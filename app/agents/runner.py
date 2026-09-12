"""AgentRunner — bridges the conversation service and the agent graph.

Builds per-request state + config (RequestContext and both gateways travel in
LangGraph's config channel, never in LLM-visible state), invokes the graph,
maps the outcome. utils.py is no longer imported anywhere.
"""
from functools import lru_cache

from pydantic import BaseModel

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
        if final.get("outcome") == "clarification":
            return AgentResult(answer=final["clarification_question"], escalated=False)
        return AgentResult(
            answer=final.get("final_answer") or "Sorry, I could not generate a response.",
            escalated=bool(final.get("requires_human_escalation")),
        )
