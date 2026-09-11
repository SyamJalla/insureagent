from typing import TypedDict, List, Annotated, Dict, Any, Optional
from langgraph.graph import StateGraph, END, add_messages
from langfuse import observe
from core.config import tracer
from agents.llm_utils import trace_agent
from agents.supervisor import supervisor_agent
from agents.claims_agent import claims_agent_node
from agents.final_answer_agent import final_answer_agent
from agents.policy_agent import policy_agent_node
from agents.billing_agent import billing_agent_node
from agents.general_help_agent import general_help_agent_node
from agents.human_escalation_agent import human_escalation_node

class GraphState(TypedDict):
    # Core conversation tracking
    messages: Annotated[List[Any], add_messages]
    user_input: str
    conversation_history: Optional[str]

    n_iteration: Optional[int]

    # Extracted context & metadata
    user_intent: Optional[str]            # e.g., "query_policy", "billing_issue"
    customer_id: Optional[str]
    policy_number: Optional[str]
    claim_id: Optional[str]

    # Supervisor / routing layer
    next_agent: Optional[str]             # e.g., "policy_agent", "claims_agent", etc.
    task: Optional[str]                   # Current task determined by supervisor
    justification: Optional[str]          # Supervisor reasoning/explanation
    end_conversation: Optional[bool]      # Flag for graceful conversation termination

    # Entity extraction and DB lookups
    extracted_entities: Dict[str, Any]    # Parsed from user input (dates, names, etc.)
    database_lookup_result: Dict[str, Any]

    # Escalation state
    requires_human_escalation: bool
    escalation_reason: Optional[str]

    # Billing-specific fields
    billing_amount: Optional[float]
    payment_method: Optional[str]
    billing_frequency: Optional[str]      # "monthly", "quarterly", "annual"
    invoice_date: Optional[str]

    # System-level metadata
    timestamp: Optional[str]     # Track time of latest user message or state update
    final_answer: Optional[str]


def decide_next_agent(state):
    # Handle clarification case first
    if state.get("needs_clarification"):
        return "supervisor_agent"  # Return to supervisor to process the clarification

    if state.get("end_conversation"):
        return "end"

    if state.get("requires_human_escalation"):
        return "human_escalation_agent"

    return state.get("next_agent", "general_help_agent")



def run_workflow(client, logger, langfuse, collection):

    workflow = StateGraph(GraphState)

    # Wrapped nodes
    supervisor = trace_agent(
        
        "supervisor_agent"
    )(lambda state: supervisor_agent(state, client, logger))

    billing = trace_agent(
        
        "billing_agent"
    )(lambda state: billing_agent_node(state,logger,client))

    policy = trace_agent(
        
        "policy_agent"
    )(lambda state: policy_agent_node(state, logger,client))

    claims = trace_agent(
        
        "claims_agent"
    )(lambda state: claims_agent_node(state, logger,client))

    general = trace_agent(
        
        "general_help_agent"
    )(lambda state: general_help_agent_node(
        state,
        logger,
        client,
        collection
    ))

    final_agent = trace_agent(
        
        "final_answer_agent"
    )(lambda state: final_answer_agent(
        state,
        logger,
        client
    ))

    human = trace_agent(
        
        "human_escalation_agent"
    )(lambda state: human_escalation_node(
        state,
        logger,
        client
    ))

    workflow.add_node("supervisor_agent", supervisor)
    workflow.add_node("billing_agent", billing)
    workflow.add_node("policy_agent", policy)
    workflow.add_node("claims_agent", claims)
    workflow.add_node("general_help_agent", general)
    workflow.add_node("final_answer_agent", final_agent)
    workflow.add_node("human_escalation_agent", human)

    workflow.set_entry_point("supervisor_agent")

    workflow.add_conditional_edges(
        "supervisor_agent",
        decide_next_agent,
        {
            "supervisor_agent": "supervisor_agent",
            "policy_agent": "policy_agent",
            "billing_agent": "billing_agent",
            "claims_agent": "claims_agent",
            "general_help_agent": "general_help_agent",
            "human_escalation_agent": "human_escalation_agent",
            "end": "final_answer_agent"
        }
    )

    workflow.add_edge("billing_agent", "supervisor_agent")
    workflow.add_edge("policy_agent", "supervisor_agent")
    workflow.add_edge("claims_agent", "supervisor_agent")
    workflow.add_edge("general_help_agent", "supervisor_agent")

    workflow.add_edge("final_answer_agent", END)
    workflow.add_edge("human_escalation_agent", END)

    return workflow.compile()

# === Display the Graph ===
#from IPython.display import Image, display

#def display_workflow(app):
    #display(Image(app.get_graph().draw_mermaid_png()))





@observe(name="insurance_query")
def run_test_query(query, app, langfuse):

    initial_state = {
        "n_iteration": 0,
        "messages": [],
        "user_input": query,
        "user_intent": "",
        "claim_id": "",
        "next_agent": "supervisor_agent",
        "extracted_entities": {},
        "database_lookup_result": {},
        "requires_human_escalation": False,
        "escalation_reason": "",
        "billing_amount": None,
        "payment_method": None,
        "billing_frequency": None,
        "invoice_date": None,
        "conversation_history": f"User: {query}",
        "task": "Help user with their query",
        "final_answer": ""
    }

    print(f"\n{'=' * 50}")
    print(f"QUERY: {query}")
    print(f"{'=' * 50}\n")

    try:

        final_state = app.invoke(initial_state)

        final_answer = final_state.get(
            "final_answer",
            "No final answer generated."
        )

        print("\n---FINAL RESPONSE---")
        print(final_answer)

        return final_state

    except Exception as e:

        print(f"\n❌ Error running workflow: {e}")

        raise

    finally:

        langfuse.flush()