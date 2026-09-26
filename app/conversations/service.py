"""ConversationService — orchestrates store + agent runner. No HTTP, no SQL."""
import logging

from app.agents.runner import AgentRunner
from app.auth.models import RequestContext
from app.config import get_settings
from app.conversations.models import Conversation, Message
from app.conversations.store import ConversationStore


class ConversationNotFound(Exception):
    pass


class ConversationService:
    def __init__(self, store: ConversationStore, runner: AgentRunner):
        self._store = store
        self._runner = runner

    def start(self, ctx: RequestContext) -> Conversation:
        conversation = self._store.create(ctx.user.user_id)
        ctx.conversation_id = conversation.conversation_id
        self._ensure_trace_context(ctx, conversation.conversation_id)
        return conversation

    def list_for_user(self, ctx: RequestContext) -> list[Conversation]:
        return self._store.list_for_user(ctx.user.user_id)

    def history(self, ctx: RequestContext, conversation_id: str) -> list[Message]:
        if self._store.get(conversation_id, ctx.user.user_id) is None:
            raise ConversationNotFound(conversation_id)
        return self._store.get_messages(conversation_id, ctx.user.user_id)

    def send_message(self, ctx: RequestContext, conversation_id: str, content: str) -> Message:
        if self._store.get(conversation_id, ctx.user.user_id) is None:
            raise ConversationNotFound(conversation_id)
        ctx.conversation_id = conversation_id  # completes the ID hierarchy for tracing
        trace_context = self._ensure_trace_context(ctx, conversation_id)
        limit = get_settings().history_message_limit
        history = self._store.get_messages(conversation_id, ctx.user.user_id, limit=limit)

        from app.tracing import get_tracer

        tracer = get_tracer()
        # Start before guardrails so their observations share the turn root.
        # The root input is set only after redaction, keeping raw PII out of traces.
        trace_id, parent_span_id = trace_context or (None, None)
        with tracer.request_trace(
            ctx, trace_id=trace_id, parent_span_id=parent_span_id
        ) as trace:
            guard = None
            if get_settings().guardrail_mode != "off":
                from app.guardrails.pipeline import get_guardrail_pipeline

                guard = get_guardrail_pipeline().run_input(content, ctx)
                content = guard.text
            tracer.update_request_input(trace, content)

            user_msg = Message(conversation_id=conversation_id, sender="user", content=content)
            self._store.append_message(user_msg, ctx.user.user_id)

            if guard is not None and guard.action in ("block", "escalate"):
                # Terminal verdict: canned in-chat reply; the agent graph and the
                # memory summarizer never see this turn.
                reply = Message(
                    conversation_id=conversation_id,
                    sender="assistant",
                    content=guard.user_reply
                    or "I can't continue with that message — can I help with an insurance question?",
                    escalated=(guard.action == "escalate"),
                    correlation_id=ctx.correlation_id,
                    langfuse_trace_id=getattr(trace, "trace_id", None),
                    langfuse_observation_id=getattr(trace, "id", None),
                )
                tracer.finish_request(guard.action, reply.content[:500])
                self._store.append_message(reply, ctx.user.user_id)
                return reply

            result = self._runner.run(ctx, history, content)

            reply = Message(
                conversation_id=conversation_id,
                sender="assistant",
                content=result.answer,
                escalated=result.escalated,
                correlation_id=ctx.correlation_id,
                langfuse_trace_id=getattr(trace, "trace_id", None),
                langfuse_observation_id=getattr(trace, "id", None),
            )
            self._store.append_message(reply, ctx.user.user_id)
            self._summarize(ctx, conversation_id)
            return reply

    def _ensure_trace_context(
        self, ctx: RequestContext, conversation_id: str
    ) -> tuple[str, str] | None:
        from app.tracing import get_tracer

        tracer = get_tracer()
        if not tracer.enabled:
            return None
        return self._store.ensure_trace_context(
            conversation_id,
            ctx.user.user_id,
            lambda: tracer.create_conversation_trace(ctx, conversation_id),
        )

    def _summarize(self, ctx: RequestContext, conversation_id: str) -> None:
        """Memory write path — never breaks the chat (guarded inside)."""
        from app.agents.runner import _gateways
        from app.memory.store import get_memory_store
        from app.memory.summarizer import Summarizer

        llm, _tools = _gateways()
        messages = self._store.get_messages(conversation_id, ctx.user.user_id, limit=50)
        Summarizer(get_memory_store(), llm).maybe_summarize(ctx, conversation_id, messages)

    def record_feedback(
        self, ctx: RequestContext, conversation_id: str, message_id: str,
        rating: str, comment: str | None = None,
    ) -> None:
        """Attach user feedback to the message's Langfuse trace (via its
        correlation_id). Ownership enforced by the store read."""
        messages = self._store.get_messages(conversation_id, ctx.user.user_id, limit=200)
        target = next((m for m in messages if m.message_id == message_id), None)
        if target is None:
            raise ConversationNotFound(conversation_id)
        logging.getLogger("insureagent.feedback").info(
            "👍👎 feedback | user=%s rating=%s message=%s corr=%s",
            ctx.user.user_id, rating, message_id, target.correlation_id,
        )
        if target.langfuse_trace_id or target.correlation_id:
            from app.tracing import get_tracer

            tracer = get_tracer()
            trace_id = target.langfuse_trace_id or tracer.legacy_request_trace_id(
                target.correlation_id
            )
            if trace_id:
                tracer.score(
                    trace_id, "user_feedback",
                    1.0 if rating == "up" else 0.0,
                    comment,
                    idempotency_key=message_id,  # repeat clicks overwrite, never stack
                    observation_id=target.langfuse_observation_id,
                )
