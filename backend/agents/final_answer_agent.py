import json
from langfuse import observe
from agents.llm_utils import run_llm, ask_user, load_prompt
from db.tools import get_policy_details, get_auto_policy_details, get_claim_status, get_billing_info, get_payment_history

@observe(name="final_answer_agent")
def final_answer_agent(state,logger,client):
    """Generate a clean final summary before ending the conversation"""
    print("---FINAL ANSWER AGENT---")
    logger.info("🎯 Final answer agent started")

    user_query = state["user_input"]
    conversation_history = state.get("conversation_history", "")

    # Extract the most recent specialist response
    recent_responses = []
    for msg in reversed(state.get("messages", [])):
        if hasattr(msg, 'content') and "clarification" not in msg.content.lower():
            recent_responses.append(msg.content)
            if len(recent_responses) >= 2:  # Get last 2 non-clarification responses
                break

    specialist_response = recent_responses[0] if recent_responses else "No response available"
    FINAL_ANSWER_PROMPT=load_prompt("final_answer_agent")
    prompt = FINAL_ANSWER_PROMPT.format(

        specialist_response=specialist_response,
        user_query=user_query,
    )

    print("🤖 Generating final summary...")
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role": "system", "content": prompt}]
    )

    final_answer = response.choices[0].message.content

    print(f"✅ Final answer: {final_answer}")

    # Replace all previous messages with just the final answer
    clean_messages = [("assistant", final_answer)]

    state["final_answer"] = final_answer
    state["end_conversation"] = True
    state["conversation_history"] = conversation_history + f"\nAssistant: {final_answer}"
    state["messages"] = clean_messages

    return state



