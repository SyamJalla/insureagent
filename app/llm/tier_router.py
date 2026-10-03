"""Tier-based request routing — Tier 3 Laya decision classifier.

Tier 1 → OpenAI gateway (role-specific models)
Tier 2 → Groq gateway   (role-specific models)
Tier 3 → Laya selects domain → Groq open-source worker

This module owns Tier 3 classifier integration. Everything above it
(runner, orchestrator, specialists) stays unchanged.
"""
import logging
from pathlib import Path

import yaml

from app.config import get_settings

logger = logging.getLogger("insureagent.tier_router")

# Map Laya decision labels → existing specialist agent names.
# These names must match the node names in app/agents/orchestrator.py.
_DOMAIN_TO_AGENT: dict[str, str] = {
    "billing": "billing_agent",
    "policy":  "policy_agent",
    "claims":  "claims_agent",
}


def _load_router_config() -> dict:
    with Path("prompts/tier3/router.yaml").open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


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

        self._classifier = None
        if self._tier == 3:
            from app.llm.provider import LayaClassifier

            self._classifier = LayaClassifier()
            logger.info("Tier 3 using local Laya router")

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
        if self._tier != 3 or self._classifier is None:
            # If no classifier is available, use the Tier 2 Groq model.
            return None, self._tier2_model

        result = self._classifier.classify(user_input, _load_router_config())

        print(
            f"[tier3] decision={result['decision']} confidence={result['confidence']:.3f} "
            f"threshold={self._threshold:.2f}"
        )
        logger.info(
            "tier3 decision | decision=%s confidence=%.3f",
            result["decision"], result["confidence"],
        )

        if (
            result["confidence"] >= self._threshold
            and result["decision"] in _DOMAIN_TO_AGENT
        ):
            agent_name = _DOMAIN_TO_AGENT[result["decision"]]
            print(f"[tier3] route to {agent_name} via domain={result['decision']}")
            logger.info("🔀 tier3 → domain=%s agent=%s", result["decision"], agent_name)
            return agent_name, self._tier3_model

        # Low-confidence or 'fallback' label → degrade to Tier-2 Groq
        print(
            f"[tier3] falling back to Tier-2 Groq because confidence={result['confidence']:.3f} "
            f"decision={result['decision']}"
        )
        logger.warning(
            "tier3 confidence %.3f below threshold %.2f or decision=%r "
            "— falling back to Tier-2 Groq",
            result["confidence"], self._threshold, result["decision"],
        )
        return None, self._tier2_model

    @property
    def active_tier(self) -> int:
        return self._tier
