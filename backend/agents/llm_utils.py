import os
import json
import yaml
from functools import wraps
from openai import OpenAI
from langfuse import observe           # langfuse v4+: observe moved to top-level package
from core.config import tracer, logger_name
import logging

# Resolve prompts/ relative to backend/ regardless of CWD
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def create_tools():
    return []
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



def ask_user(logger,question: str, missing_info: str = ""):
    """Ask the user for input and return the response."""
    logger.info(f"🗣️ Asking user for input: {question}")
    if missing_info:
        print(f"---USER INPUT REQUIRED---\nMissing information: {missing_info}")
    else:
        print(f"---USER INPUT REQUIRED---")

    answer = input(f"{question}: ")
    return {"context": answer, "source": "User Input"}

def load_prompt(prompt_name):
    with open(
        os.path.join(_BACKEND_DIR, 'prompts', f'{prompt_name}.yaml'),
        "r",
        encoding="utf-8"
    ) as f:
        return yaml.safe_load(f)["prompt"]



