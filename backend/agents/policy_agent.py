import json
from langfuse import observe
from agents.llm_utils import run_llm, ask_user, load_prompt
from db.tools import get_policy_details, get_auto_policy_details, get_claim_status, get_billing_info, get_payment_history

@observe(name="policy_agent")
def policy_agent_node(state,logger,client):
    print("---POLICY AGENT---")
    logger.info("📄 Policy agent started")
    logger.debug(f"Policy agent state: { {k: v for k, v in state.items() if k != 'messages'} }")
    POLICY_AGENT_PROMPT=load_prompt("policy_agent")
    prompt = POLICY_AGENT_PROMPT.format(
        task=state.get("task"),
        policy_number=state.get("policy_number", "Not provided"),
        customer_id=state.get("customer_id", "Not provided"),
        conversation_history=state.get("conversation_history", "")
    )

    tools = [
        {"type": "function", "function": {
            "name": "get_policy_details",
            "description": "Fetch policy info by policy number",
            "parameters": {"type": "object", "properties": {"policy_number": {"type": "string"}}}
        }},
        {"type": "function", "function": {
            "name": "get_auto_policy_details",
            "description": "Get auto policy details",
            "parameters": {"type": "object", "properties": {"policy_number": {"type": "string"}}}
        }}
    ]

    print("🔄 Processing policy request...")
    

    result = run_llm(
        client,
        prompt,
        tools,
        {
            "get_policy_details": lambda **kwargs: get_policy_details(logger, **kwargs),
            "get_auto_policy_details": lambda **kwargs: get_auto_policy_details(logger, **kwargs)
        }
    )

    print("✅ Policy agent completed")
    return {"messages": [("assistant", result)]}

