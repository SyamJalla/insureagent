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
    "general_help_agent", "human_escalation_agent", "end", "respond",
}

_FALLBACK_REPLY = (
    "I can help with your policies, billing, and claims, or answer general "
    "insurance questions. What would you like to know?"
)


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
        # Loop exhaustion is NOT an escalation trigger: hand what we have to the
        # final answer node, which acknowledges the limit and OFFERS a human.
        # Real escalation stays reserved for flagged reasons (explicit request,
        # supervisor judgment).
        return {
            "n_iteration": n,
            "next_agent": "end",
            "collected_facts": [
                "[system note] Iteration limit reached before the request was fully "
                "resolved. Answer with what is known, acknowledge the limitation, "
                "and offer to connect the user with a human specialist."
            ],
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

    # Contract violation (no JSON): never guess a route. If the model replied
    # in conversational prose, that prose IS the reply; otherwise a safe fallback.
    if not decision:
        prose = (response.content or "").strip()
        return {
            "n_iteration": n,
            "final_answer": prose or _FALLBACK_REPLY,
            "outcome": "answer",
        }

    next_agent = decision.get("next_agent", "")
    if next_agent not in _VALID_AGENTS:
        return {
            "n_iteration": n,
            "final_answer": _FALLBACK_REPLY,
            "outcome": "answer",
        }

    # Direct response: small talk, capability questions, out-of-scope. The
    # supervisor is the answer; no specialist, no tools, straight to END.
    if next_agent == "respond":
        return {
            "n_iteration": n,
            "final_answer": decision.get("response") or _FALLBACK_REPLY,
            "outcome": "answer",
        }

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
