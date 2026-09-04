"""ConversationService — orchestrates store + agent runner. No HTTP, no SQL."""
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
        return self._store.create(ctx.user.user_id)

    def list_for_user(self, ctx: RequestContext) -> list[Conversation]:
        return self._store.list_for_user(ctx.user.user_id)

    def history(self, ctx: RequestContext, conversation_id: str) -> list[Message]:
        if self._store.get(conversation_id, ctx.user.user_id) is None:
            raise ConversationNotFound(conversation_id)
        return self._store.get_messages(conversation_id, ctx.user.user_id)

    def send_message(self, ctx: RequestContext, conversation_id: str, content: str) -> Message:
        if self._store.get(conversation_id, ctx.user.user_id) is None:
            raise ConversationNotFound(conversation_id)
        limit = get_settings().history_message_limit
        history = self._store.get_messages(conversation_id, ctx.user.user_id, limit=limit)

        user_msg = Message(conversation_id=conversation_id, sender="user", content=content)
        self._store.append_message(user_msg, ctx.user.user_id)

        result = self._runner.run(ctx, history, content)

        reply = Message(
            conversation_id=conversation_id,
            sender="assistant",
            content=result.answer,
            escalated=result.escalated,
        )
        self._store.append_message(reply, ctx.user.user_id)
        return reply
