from datasets import load_dataset
import pandas as pd
import chromadb
from tqdm import tqdm
import numpy as np
from datetime import datetime, timedelta
import random
import json
from functools import wraps
import time

from app import enterprise_db

from typing import TypedDict,List,Annotated, Dict, Any, Optional
import logging
from datetime import datetime
from langgraph.graph import StateGraph, END
from langgraph.graph import add_messages
from langfuse import Langfuse, observe
from openai import OpenAI

from opentelemetry import trace
import os
import yaml


logger_name='insurance_agent.log'
tracer = trace.get_tracer(__name__)



#create faq dataset
def create_faq_dataset():
    # Load the dataset from Hugging Face
    ds = load_dataset("deccan-ai/insuranceQA-v2")

    # Combine all splits into a single DataFrame
    df = pd.concat([split.to_pandas() for split in ds.values()], ignore_index=True)
    df["combined"] = "Question: " + df["input"] + " \n Answer:  " + df["output"]
    df.to_csv("insurance_faq.csv", index=False)
    return df

collection_name="insurance_FAQ_collection"
def create_chroma_client(persist_directory):
    # Setting up the Chromadb
    chroma_client = chromadb.PersistentClient(path=persist_directory)
    
    return chroma_client



def create_chroma_vector_db(chroma_client,collection_name):
    
    collection = chroma_client.get_or_create_collection(name=collection_name)
    return collection

def add_data_to_collection(df,collection):
    # Collection 1 for insurance Q&A Dataset

    df = df.sample(500, random_state=42).reset_index(drop=True)  # For testing, use a smaller subset
    # Add data to collection
    # here the chroma db will use default embeddings (sentence transformers)
    # Split into batches of <= 5000
    batch_size = 100

    for i in tqdm(range(0, len(df), batch_size)):
        batch_df = df.iloc[i:i+batch_size]
        collection.add(
            documents=batch_df["combined"].tolist(),
            metadatas=[{"question": q, "answer": a} for q, a in zip(batch_df["input"], batch_df["output"])],
            ids=batch_df.index.astype(str).tolist()
        )

query = "What does life insurance cover?"
def retrieve_data(query,chroma_client,collection_name):
    collection = chroma_client.get_collection(name=collection_name)
    results = collection.query(
        query_texts=[query],
        n_results=3,
    )
    return results

def print_query_results(results):
    for i, m in enumerate(results["metadatas"][0]):
        print(f"Result {i+1}:")
        print("Distance:", results["distances"][0][i])
        print("Q:", m["question"])
        print("A:", m["answer"])
        print("-" * 50)



# Data generation moved to scripts/seed_enterprise.py; enterprise DB access via app.enterprise_db.

def create_langfuse():

    return Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        host=os.getenv("LANGFUSE_BASE_URL")
    )


from functools import wraps

def trace_agent(agent_name):

    def decorator(func):

        @wraps(func)
        @observe(name=agent_name)
        def wrapper(state):

            with tracer.start_as_current_span(agent_name) as span:

                span.set_attribute(
                    "agent.name",
                    agent_name
                )

                span.set_attribute(
                    "user_input",
                    state.get("user_input", "")
                )

                span.set_attribute(
                    "task",
                    state.get("task", "")
                )

                result = func(state)

                if isinstance(result, dict):

                    span.set_attribute(
                        "next_agent",
                        str(result.get("next_agent", ""))
                    )

                return result

        return wrapper

    return decorator


def create_client(openai_api_key):
    client = OpenAI(api_key=openai_api_key)
    return client



@observe(name="run_llm")
def run_llm(
    client,
    prompt: str,
    tools=None,
    tool_functions=None,
    model="gpt-4o-mini",
):
    

    messages = [{"role": "user", "content": prompt}]

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools if tools else None,
        tool_choice="auto" if tools else None
    )

    message = response.choices[0].message

    # No tool calls
    if not message.tool_calls:
        return message.content

    tool_outputs = []

    for tool_call in message.tool_calls:

        func_name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)

        tool_fn = tool_functions.get(func_name)

        if not tool_fn:
            result = {"error": f"{func_name} not implemented"}
        else:
            result = tool_fn(**arguments)

        tool_outputs.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(result)
        })

    second_response = client.chat.completions.create(
        model=model,
        messages=[
            *messages,
            {
                "role": "assistant",
                "tool_calls": message.tool_calls
            },
            *tool_outputs
        ]
    )

    return second_response.choices[0].message.content

