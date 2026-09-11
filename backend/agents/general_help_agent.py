import json
from langfuse import observe
from agents.llm_utils import run_llm, ask_user, load_prompt
from db.tools import get_policy_details, get_auto_policy_details, get_claim_status, get_billing_info, get_payment_history

@observe(name="general_help_agent")
def general_help_agent_node(state,logger,client,collection):
    print("---GENERAL HELP AGENT---")

    user_query = state.get("user_input", "")
    conversation_history = state.get("conversation_history", "")
    task = state.get("task", "General insurance support")

    # Step 1: Retrieve relevant FAQs from the vector DB
    print("🔍 Retrieving FAQs...")
    logger.info("🔍 Retrieving FAQs from vector database")
    results = collection.query(
        query_texts=[user_query],
        n_results=3,
        include=["metadatas", "documents", "distances"]
    )

    # Step 2: Format retrieved FAQs
    faq_context = ""
    if results and results.get("metadatas") and results["metadatas"][0]:
        print(f"📚 Found {len(results['metadatas'][0])} relevant FAQs")
        for i, meta in enumerate(results["metadatas"][0]):
            q = meta.get("question", "")
            a = meta.get("answer", "")
            score = results["distances"][0][i]
            faq_context += f"FAQ {i+1} (score: {score:.3f})\nQ: {q}\nA: {a}\n\n"
    else:
        print("❌ No relevant FAQs found")
        faq_context = "No relevant FAQs were found."

    GENERAL_HELP_PROMPT=load_prompt("general_help_agent")
    # Step 3: Format the final prompt
    prompt = GENERAL_HELP_PROMPT.format(
        task=task,
        conversation_history=conversation_history,
        faq_context=faq_context
    )

    print("🤖 Calling LLM for general response...")
    final_answer = run_llm(client,prompt)



    print("✅ General help agent completed")
    updated_state = {
                        "messages": [("assistant", final_answer)],
                        "retrieved_faqs": results.get("metadatas", []),
                    }


    updated_state["conversation_history"] = conversation_history + f"\nGeneral Help Agent: {final_answer}"

    return updated_state

