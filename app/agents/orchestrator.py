"""Graph assembly. Hub-and-spoke supervisor loop with three first-class
outcomes: answer | clarification | escalation.

Node names match the retired POC graph (and prompts/router tier keys).
"""
from langgraph.graph import END, StateGraph

from app.agents.specialists import BillingAgent, ClaimsAgent, GeneralHelpAgent, PolicyAgent
from app.agents.state import GraphState
from app.agents.supervisor import supervisor_node
from app.agents.terminal import escalation_node, final_answer_node


def route_after_supervisor(state: GraphState) -> str:
    """Priority-ordered decision — plain code (LLMs reason; systems decide)."""
    if state.get("outcome") == "clarification":
        return "clarify"
    if state.get("requires_human_escalation"):
        return "human_escalation_agent"
    next_agent = state.get("next_agent", "general_help_agent")
    if next_agent == "end":
        return "final_answer_agent"
    return next_agent


def build_graph():
    g = StateGraph(GraphState)

    g.add_node("supervisor_agent", supervisor_node)
    g.add_node("policy_agent", PolicyAgent())
    g.add_node("billing_agent", BillingAgent())
    g.add_node("claims_agent", ClaimsAgent())
    g.add_node("general_help_agent", GeneralHelpAgent())
    g.add_node("final_answer_agent", final_answer_node)
    g.add_node("human_escalation_agent", escalation_node)

    g.set_entry_point("supervisor_agent")
    g.add_conditional_edges(
        "supervisor_agent",
        route_after_supervisor,
        {
            "clarify": END,  # clarification question returns to the user as the reply
            "policy_agent": "policy_agent",
            "billing_agent": "billing_agent",
            "claims_agent": "claims_agent",
            "general_help_agent": "general_help_agent",
            "final_answer_agent": "final_answer_agent",
            "human_escalation_agent": "human_escalation_agent",
        },
    )
    for specialist in ("policy_agent", "billing_agent", "claims_agent", "general_help_agent"):
        g.add_edge(specialist, "supervisor_agent")
    g.add_edge("final_answer_agent", END)
    g.add_edge("human_escalation_agent", END)
    return g.compile()
