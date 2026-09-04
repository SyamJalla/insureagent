"""Conversation persistence.

Contract: every read is scoped by user_id — there is no way to fetch another
user's conversation through this interface. SQLite now; the ABC is the swap
point for Postgres/DynamoDB later.
"""
from abc import ABC, abstractmethod
from pathlib import Path
import sqlite3

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


class SqliteConversationStore(ConversationStore):
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS conversations (
                       conversation_id TEXT PRIMARY KEY,
                       user_id         TEXT NOT NULL,
                       title           TEXT NOT NULL,
                       created_at      TEXT NOT NULL,
                       updated_at      TEXT NOT NULL
                   )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS messages (
                       message_id      TEXT PRIMARY KEY,
                       conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
                       sender          TEXT NOT NULL CHECK (sender IN ('user','assistant')),
                       content         TEXT NOT NULL,
                       escalated       INTEGER NOT NULL DEFAULT 0,
                       created_at      TEXT NOT NULL
                   )"""
            )

    def create(self, user_id: str) -> Conversation:
        conv = Conversation(user_id=user_id)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations VALUES (?,?,?,?,?)",
                (
                    conv.conversation_id,
                    conv.user_id,
                    conv.title,
                    conv.created_at.isoformat(),
                    conv.updated_at.isoformat(),
                ),
            )
        return conv

    def get(self, conversation_id: str, user_id: str) -> Conversation | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE conversation_id=? AND user_id=?",
                (conversation_id, user_id),
            ).fetchone()
        return Conversation(**dict(row)) if row else None

    def list_for_user(self, user_id: str) -> list[Conversation]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM conversations WHERE user_id=? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        return [Conversation(**dict(r)) for r in rows]

    def append_message(self, message: Message, user_id: str) -> None:
        with self._connect() as conn:
            owner = conn.execute(
                "SELECT 1 FROM conversations WHERE conversation_id=? AND user_id=?",
                (message.conversation_id, user_id),
            ).fetchone()
            if owner is None:
                raise KeyError("conversation not found for user")
            conn.execute(
                "INSERT INTO messages VALUES (?,?,?,?,?,?)",
                (
                    message.message_id,
                    message.conversation_id,
                    message.sender,
                    message.content,
                    int(message.escalated),
                    message.created_at.isoformat(),
                ),
            )
            title_update = (
                (message.content[:60], message.conversation_id)
                if message.sender == "user"
                else None
            )
            if title_update:
                conn.execute(
                    """UPDATE conversations SET title=?, updated_at=datetime('now')
                       WHERE conversation_id=? AND title='New conversation'""",
                    title_update,
                )
            conn.execute(
                "UPDATE conversations SET updated_at=datetime('now') WHERE conversation_id=?",
                (message.conversation_id,),
            )

    def get_messages(
        self, conversation_id: str, user_id: str, limit: int = 50
    ) -> list[Message]:
        if self.get(conversation_id, user_id) is None:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM messages WHERE conversation_id=?
                   ORDER BY created_at DESC LIMIT ?""",
                (conversation_id, limit),
            ).fetchall()
        return [Message(**{**dict(r), "escalated": bool(r["escalated"])}) for r in reversed(rows)]
