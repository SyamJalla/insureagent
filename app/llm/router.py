"""Model routing policy.

Flag OFF (default): static per-node tiers — the graph's shape already encodes
complexity (supervisor plans; specialists do narrow extract-and-call work).
Flag ON: the supervisor's complexity score upgrades/downgrades the tier.

Both paths stay unit-tested regardless of the flag, so flipping it is a
config change, not a debugging session.
"""
from app.llm.models import Complexity, ModelTier

# Static tier per calling node (flag off, and the baseline when on).
STATIC_TIERS: dict[str, ModelTier] = {
    "supervisor_agent": ModelTier.STANDARD,
    "policy_agent": ModelTier.FAST,
    "billing_agent": ModelTier.FAST,
    "claims_agent": ModelTier.FAST,
    "general_help_agent": ModelTier.FAST,
    "final_answer_agent": ModelTier.FAST,
    "human_escalation_agent": ModelTier.FAST,
}
DEFAULT_TIER = ModelTier.STANDARD

# Flag on: how a complexity score shifts a specialist's tier.
_COMPLEXITY_TIER: dict[Complexity, ModelTier] = {
    Complexity.SIMPLE: ModelTier.FAST,
    Complexity.STANDARD: ModelTier.STANDARD,
    Complexity.COMPLEX: ModelTier.REASONING,
}


class ModelRouter:
    def __init__(self, complexity_routing_enabled: bool):
        self._complexity_enabled = complexity_routing_enabled

    def tier_for(self, agent: str, complexity: Complexity | None) -> ModelTier:
        base = STATIC_TIERS.get(agent, DEFAULT_TIER)
        if not self._complexity_enabled or complexity is None:
            return base
        # Supervisor always keeps its static tier — it produces the score.
        if agent == "supervisor_agent":
            return base
        routed = _COMPLEXITY_TIER[complexity]
        # Never downgrade below the static baseline's intent for terminal nodes
        return routed
