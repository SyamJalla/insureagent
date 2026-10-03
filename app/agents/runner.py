"""AgentRunner — bridges the conversation service and the agent graph.

Builds per-request state + config (RequestContext and both gateways travel in
LangGraph's config channel, never in LLM-visible state), invokes the graph,
maps the outcome.
"""
from functools import lru_cache
import logging
import time

from pydantic import BaseModel

logger = logging.getLogger("insureagent.runner")

from app.agents.orchestrator import build_graph
from app.auth.models import RequestContext
from app.conversations.models import Message
from app.llm.gateway import build_gateway_for_tier
from app.llm.tier_router import TierRouter
from app.tools.gateway import ToolGateway
from app.tracing import get_tracer


class AgentResult(BaseModel):
    answer: str
    escalated: bool


@lru_cache
def _graph():
    return build_graph()


@lru_cache
def _gateways(tier: int = 1):
    """Return the selected LLM gateway and shared tool gateway."""
    return build_gateway_for_tier(tier), _tool_gateway()


@lru_cache
def _tool_gateway():
    return ToolGateway()


@lru_cache
def _tier_router(tier: int = 3):
    return TierRouter(tier=tier)


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
    def run(
        self, ctx: RequestContext, history: list[Message], user_input: str, tier: int = 1
    ) -> AgentResult:
        result, _ = self.run_detailed(ctx, history, user_input, tier=tier)
        return result

    def run_detailed(
        self, ctx: RequestContext, history: list[Message], user_input: str, tier: int = 1
    ) -> tuple[AgentResult, dict]:
        """run() plus the final graph state — used by the eval harness to
        inspect which agents ran (collected_facts prefixes) and outcomes."""
        started = time.monotonic()
        logger.info(
            "[%s] ▶ request start | user=%s role=%s | input=%r",
            ctx.correlation_id, ctx.user.user_id, ctx.user.role.value, user_input[:120],
        )
        tracer = get_tracer()
        try:
            tier3_agent_override = None
            model_override = None
            if tier == 3:
                tier3_agent_override, model_override = _tier_router(tier=3).resolve(user_input)
            llm = build_gateway_for_tier(tier, model_override=model_override)
            tools = _tool_gateway()
            with tracer.request_trace(ctx, user_input):
                conversation_history = _render_history(ctx, history, user_input)
                from app.config import get_settings
                if get_settings().memory_enabled:
                    from app.memory.retriever import memory_block
                    from app.memory.store import get_memory_store

                    with tracer.observation(
                        "memory_retrieval", input={"query": user_input}
                    ) as memory_span:
                        block = memory_block(get_memory_store(), ctx, user_input)
                        if block and memory_span:
                            memory_span.update(output={"context": block})
                else:
                    block = ""
                if block:
                    conversation_history = block + "\n" + conversation_history
                state = {
                    "user_input": user_input,
                    "conversation_history": conversation_history,
                    "n_iteration": 0,
                    "collected_facts": [],
                    "requires_human_escalation": False,
                    "outcome": "",
                    "tier3_agent_override": tier3_agent_override,
                }
                with tracer.observation(
                    "agent_graph",
                    input={"user_input": user_input, "history_count": len(history)},
                    metadata={"graph": "supervisor_specialist_loop"},
                ) as graph_span:
                    final = _graph().invoke(
                        state,
                        config={"configurable": {
                            "ctx": ctx, "llm": llm, "tools": tools, "tier": tier,
                        }},
                    )
                    if graph_span:
                        graph_span.update(
                            output={
                                "outcome": final.get("outcome"),
                                "iterations": final.get("n_iteration", 0),
                                "collected_fact_count": len(final.get("collected_facts", [])),
                            }
                        )
                tracer.finish_request(
                    final.get("outcome") or "answer",
                    (final.get("final_answer") or final.get("clarification_question") or "")[:500],
                )
        except Exception:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.exception(
                "[%s] ✖ request FAILED after %dms — returning graceful error",
                ctx.correlation_id, elapsed_ms,
            )
            error_answer = (
                "Sorry — something went wrong on our side while handling that. "
                "Please try again, or ask to speak with a person."
            )
            tracer.finish_request("error", error_answer[:500])
            return AgentResult(
                answer=error_answer,
                escalated=False,
            ), {"outcome": "error"}
        finally:
            tracer.flush()
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if final.get("outcome") == "clarification":
            logger.info(
                "[%s] ◀ request end | outcome=clarification | %dms | question=%r",
                ctx.correlation_id, elapsed_ms, final["clarification_question"][:100],
            )
            return AgentResult(answer=final["clarification_question"], escalated=False), final
        result = AgentResult(
            answer=final.get("final_answer") or "Sorry, I could not generate a response.",
            escalated=bool(final.get("requires_human_escalation")),
        )
        logger.info(
            "[%s] ◀ request end | outcome=%s | iterations=%d | %dms | answer=%r",
            ctx.correlation_id, final.get("outcome") or "answer",
            final.get("n_iteration", 0), elapsed_ms, result.answer[:100],
        )
        return result, final
