"""Conversation persistence.

Contract: every read is scoped by user_id — there is no way to fetch another
user's conversation through this interface. Postgres now; the ABC is the swap
point for DynamoDB later.
"""
from abc import ABC, abstractmethod

import psycopg2
import psycopg2.extras

from app.conversations.models import Conversation, Message


class ConversationStore(ABC):
    @abstractmethod
    def create(self, user_id: str) -> Conversation: ...

    @abstractmethod
    def get(self, conversation_id: str, user_id: str) -> Conversation | None: ...

    @abstractmethod
    def list_for_user(self, user_id: str) -> list[Conversation]: ...

    @abstractmethod
    def append_message(self, message: Message, user_id: str) -> None: ...

    @abstractmethod
    def get_messages(
        self, conversation_id: str, user_id: str, limit: int = 50
    ) -> list[Message]: ...


class PostgresConversationStore(ConversationStore):
    def __init__(self, dsn: str):
        # Schema is owned by scripts/db/migrate.py — run it on a new machine.
        self._dsn = dsn

    def _connect(self):
        return psycopg2.connect(self._dsn, cursor_factory=psycopg2.extras.RealDictCursor)

    def create(self, user_id: str) -> Conversation:
        conv = Conversation(user_id=user_id)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO conversations VALUES (%s,%s,%s,%s,%s)",
                (conv.conversation_id, conv.user_id, conv.title,
                 conv.created_at, conv.updated_at),
            )
        return conv

    def get(self, conversation_id: str, user_id: str) -> Conversation | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM conversations WHERE conversation_id=%s AND user_id=%s",
                (conversation_id, user_id),
            )
            row = cur.fetchone()
        return Conversation(**dict(row)) if row else None

    def list_for_user(self, user_id: str) -> list[Conversation]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM conversations WHERE user_id=%s ORDER BY updated_at DESC",
                (user_id,),
            )
            rows = cur.fetchall()
        return [Conversation(**dict(r)) for r in rows]

    def append_message(self, message: Message, user_id: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM conversations WHERE conversation_id=%s AND user_id=%s",
                (message.conversation_id, user_id),
            )
            if cur.fetchone() is None:
                raise KeyError("conversation not found for user")
            cur.execute(
                """INSERT INTO messages
                   (message_id, conversation_id, sender, content, escalated,
                    created_at, correlation_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (message.message_id, message.conversation_id, message.sender,
                 message.content, message.escalated, message.created_at,
                 message.correlation_id),
            )
            if message.sender == "user":
                cur.execute(
                    """UPDATE conversations SET title=%s, updated_at=now()
                       WHERE conversation_id=%s AND title='New conversation'""",
                    (message.content[:60], message.conversation_id),
                )
            cur.execute(
                "UPDATE conversations SET updated_at=now() WHERE conversation_id=%s",
                (message.conversation_id,),
            )

    def get_messages(
        self, conversation_id: str, user_id: str, limit: int = 50
    ) -> list[Message]:
        if self.get(conversation_id, user_id) is None:
            return []
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM messages WHERE conversation_id=%s
                   ORDER BY created_at DESC LIMIT %s""",
                (conversation_id, limit),
            )
            rows = cur.fetchall()
        return [Message(**dict(r)) for r in reversed(rows)]
