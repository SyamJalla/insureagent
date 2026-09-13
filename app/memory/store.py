"""Memory persistence.

Postgres rows = source of truth. Chroma 'user_memory' collection = rebuildable
similarity index over EPISODIC items only. Every read/delete is scoped by
user_id in the query (tool-gateway enforcement style) — one user's memory can
never surface for another.
"""
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
import logging

import chromadb
import psycopg2
import psycopg2.extras

from app.config import get_settings
from app.memory.models import MemoryItem, MemoryKind

logger = logging.getLogger("insureagent.memory")

EPISODIC_TTL_DAYS = 180  # policy: docs/design/memory.md §1


class MemoryStore(ABC):
    @abstractmethod
    def add(self, item: MemoryItem) -> None: ...

    @abstractmethod
    def semantic_facts(self, user_id: str) -> list[MemoryItem]: ...

    @abstractmethod
    def similar_episodes(self, user_id: str, query: str, k: int = 3) -> list[MemoryItem]: ...

    @abstractmethod
    def list_for_user(self, user_id: str) -> list[MemoryItem]: ...

    @abstractmethod
    def delete(self, user_id: str, memory_id: str | None = None) -> int:
        """Hard delete one item (or ALL of the user's memory when id is None).
        Returns rows removed."""

    @abstractmethod
    def sweep_expired(self) -> int: ...


class ShortTermMemory(ABC):
    """Per-conversation working state. Postgres now; Redis is the swap-in."""

    @abstractmethod
    def get(self, conversation_id: str) -> dict: ...

    @abstractmethod
    def set(self, conversation_id: str, state: dict, ttl_s: int = 3600) -> None: ...


def _row_to_item(row) -> MemoryItem:
    return MemoryItem(
        memory_id=row["memory_id"], user_id=row["user_id"],
        kind=MemoryKind(row["kind"]), content=row["content"],
        intents=list(row["intents"] or []), actions=list(row["actions"] or []),
        source_conversation_id=row["source_conversation_id"],
        created_at=row["created_at"], expires_at=row["expires_at"],
    )


class PostgresChromaMemoryStore(MemoryStore):
    def __init__(self, dsn: str, vector_db_path: str):
        self._dsn = dsn
        self._vector_db_path = vector_db_path

    def _connect(self):
        return psycopg2.connect(self._dsn, cursor_factory=psycopg2.extras.RealDictCursor)

    @lru_cache(maxsize=1)
    def _collection(self):
        client = chromadb.PersistentClient(path=self._vector_db_path)
        return client.get_or_create_collection("user_memory")

    def add(self, item: MemoryItem) -> None:
        if item.kind == MemoryKind.EPISODIC and item.expires_at is None:
            item.expires_at = datetime.now(timezone.utc) + timedelta(days=EPISODIC_TTL_DAYS)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO memory_items
                   (memory_id, user_id, kind, content, intents, actions,
                    source_conversation_id, created_at, expires_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (item.memory_id, item.user_id, item.kind.value, item.content,
                 item.intents, item.actions, item.source_conversation_id,
                 item.created_at, item.expires_at),
            )
        if item.kind == MemoryKind.EPISODIC:
            try:
                self._collection().add(
                    ids=[item.memory_id],
                    documents=[item.content],
                    metadatas=[{"user_id": item.user_id}],
                )
            except Exception:
                logger.exception("episodic embedding failed (row kept; index rebuildable)")

    def semantic_facts(self, user_id: str) -> list[MemoryItem]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM memory_items WHERE user_id=%s AND kind='semantic'
                   ORDER BY created_at DESC LIMIT 10""",
                (user_id,),
            )
            return [_row_to_item(r) for r in cur.fetchall()]

    def similar_episodes(self, user_id: str, query: str, k: int = 3) -> list[MemoryItem]:
        try:
            res = self._collection().query(
                query_texts=[query], n_results=k,
                where={"user_id": user_id},  # scoping enforced HERE, from ctx
            )
            ids = res["ids"][0]
        except Exception:
            logger.exception("episodic retrieval failed — continuing without memory")
            return []
        if not ids:
            return []
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM memory_items
                   WHERE user_id=%s AND memory_id = ANY(%s)
                     AND (expires_at IS NULL OR expires_at > now())""",
                (user_id, ids),
            )
            rows = {r["memory_id"]: r for r in cur.fetchall()}
        return [_row_to_item(rows[i]) for i in ids if i in rows]

    def list_for_user(self, user_id: str) -> list[MemoryItem]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM memory_items WHERE user_id=%s ORDER BY created_at DESC",
                (user_id,),
            )
            return [_row_to_item(r) for r in cur.fetchall()]

    def delete(self, user_id: str, memory_id: str | None = None) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            if memory_id:
                cur.execute(
                    "DELETE FROM memory_items WHERE user_id=%s AND memory_id=%s RETURNING memory_id",
                    (user_id, memory_id),
                )
            else:
                cur.execute(
                    "DELETE FROM memory_items WHERE user_id=%s RETURNING memory_id", (user_id,)
                )
            removed = [r["memory_id"] for r in cur.fetchall()]
        if removed:
            try:
                self._collection().delete(ids=removed)
            except Exception:
                logger.exception("chroma delete failed for %d ids", len(removed))
        return len(removed)

    def sweep_expired(self) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM memory_items WHERE expires_at IS NOT NULL AND expires_at < now() "
                "RETURNING memory_id"
            )
            removed = [r["memory_id"] for r in cur.fetchall()]
        if removed:
            try:
                self._collection().delete(ids=removed)
            except Exception:
                logger.exception("chroma sweep delete failed")
        return len(removed)


class PostgresShortTermMemory(ShortTermMemory):
    def __init__(self, dsn: str):
        self._dsn = dsn

    def get(self, conversation_id: str) -> dict:
        with psycopg2.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT state FROM conversation_scratch WHERE conversation_id=%s AND expires_at > now()",
                (conversation_id,),
            )
            row = cur.fetchone()
        return row[0] if row else {}

    def set(self, conversation_id: str, state: dict, ttl_s: int = 3600) -> None:
        with psycopg2.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO conversation_scratch (conversation_id, state, expires_at)
                   VALUES (%s, %s, now() + %s * interval '1 second')
                   ON CONFLICT (conversation_id)
                   DO UPDATE SET state = EXCLUDED.state, expires_at = EXCLUDED.expires_at""",
                (conversation_id, json.dumps(state), ttl_s),
            )


@lru_cache
def get_memory_store() -> MemoryStore:
    s = get_settings()
    return PostgresChromaMemoryStore(s.app_db_url, str(s.vector_db_path))
