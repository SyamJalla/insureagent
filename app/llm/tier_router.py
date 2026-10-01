"""Tier-based request routing — Tier 3 Laya domain classifier.

Tier 1 → OpenAI gateway (role-specific models)
Tier 2 → Groq gateway   (role-specific models)
Tier 3 → Laya classifier selects domain → Groq open-source worker

This module is the ONLY place that knows about Laya.  Everything above it
(runner, orchestrator, specialists) stays unchanged.
"""
import logging

from app.config import get_settings

logger = logging.getLogger("insureagent.tier_router")

# Map Laya classification labels → existing specialist agent names.
# These names must match the node names in app/agents/orchestrator.py.
_DOMAIN_TO_AGENT: dict[str, str] = {
    "billing": "billing_agent",
    "policy":  "policy_agent",
    "claims":  "claims_agent",
}


class TierRouter:
    """Encapsulates Tier-3 Laya-based domain routing.

    Usage (in runner or orchestrator):
        tier_router = TierRouter()
        agent_override, model = tier_router.resolve(user_input)
        # agent_override is None when falling back to Tier-2 Groq
    """

    def __init__(self, tier: int | None = None):
        s = get_settings()
        self._tier = tier if tier is not None else s.active_tier
        self._threshold = s.tier3_confidence_threshold
        self._tier3_model = s.tier3_worker_model
        self._tier2_model = s.tier2_specialist_model

        # Lazily build Laya classifier only when Tier 3 is active
        self._laya = None
        if self._tier == 3 and s.laya_api_key:
            from app.llm.provider import LayaClassifier
            self._laya = LayaClassifier(
                api_key=s.laya_api_key,
                base_url=s.laya_base_url,
                model=s.tier3_router_model,
            )
        elif self._tier == 3 and not s.laya_api_key:
            logger.warning(
                "ACTIVE_TIER=3 but LAYA_API_KEY is missing — "
                "Tier 3 will always fall back to Tier-2 Groq."
            )

    # ── Public API ───────────────────────────────────────────────────────

    def resolve(self, user_input: str) -> tuple[str | None, str]:
        """Determine (agent_name_override, groq_model) for the current tier.

        Returns:
            (agent_name_override, model)
            - agent_name_override: one of the _DOMAIN_TO_AGENT values, or None
              when no domain override is needed (Tier 1/2, or Tier-3 fallback).
            - model: the Groq model string to use for this request.

        Tier 1 callers should not use this method — they use the OpenAI gateway.
        """
        if self._tier != 3 or self._laya is None:
            # Tier 2: no Laya, no override — just use the Groq model.
            return None, self._tier2_model

        # ── Tier 3: call Laya to classify the user input ─────────────────
        from app.agents.prompt_source import get_prompt_source
        router_prompt = get_prompt_source(tier=3).get("router")
        result = self._laya.classify(user_input, router_prompt)

        logger.info(
            "🔀 laya classify | decision=%s confidence=%.3f",
            result["decision"], result["confidence"],
        )

        if (
            result["confidence"] >= self._threshold
            and result["decision"] in _DOMAIN_TO_AGENT
        ):
            agent_name = _DOMAIN_TO_AGENT[result["decision"]]
            logger.info("🔀 tier3 → domain=%s agent=%s", result["decision"], agent_name)
            return agent_name, self._tier3_model

        # Low-confidence or 'fallback' label → degrade to Tier-2 Groq
        logger.warning(
            "🔀 laya confidence %.3f below threshold %.2f or decision=%r "
            "— falling back to Tier-2 Groq",
            result["confidence"], self._threshold, result["decision"],
        )
        return None, self._tier2_model

    @property
    def active_tier(self) -> int:
        return self._tier
