"""AgentRunner — bridges the conversation service and the agent graph.

Builds per-request state + config (RequestContext and both gateways travel in
LangGraph's config channel, never in LLM-visible state), invokes the graph,
maps the outcome. utils.py is no longer imported anywhere.
"""
from functools import lru_cache
import logging
import time

from pydantic import BaseModel

logger = logging.getLogger("insureagent.runner")

from app.agents.orchestrator import build_graph
from app.auth.models import RequestContext
from app.conversations.models import Message
from app.llm.gateway import build_default_gateway
from app.tools.gateway import ToolGateway


class AgentResult(BaseModel):
    answer: str
    escalated: bool


@lru_cache
def _graph():
    return build_graph()


@lru_cache
def _gateways():
    return build_default_gateway(), ToolGateway()


def _render_history(ctx: RequestContext, history: list[Message], user_input: str) -> str:
    lines = [
        f"[Verified session context — role: {ctx.user.role.value}"
        + (f", customer_id: {ctx.user.customer_id}" if ctx.user.customer_id else "")
        + (
            f", owned policies: {', '.join(ctx.owned_policy_numbers)}"
            if ctx.owned_policy_numbers
            else ""
        )
        + "]"
    ]
    for m in history:
        speaker = "User" if m.sender == "user" else "Assistant"
        lines.append(f"{speaker}: {m.content}")
    lines.append(f"User: {user_input}")
    return "\n".join(lines)


class AgentRunner:
    def run(self, ctx: RequestContext, history: list[Message], user_input: str) -> AgentResult:
        started = time.monotonic()
        logger.info(
            "[%s] ▶ request start | user=%s role=%s | input=%r",
            ctx.correlation_id, ctx.user.user_id, ctx.user.role.value, user_input[:120],
        )
        llm, tools = _gateways()
        state = {
            "user_input": user_input,
            "conversation_history": _render_history(ctx, history, user_input),
            "n_iteration": 0,
            "collected_facts": [],
            "requires_human_escalation": False,
            "outcome": "",
        }
        final = _graph().invoke(
            state,
            config={"configurable": {"ctx": ctx, "llm": llm, "tools": tools}},
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if final.get("outcome") == "clarification":
            logger.info(
                "[%s] ◀ request end | outcome=clarification | %dms | question=%r",
                ctx.correlation_id, elapsed_ms, final["clarification_question"][:100],
            )
            return AgentResult(answer=final["clarification_question"], escalated=False)
        result = AgentResult(
            answer=final.get("final_answer") or "Sorry, I could not generate a response.",
            escalated=bool(final.get("requires_human_escalation")),
        )
        logger.info(
            "[%s] ◀ request end | outcome=%s | iterations=%d | %dms | answer=%r",
            ctx.correlation_id, final.get("outcome") or "answer",
            final.get("n_iteration", 0), elapsed_ms, result.answer[:100],
        )
        return result
