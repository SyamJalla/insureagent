"""Supervisor node: intent, routing proposal, complexity score, clarification.

The LLM proposes (next_agent/task/complexity JSON, or an ask_user call);
the orchestrator's routing function decides. No tool-gateway access here —
ask_user is a control-flow pseudo-tool, not a data tool.
"""
import json
import re

from langchain_core.runnables import RunnableConfig

from app.agents.base import load_prompt, render, _cfg
from app.llm.models import Complexity, LlmRequest

MAX_ITERATIONS = 3

_ASK_USER_SPEC = {
    "type": "function",
    "function": {
        "name": "ask_user",
        "description": "Ask the user ONE short clarification question when essential info is missing.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "missing_info": {"type": "string"},
            },
            "required": ["question"],
        },
    },
}

_VALID_AGENTS = {
    "policy_agent", "billing_agent", "claims_agent",
    "general_help_agent", "human_escalation_agent", "end",
}


def _parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {}


def supervisor_node(state: dict, config: RunnableConfig) -> dict:
    ctx, llm, _tools = _cfg(config)
    n = state.get("n_iteration", 0) + 1
    if n > MAX_ITERATIONS:
        return {
            "n_iteration": n,
            "requires_human_escalation": True,
            "escalation_reason": f"iteration limit ({MAX_ITERATIONS}) reached",
        }

    system = render(
        load_prompt("supervisor"),
        conversation_history=state.get("conversation_history", ""),
    )
    response = llm.complete(
        LlmRequest(
            agent="supervisor_agent",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": state.get("user_input", "")},
            ],
            tools=[_ASK_USER_SPEC],
        ),
        correlation_id=ctx.correlation_id,
    )

    for tc in response.tool_calls:
        if tc.name == "ask_user":
            question = tc.arguments.get("question", "Could you clarify your request?")
            return {
                "n_iteration": n,
                "clarification_question": question,
                "outcome": "clarification",
            }

    decision = _parse_json(response.content or "")
    next_agent = decision.get("next_agent", "general_help_agent")
    if next_agent not in _VALID_AGENTS:
        next_agent = "general_help_agent"
    try:
        complexity = Complexity(decision.get("complexity", "standard"))
    except ValueError:
        complexity = Complexity.STANDARD
    return {
        "n_iteration": n,
        "next_agent": next_agent,
        "task": decision.get("task", state.get("user_input", "")),
        "justification": decision.get("justification", ""),
        "complexity": complexity,
    }
