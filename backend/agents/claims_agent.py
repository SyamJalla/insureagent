import json
from langfuse import observe
from agents.llm_utils import run_llm, ask_user, load_prompt
from db.tools import get_policy_details, get_auto_policy_details, get_claim_status, get_billing_info, get_payment_history

@observe(name="claims_agent")
def claims_agent_node(state,logger,client):
    logger.info("🏥 Claims agent started")
    logger.debug(f"Claims agent state: { {k: v for k, v in state.items() if k != 'messages'} }")
    CLAIMS_AGENT_PROMPT=load_prompt("claims_agent")
    prompt = CLAIMS_AGENT_PROMPT.format(
        task=state.get("task"),
        policy_number=state.get("policy_number", "Not provided"),
        claim_id=state.get("claim_id", "Not provided"),
        conversation_history=state.get("conversation_history", "")
    )

    tools = [
        {"type": "function", "function": {
            "name": "get_claim_status",
            "description": "Retrieve claim details",
            "parameters": {"type": "object", "properties": {"claim_id": {"type": "string"}, "policy_number": {"type": "string"}}}
        }}
    ]

    

    result = run_llm(
        client,
        prompt,
        tools,
        {
            "get_claim_status": lambda **kwargs: get_claim_status(logger, **kwargs)
            
        }
    )

    logger.info("✅ Claims agent completed")
    return {"messages": [("assistant", result)]}

