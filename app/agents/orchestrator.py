"""Graph assembly. Hub-and-spoke supervisor loop with three first-class
outcomes: answer | clarification | escalation.

Node names are contract keys: they must match prompts/*.yaml filenames and
the router's tier map (app/llm/router.py).
"""
from langgraph.graph import END, StateGraph

from app.agents.specialists import BillingAgent, ClaimsAgent, GeneralHelpAgent, PolicyAgent
from app.agents.state import GraphState
from app.agents.supervisor import supervisor_node
from app.agents.terminal import escalation_node, final_answer_node
from app.tracing import get_tracer


def route_after_supervisor(state: GraphState) -> str:
    """Priority-ordered decision — plain code (LLMs reason; systems decide)."""
    if state.get("outcome") == "clarification":
        route = "clarify"
    elif state.get("outcome") == "answer":
        route = "direct"  # supervisor answered directly (small talk / out-of-scope)
    elif state.get("requires_human_escalation"):
        route = "human_escalation_agent"
    else:
        next_agent = state.get("next_agent", "general_help_agent")
        route = "final_answer_agent" if next_agent == "end" else next_agent
    get_tracer().log_route(
        next_agent=route, outcome=state.get("outcome"), state=dict(state)
    )
    return route


def _traced_node(name: str, node):
    def invoke(state, config):
        tracer = get_tracer()
        with tracer.observation(
            f"graph:{name}",
            input={
                "user_input": state.get("user_input", ""),
                "task": state.get("task", ""),
                "iteration": state.get("n_iteration", 0),
            },
            metadata={"node": name},
        ) as span:
            output = node(state, config)
            if span:
                # Record both output and post‑execution state snapshot.
                try:
                    span.update(output=output, metadata={"post_state": dict(state)})
                except Exception:
                    # Fallback – just record the output if state cannot be serialized.
                    span.update(output=output)
            # Log a dedicated state span for deeper inspection.
            tracer.log_state(node=name, state=dict(state))
            return output

    return invoke


def build_graph():
    g = StateGraph(GraphState)

    g.add_node("supervisor_agent", _traced_node("supervisor_agent", supervisor_node))
    g.add_node("policy_agent", _traced_node("policy_agent", PolicyAgent()))
    g.add_node("billing_agent", _traced_node("billing_agent", BillingAgent()))
    g.add_node("claims_agent", _traced_node("claims_agent", ClaimsAgent()))
    g.add_node("general_help_agent", _traced_node("general_help_agent", GeneralHelpAgent()))
    g.add_node("final_answer_agent", _traced_node("final_answer_agent", final_answer_node))
    g.add_node("human_escalation_agent", _traced_node("human_escalation_agent", escalation_node))

    g.set_entry_point("supervisor_agent")
    g.add_conditional_edges(
        "supervisor_agent",
        route_after_supervisor,
        {
            "clarify": END,  # clarification question returns to the user as the reply
            "direct": END,   # supervisor's own reply is the final answer
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