def add_numbers(a: int, b: int):
    return {"result": a + b}

def create_tools():
    tools = [{
        "type": "function",
        "function": {
            "name": "add_numbers",
            "description": "Add two numbers together",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"}
                },
                "required": ["a", "b"]
            },
        }
    }]
    return tools



def create_logger(logger_name):
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(logger_name),
            logging.StreamHandler()
        ]
    )
    logger = logging.getLogger(__name__)
    return logger

def ask_user(logger,question: str, missing_info: str = ""):
    """Ask the user for input and return the response."""
    logger.info(f"🗣️ Asking user for input: {question}")
    if missing_info:
        print(f"---USER INPUT REQUIRED---\nMissing information: {missing_info}")
    else:
        print(f"---USER INPUT REQUIRED---")

    answer = input(f"{question}: ")
    return {"context": answer, "source": "User Input"}

def get_policy_details(logger, policy_number):

    with tracer.start_as_current_span(
        "db_get_policy_details"
    ) as span:

        conn = None

        try:

            span.set_attribute(
                "policy_number",
                policy_number
            )

            logger.info(
                f"🔍 Fetching policy details for: {policy_number}"
            )

            conn = enterprise_db.qmark_connection()

            cursor = conn.cursor()

            span.set_attribute("db.system", "postgresql")
            span.set_attribute("db.operation", "SELECT")
            span.set_attribute("db.table", "policies")

            cursor.execute(
                """
                SELECT p.*, c.first_name, c.last_name
                FROM policies p
                JOIN customers c
                    ON p.customer_id = c.customer_id
                WHERE p.policy_number = ?
                """,
                (policy_number,)
            )

            result = cursor.fetchone()
            response = dict(zip(columns, result))

            span.set_attribute(
                "policy_type",
                str(response.get("policy_type", ""))
            )

            span.set_attribute(
                "policy_status",
                str(response.get("status", ""))
            )

            if result:

                span.set_attribute(
                    "lookup_status",
                    "found"
                )

                logger.info(
                    f"✅ Policy found: {policy_number}"
                )

                columns = [
                    desc[0]
                    for desc in cursor.description
                ]

                return dict(
                    zip(columns, result)
                )

            span.set_attribute(
                "lookup_status",
                "not_found"
            )

            logger.warning(
                f"❌ Policy not found: {policy_number}"
            )

            return {
                "error": "Policy not found"
            }

        except Exception as e:

            span.record_exception(e)

            span.set_attribute(
                "lookup_status",
                "failed"
            )
            span.set_attribute(
                "error.message",
                str(e)
            )

            logger.exception(
                f"Error retrieving policy {policy_number}"
            )

            raise

        finally:

            if conn:
                conn.close()

