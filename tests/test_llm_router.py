"""Router policy tests — both flag states, so flipping the env flag later is
a config change, not a debugging session."""
from app.llm.models import Complexity, ModelTier
from app.llm.router import ModelRouter


def test_flag_off_static_tiers():
    r = ModelRouter(complexity_routing_enabled=False)
    assert r.tier_for("supervisor_agent", Complexity.COMPLEX) == ModelTier.STANDARD
    assert r.tier_for("policy_agent", Complexity.COMPLEX) == ModelTier.FAST
    assert r.tier_for("final_answer_agent", None) == ModelTier.FAST


def test_flag_on_complexity_upgrades_specialists():
    r = ModelRouter(complexity_routing_enabled=True)
    assert r.tier_for("policy_agent", Complexity.SIMPLE) == ModelTier.FAST
    assert r.tier_for("policy_agent", Complexity.STANDARD) == ModelTier.STANDARD
    assert r.tier_for("claims_agent", Complexity.COMPLEX) == ModelTier.REASONING


def test_flag_on_supervisor_keeps_static_tier():
    r = ModelRouter(complexity_routing_enabled=True)
    assert r.tier_for("supervisor_agent", Complexity.COMPLEX) == ModelTier.STANDARD


def test_unknown_agent_gets_default():
    r = ModelRouter(complexity_routing_enabled=False)
    assert r.tier_for("mystery_agent", None) == ModelTier.STANDARD
