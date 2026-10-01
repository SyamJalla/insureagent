"""Supervisor node: intent, routing proposal, complexity score, clarification.

The LLM proposes JSON; the orchestrator's routing function decides. The
supervisor has no tool-gateway access.
"""
import json
import logging
import re

from langchain_core.runnables import RunnableConfig

logger = logging.getLogger("insureagent.supervisor")

from app.agents.base import load_prompt, render, _cfg
from app.llm.models import Complexity, LlmRequest

MAX_ITERATIONS = 3

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
    logger.info("[%s] 🧭 supervisor | iteration=%d", ctx.correlation_id, n)

    tier3_agent = state.get("tier3_agent_override")
    if tier3_agent:
        return {
            "n_iteration": n,
            "next_agent": tier3_agent,
            "task": state.get("user_input", ""),
            "tier3_agent_override": None,
        }

    # 1. Execution Phase (Check for existing plan)
    plan = state.get("plan")
    if plan is not None:
        if len(plan) > 0:
            step = plan.pop(0)
            next_agent = step.get("next_agent", "end")
            logger.info("[%s] 🧭 plan pop → %s", ctx.correlation_id, next_agent)
            
            if next_agent == "respond":
                return {
                    "n_iteration": n,
                    "final_answer": step.get("response") or _FALLBACK_REPLY,
                    "outcome": "answer",
                    "plan": plan
                }
            
            try:
                complexity = Complexity(step.get("complexity", "standard"))
            except ValueError:
                complexity = Complexity.STANDARD
                
            return {
                "n_iteration": n,
                "next_agent": next_agent,
                "task": step.get("task", state.get("user_input", "")),
                "justification": step.get("justification", ""),
                "complexity": complexity,
                "plan": plan
            }
        else:
            logger.info("[%s] 🧭 plan empty → end", ctx.correlation_id)
            return {
                "n_iteration": n,
                "next_agent": "end",
                "plan": plan
            }

    if n > MAX_ITERATIONS:
        logger.warning(
            "[%s] 🧭 iteration cap (%d) hit → final answer with human offer",
            ctx.correlation_id, MAX_ITERATIONS,
        )
        # Loop exhaustion is NOT an escalation trigger: hand what we have to the
        # final answer node, which acknowledges the limit and OFFERS a human.
        # Real escalation stays reserved for flagged reasons (explicit request,
        # supervisor judgment).
        return {
            "n_iteration": n,
            "next_agent": "end",
            "collected_facts": [
                "[system note] Iteration limit reached. IMPORTANT: include ALL "
                "concrete facts already gathered above (amounts, dates, statuses) "
                "in your answer — do not discard them. Only the parts that were "
                "NOT resolved should be described as incomplete, with an offer to "
                "connect the user with a human specialist for those."
            ],
        }

    # Compose the supervisor's view: user-side history (single writer: the
    # runner) + this turn's agent findings (append-reducer, parallel-safe).
    history = state.get("conversation_history", "")
    facts = state.get("collected_facts") or []
    if facts:
        history += "\n[Agent findings this turn]\n" + "\n".join(facts)
    system = render(
        load_prompt("supervisor", tier=config["configurable"].get("tier", 0)),
        conversation_history=history,
    )
    # The supervisor communicates only through JSON. Mixing a pseudo-tool
    # with the JSON contract can make Groq models interpret "json" as a tool.
    response = llm.complete(
        LlmRequest(
            agent="supervisor_agent",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": state.get("user_input", "")},
            ],
            tools=None,
        ),
        correlation_id=ctx.correlation_id,
    )

    decision = _parse_json(response.content or "")

    # Contract violation (no JSON): never guess a route. If the model replied
    # in conversational prose, that prose IS the reply; otherwise a safe fallback.
    if not decision:
        prose = (response.content or "").strip()
        logger.warning(
            "[%s] 🧭 decision=no-JSON fallback → direct reply (%s)",
            ctx.correlation_id, "prose" if prose else "canned",
        )
        return {
            "n_iteration": n,
            "final_answer": prose or _FALLBACK_REPLY,
            "outcome": "answer",
        }

    question = decision.get("clarification_question")
    if question and not facts:
        logger.info("[%s] 🧭 decision=clarify | question=%r", ctx.correlation_id, question[:100])
        return {
            "n_iteration": n,
            "clarification_question": question,
            "outcome": "clarification",
        }

    new_plan = decision.get("plan", [])
    
    # Backward compatibility if model still returns old schema
    if not new_plan and "next_agent" in decision:
        new_plan = [decision]

    if not new_plan:
        logger.warning(
            "[%s] 🧭 decision=empty plan → canned fallback", ctx.correlation_id
        )
        return {
            "n_iteration": n,
            "final_answer": _FALLBACK_REPLY,
            "outcome": "answer",
        }

    step = new_plan.pop(0)
    next_agent = step.get("next_agent", "")
    
    if next_agent not in _VALID_AGENTS:
        logger.warning(
            "[%s] 🧭 decision=invalid agent %r → canned fallback", ctx.correlation_id, next_agent
        )
        return {
            "n_iteration": n,
            "final_answer": _FALLBACK_REPLY,
            "outcome": "answer",
            "plan": new_plan
        }

    # Direct response: small talk, capability questions, out-of-scope. The
    # supervisor is the answer; no specialist, no tools, straight to END.
    if next_agent == "respond":
        logger.info("[%s] 🧭 decision=respond (direct, no specialist)", ctx.correlation_id)
        return {
            "n_iteration": n,
            "final_answer": step.get("response") or _FALLBACK_REPLY,
            "outcome": "answer",
            "plan": new_plan
        }

    try:
        complexity = Complexity(step.get("complexity", "standard"))
    except ValueError:
        complexity = Complexity.STANDARD
    logger.info(
        "[%s] 🧭 decision=route → %s | complexity=%s | task=%r | why=%r",
        ctx.correlation_id, next_agent, complexity.value,
        step.get("task", "")[:90], step.get("justification", "")[:90],
    )
    return {
        "n_iteration": n,
        "next_agent": next_agent,
        "task": step.get("task", state.get("user_input", "")),
        "justification": step.get("justification", ""),
        "complexity": complexity,
        "plan": new_plan
    }