def get_claim_status(
    logger,
    claim_id: str = None,
    policy_number: str = None
) -> Dict[str, Any]:

    with tracer.start_as_current_span(
        "db_get_claim_status"
    ) as span:

        conn = None

        try:

            span.set_attribute(
                "db.system",
                "postgresql"
            )

            span.set_attribute(
                "db.operation",
                "SELECT"
            )

            span.set_attribute(
                "db.table",
                "claims"
            )

            if claim_id:
                span.set_attribute(
                    "claim_id",
                    claim_id
                )

            if policy_number:
                span.set_attribute(
                    "policy_number",
                    policy_number
                )

            logger.info(
                f"🔍 Fetching claim status - Claim ID: {claim_id}, Policy: {policy_number}"
            )

            conn = enterprise_db.qmark_connection()

            cursor = conn.cursor()

            if claim_id:

                cursor.execute(
                    """
                    SELECT c.*, p.policy_type
                    FROM claims c
                    JOIN policies p
                        ON c.policy_number = p.policy_number
                    WHERE c.claim_id = ?
                    """,
                    (claim_id,)
                )

            elif policy_number:

                cursor.execute(
                    """
                    SELECT c.*, p.policy_type
                    FROM claims c
                    JOIN policies p
                        ON c.policy_number = p.policy_number
                    WHERE c.policy_number = ?
                    ORDER BY c.claim_date DESC
                    LIMIT 3
                    """,
                    (policy_number,)
                )

            else:

                span.set_attribute(
                    "lookup_status",
                    "invalid_request"
                )

                return {
                    "error": "Either claim_id or policy_number is required"
                }

            results = cursor.fetchall()

            if results:

                span.set_attribute(
                    "lookup_status",
                    "found"
                )

                span.set_attribute(
                    "claim_count",
                    len(results)
                )

                logger.info(
                    f"✅ Found {len(results)} claim(s)"
                )

                columns = [
                    desc[0]
                    for desc in cursor.description
                ]

                return [
                    dict(zip(columns, row))
                    for row in results
                ]

            span.set_attribute(
                "lookup_status",
                "not_found"
            )

            logger.warning(
                "❌ No claims found"
            )

            return {
                "error": "Claim not found"
            }

        except Exception as e:

            span.record_exception(e)

            span.set_attribute(
                "lookup_status",
                "failed"
            )

            span.set_attribute(
                "error.message",
                str(e)
            )

            logger.exception(
                f"Error retrieving claim status. Claim ID={claim_id}, Policy={policy_number}"
            )

            raise

        finally:

            if conn:
                conn.close()

def get_billing_info(
    logger,
    policy_number: str = None,
    customer_id: str = None
) -> Dict[str, Any]:

    with tracer.start_as_current_span(
        "db_get_billing_info"
    ) as span:

        conn = None

        try:

            span.set_attribute(
                "db.system",
                "postgresql"
            )

            span.set_attribute(
                "db.operation",
                "SELECT"
            )

            span.set_attribute(
                "db.table",
                "billing"
            )

            if policy_number:
                span.set_attribute(
                    "policy_number",
                    policy_number
                )

            if customer_id:
                span.set_attribute(
                    "customer_id",
                    customer_id
                )

            logger.info(
                f"🔍 Fetching billing info - Policy: {policy_number}, Customer: {customer_id}"
            )

            conn = enterprise_db.qmark_connection()

            cursor = conn.cursor()

            if policy_number:

                cursor.execute(
                    """
                    SELECT b.*, p.premium_amount, p.billing_frequency
                    FROM billing b
                    JOIN policies p
                        ON b.policy_number = p.policy_number
                    WHERE b.policy_number = ?
                    AND b.status = 'pending'
                    ORDER BY b.due_date DESC
                    LIMIT 1
                    """,
                    (policy_number,)
                )

            elif customer_id:

                cursor.execute(
                    """
                    SELECT b.*, p.premium_amount, p.billing_frequency
                    FROM billing b
                    JOIN policies p
                        ON b.policy_number = p.policy_number
                    WHERE p.customer_id = ?
                    AND b.status = 'pending'
                    ORDER BY b.due_date DESC
                    LIMIT 1
                    """,
                    (customer_id,)
                )

            else:

                span.set_attribute(
                    "lookup_status",
                    "invalid_request"
                )

                return {
                    "error": "Either policy_number or customer_id is required"
                }

            result = cursor.fetchone()

            if result:

                span.set_attribute(
                    "lookup_status",
                    "found"
                )

                logger.info(
                    "✅ Billing info found"
                )

                columns = [
                    desc[0]
                    for desc in cursor.description
                ]

                response = dict(
                    zip(columns, result)
                )

                span.set_attribute(
                    "billing_status",
                    str(response.get("status", ""))
                )

                return response

            span.set_attribute(
                "lookup_status",
                "not_found"
            )

            logger.warning(
                "❌ Billing info not found"
            )

            return {
                "error": "Billing information not found"
            }

        except Exception as e:

            span.record_exception(e)

            span.set_attribute(
                "lookup_status",
                "failed"
            )

            span.set_attribute(
                "error.message",
                str(e)
            )

            logger.exception(
                f"Error retrieving billing info. Policy={policy_number}, Customer={customer_id}"
            )

            raise

        finally:

            if conn:
                conn.close()

