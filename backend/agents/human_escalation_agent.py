import json
from langfuse import observe
from agents.llm_utils import run_llm, ask_user, load_prompt
from db.tools import get_policy_details, get_auto_policy_details, get_claim_status, get_billing_info, get_payment_history

@observe(name="human_escalation_agent")
def human_escalation_node(state,logger,client):
    print("---HUMAN ESCALATION AGENT---")
    logger.warning(f"Escalation triggered - State: { {k: v for k, v in state.items() if k != 'messages'} }")

    HUMAN_ESCALATION_PROMPT=load_prompt("human_escalation_agent")
    prompt = HUMAN_ESCALATION_PROMPT.format(
        task=state.get("task"),
        #user_query=state.get("user_input"),
        conversation_history=state.get("conversation_history", "")
    )

    print("🤖 Generating escalation response...")
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role": "system", "content": prompt}]
    )

    print("🚨 Conversation escalated to human")
    return {
        "final_answer": response.choices[0].message.content,
        "requires_human_escalation": True,
        "escalation_reason": "Customer requested human assistance.",
        "messages": [("assistant", response.choices[0].message.content)]
    }



