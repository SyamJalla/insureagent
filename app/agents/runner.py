"""AgentRunner — the ONLY module that imports utils.py.

Wraps the existing LangGraph workflow. When the utils.py refactor lands
(agents/ package split), this file is the single place that changes.
"""
from functools import lru_cache

from pydantic import BaseModel

import utils
from app.auth.models import RequestContext
from app.config import get_settings
from app.conversations.models import Message


class AgentResult(BaseModel):
    answer: str
    escalated: bool


class _ClarificationNeeded(Exception):
    """Raised in place of utils.ask_user's console input() prompt."""

    def __init__(self, question: str):
        super().__init__(question)
        self.question = question


def _ask_user_via_chat(logger, question: str, missing_info: str = ""):
    # utils.ask_user blocks on console input(), which cannot work behind an HTTP
    # API. In chat, a clarification question IS the assistant's reply: raise it
    # out of the graph and return it as the message; the user's answer arrives
    # as their next message, carried back in via conversation_history.
    # Refactor note (utils.py split): make clarification a first-class graph
    # outcome instead of this patch.
    raise _ClarificationNeeded(question)


utils.ask_user = _ask_user_via_chat


@lru_cache
def _build_workflow():
    """Build the compiled graph once per process (LLM client, vector DB, tracing)."""
    settings = get_settings()
    logger = utils.create_logger("insurance_agent.log")
    langfuse = utils.create_langfuse()
    client = utils.create_client(settings.openai_api_key)
    chroma_client = utils.create_chroma_client(str(settings.vector_db_path))
    collection = chroma_client.get_collection(name=settings.faq_collection_name)
    app = utils.run_workflow(
        client=client, logger=logger, langfuse=langfuse, collection=collection
    )
    return app, langfuse


def _render_history(ctx: RequestContext, history: list[Message], user_input: str) -> str:
    """Conversation history + identity context, as the prompt text the graph expects."""
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
        app, langfuse = _build_workflow()
        initial_state = {
            "n_iteration": 0,
            "messages": [],
            "user_input": user_input,
            "user_intent": "",
            "customer_id": ctx.user.customer_id or "",
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
            "conversation_history": _render_history(ctx, history, user_input),
            "task": "Help user with their query",
            "final_answer": "",
        }
        try:
            final_state = app.invoke(initial_state)
        except _ClarificationNeeded as need:
            return AgentResult(answer=need.question, escalated=False)
        finally:
            langfuse.flush()
        return AgentResult(
            answer=final_state.get("final_answer") or "Sorry, I could not generate a response.",
            escalated=bool(final_state.get("requires_human_escalation")),
        )