def get_payment_history(
    logger,
    policy_number: str
) -> List[Dict[str, Any]]:

    with tracer.start_as_current_span(
        "db_get_payment_history"
    ) as span:

        conn = None

        try:

            span.set_attribute(
                "db.system",
                "postgresql"
            )

            span.set_attribute(
                "db.operation",
                "SELECT"
            )

            span.set_attribute(
                "db.table",
                "payments"
            )

            span.set_attribute(
                "policy_number",
                policy_number
            )

            logger.info(
                f"🔍 Fetching payment history for policy: {policy_number}"
            )

            conn = enterprise_db.qmark_connection()

            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    p.payment_date,
                    p.amount,
                    p.status,
                    p.payment_method
                FROM payments p
                JOIN billing b
                    ON p.bill_id = b.bill_id
                WHERE b.policy_number = ?
                ORDER BY p.payment_date DESC
                LIMIT 10
                """,
                (policy_number,)
            )

            results = cursor.fetchall()

            if results:

                span.set_attribute(
                    "lookup_status",
                    "found"
                )

                span.set_attribute(
                    "records_found",
                    len(results)
                )

                logger.info(
                    f"✅ Found {len(results)} payment records"
                )

                columns = [
                    desc[0]
                    for desc in cursor.description
                ]

                response = [
                    dict(zip(columns, row))
                    for row in results
                ]

                return response

            span.set_attribute(
                "lookup_status",
                "not_found"
            )

            span.set_attribute(
                "records_found",
                0
            )

            logger.warning(
                "❌ No payment history found"
            )

            return []

        except Exception as e:

            span.record_exception(e)

            span.set_attribute(
                "lookup_status",
                "failed"
            )

            span.set_attribute(
                "error.message",
                str(e)
            )

            logger.exception(
                f"Error retrieving payment history for policy {policy_number}"
            )

            raise

        finally:

            if conn:
                conn.close()
def get_auto_policy_details(
    logger,
    policy_number: str
) -> Dict[str, Any]:

    with tracer.start_as_current_span(
        "db_get_auto_policy_details"
    ) as span:

        conn = None

        try:

            span.set_attribute(
                "db.system",
                "postgresql"
            )

            span.set_attribute(
                "db.name",
                "insureagent"
            )

            span.set_attribute(
                "db.operation",
                "SELECT"
            )

            span.set_attribute(
                "db.table",
                "auto_policy_details"
            )

            span.set_attribute(
                "policy_number",
                policy_number
            )

            logger.info(
                f"🔍 Fetching auto policy details for: {policy_number}"
            )

            conn = enterprise_db.qmark_connection()

            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    apd.*,
                    p.policy_type,
                    p.premium_amount
                FROM auto_policy_details apd
                JOIN policies p
                    ON apd.policy_number = p.policy_number
                WHERE apd.policy_number = ?
                """,
                (policy_number,)
            )

            result = cursor.fetchone()

            if result:

                span.set_attribute(
                    "lookup_status",
                    "found"
                )

                logger.info(
                    "✅ Auto policy details found"
                )

                columns = [
                    desc[0]
                    for desc in cursor.description
                ]

                response = dict(
                    zip(columns, result)
                )

                span.set_attribute(
                    "vehicle_make",
                    str(response.get("vehicle_make", ""))
                )

                span.set_attribute(
                    "vehicle_model",
                    str(response.get("vehicle_model", ""))
                )

                span.set_attribute(
                    "policy_type",
                    str(response.get("policy_type", ""))
                )

                return response

            span.set_attribute(
                "lookup_status",
                "not_found"
            )

            logger.warning(
                "❌ Auto policy details not found"
            )

            return {
                "error": "Auto policy details not found"
            }

        except Exception as e:

            span.record_exception(e)

            span.set_attribute(
                "lookup_status",
                "failed"
            )

            span.set_attribute(
                "error.message",
                str(e)
            )

            logger.exception(
                f"Error retrieving auto policy details for policy {policy_number}"
            )

            raise

        finally:

            if conn:
                conn.close()




def load_prompt(prompt_name):
    with open(
        f"prompts/{prompt_name}.yaml",
        "r",
        encoding="utf-8"
    ) as f:
        return yaml.safe_load(f)["prompt"]



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