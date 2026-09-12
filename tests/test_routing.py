"""Routing-function tests — pure code, no LLM."""
from app.agents.orchestrator import route_after_supervisor


def test_clarification_ends_graph():
    assert route_after_supervisor({"outcome": "clarification"}) == "clarify"


def test_direct_answer_ends_graph():
    assert route_after_supervisor({"outcome": "answer", "final_answer": "Hi!"}) == "direct"


def test_escalation_flag_routes_to_human():
    assert route_after_supervisor({"requires_human_escalation": True}) == "human_escalation_agent"


def test_end_routes_to_final_answer():
    assert route_after_supervisor({"next_agent": "end"}) == "final_answer_agent"


def test_specialist_passthrough():
    assert route_after_supervisor({"next_agent": "billing_agent"}) == "billing_agent"


def test_default_is_general_help():
    assert route_after_supervisor({}) == "general_help_agent"


def test_priority_clarification_beats_escalation():
    state = {"outcome": "clarification", "requires_human_escalation": True}
    assert route_after_supervisor(state) == "clarify"
