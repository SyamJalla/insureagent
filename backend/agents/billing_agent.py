import json
from langfuse import observe
from agents.llm_utils import run_llm, ask_user, load_prompt
from db.tools import get_policy_details, get_auto_policy_details, get_claim_status, get_billing_info, get_payment_history

@observe(name="billing_agent")
def billing_agent_node(state,logger,client):
    print("---BILLING AGENT---")
    print("TASK: ", state.get("task"))
    print("USER QUERY: ", state.get("user_input"))
    print("CONVERSATION HISTORY: ", state.get("conversation_history", ""))

    BILLING_AGENT_PROMPT=load_prompt("billing_agent")
    prompt = BILLING_AGENT_PROMPT.format(
        task=state.get("task"),
        conversation_history=state.get("conversation_history", "")
    )

    tools = [
        {"type": "function", "function": {
            "name": "get_billing_info",
            "description": "Retrieve billing information",
            "parameters": {"type": "object", "properties": {"policy_number": {"type": "string"}, "customer_id": {"type": "string"}}}
        }},
        {"type": "function", "function": {
            "name": "get_payment_history",
            "description": "Fetch recent payment history",
            "parameters": {"type": "object", "properties": {"policy_number": {"type": "string"}}}
        }}
    ]

    print("🔄 Processing billing request...")
    

    result = run_llm(
        client,
        prompt,
        tools,
        {
            "get_billing_info": lambda **kwargs: get_billing_info(logger, **kwargs),
            "get_payment_history": lambda **kwargs: get_payment_history(logger, **kwargs)
        }
    )

    print("✅ Billing agent completed")

    # Extract and preserve policy number if mentioned in the conversation
    updated_state = {"messages": [("assistant", result)]}

    # If we have a policy number in state, preserve it
    if state.get("policy_number"):
        updated_state["policy_number"] = state["policy_number"]
    if state.get("customer_id"):
        updated_state["customer_id"] = state["customer_id"]

    # Update conversation history
    current_history = state.get("conversation_history", "")
    updated_state["conversation_history"] = current_history + f"\nBilling Agent: {result}"

    return updated_state


