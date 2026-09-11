import json
from langfuse import observe
from agents.llm_utils import run_llm, ask_user, load_prompt
from db.tools import get_policy_details, get_auto_policy_details, get_claim_status, get_billing_info, get_payment_history

@observe(name="supervisor_agent")
def supervisor_agent(state, client, logger):
    print("---SUPERVISOR AGENT---")
    # Increment iteration counter
    n_iter = state.get("n_iteration", 0) + 1
    state["n_iteration"] = n_iter
    print(f"🔢 Supervisor iteration: {n_iter}")

    # Force end if iteration limit reached
    # Escalate to human support if iteration limit reached
    if n_iter >= 3:
        print("⚠️ Maximum supervisor iterations reached — escalating to human agent")
        updated_history = (
            state.get("conversation_history", "")
            + "\nAssistant: It seems this issue requires human review. Escalating to a human support specialist."
        )
        return {
            "escalate_to_human": True,
            "conversation_history": updated_history,
            "next_agent": "human_escalation_agent",
            "n_iteration": n_iter
        }

    # Check if we're coming from a clarification
    if state.get("needs_clarification", False):
        user_clarification = state.get("user_clarification", "")
        print(f"🔄 Processing user clarification: {user_clarification}")

        # Update conversation history with the clarification exchange
        clarification_question = state.get("clarification_question", "")
        updated_conversation = state.get("conversation_history", "") + f"\nAssistant: {clarification_question}\nUser: {user_clarification}"

        # Update state to clear clarification flags and update history
        updated_state = state.copy()
        updated_state["needs_clarification"] = False
        updated_state["conversation_history"] = updated_conversation

        # Clear clarification fields
        if "clarification_question" in updated_state:
            del updated_state["clarification_question"]
        if "user_clarification" in updated_state:
            del updated_state["user_clarification"]

        return updated_state

    user_query = state["user_input"]
    conversation_history = state.get("conversation_history", "")


    print(f"User Query: {user_query}")
    print(f"Conversation History: {conversation_history}")


    # Include the ENTIRE conversation history in the prompt
    full_context = f"Full Conversation:\n{conversation_history}"

    SUPERVISOR_PROMPT=load_prompt("supervisor")
    prompt = SUPERVISOR_PROMPT.format(
        conversation_history=full_context  # Use full context instead of just history
    )

    tools = [
        {
            "type": "function",
            "function": {
                "name": "ask_user",
                "description": "Ask the user for clarification or additional information when their query is unclear or missing important details. ONLY use this if essential information like policy number or customer ID is missing.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The specific question to ask the user for clarification"
                        },
                        "missing_info": {
                            "type": "string",
                            "description": "What specific information is missing or needs clarification"
                        }
                    },
                    "required": ["question", "missing_info"]
                }
            }
        }
    ]

    print("🤖 Calling LLM for supervisor decision...")
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role": "system", "content": prompt}],
        tools=tools,
        tool_choice="auto"
    )

    message = response.choices[0].message

    # Check if supervisor wants to ask user for clarification
    if getattr(message, "tool_calls", None):
        print("🛠️ Supervisor requesting user clarification")
        for tool_call in message.tool_calls:
            if tool_call.function.name == "ask_user":
                args = json.loads(tool_call.function.arguments)
                question = args.get("question", "Can you please provide more details?")
                missing_info = args.get("missing_info", "additional information")

                print(f"❓ Asking user: {question}")


                user_response_data = ask_user(logger, question, missing_info)
                user_response = user_response_data["context"]

                print(f"✅ User response: {user_response}")

                # Update conversation history with the question
                updated_history = conversation_history + f"\nAssistant: {question}"
                updated_history = updated_history + f"\nUser: {user_response}"

                return {
                    "needs_clarification": True,
                    "clarification_question": question,
                    "user_clarification": user_response,
                    "conversation_history": updated_history
                }

    # If no tool calls, proceed with normal supervisor decision
    message_content = message.content

    try:
        parsed = json.loads(message_content)
        print("✅ Supervisor output parsed successfully")
    except json.JSONDecodeError:
        print("❌ Supervisor output invalid JSON, using fallback")
        parsed = {}

    next_agent = parsed.get("next_agent", "general_help_agent")
    task = parsed.get("task", "Assist the user with their query.")
    justification = parsed.get("justification", "")

    print(f"---SUPERVISOR DECISION: {next_agent}---")
    print(f"Task: {task}")
    print(f"Reason: {justification}")

    # Update conversation history with the current exchange
    updated_conversation = conversation_history + f"\nAssistant: Routing to {next_agent} for: {task}"


    print(f"➡️ Routing to: {next_agent}")
    return {
        "next_agent": next_agent,
        "task": task,
        "justification": justification,
        "conversation_history": updated_conversation,
        "n_iteration": n_iter
    }

