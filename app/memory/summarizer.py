"""Write path: summarize a conversation into episodic + semantic memory.

Triggered after a reply when a conversation has accumulated N new messages
since its last summary. One FAST-tier LLM call. Never breaks the chat —
failures are logged and skipped.
"""
import json
import logging
import re

import psycopg2

from app.agents.base import load_prompt
from app.config import get_settings
from app.conversations.models import Message
from app.llm.models import LlmRequest
from app.memory.models import MemoryItem, MemoryKind
from app.memory.store import MemoryStore

logger = logging.getLogger("insureagent.memory")

SUMMARIZE_EVERY_N_MESSAGES = 4
MAX_TRANSCRIPT_MESSAGES = 12
MAX_FACTS = 2


def _parse(content: str) -> dict:
    m = re.search(r"\{.*\}", content or "", re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return {}


class Summarizer:
    def __init__(self, memory: MemoryStore, llm):
        self._memory = memory
        self._llm = llm

    def maybe_summarize(self, ctx, conversation_id: str, messages: list[Message]) -> None:
        """Call after appending a reply. Cheap check first, LLM only when due."""
        try:
            self._maybe_summarize(ctx, conversation_id, messages)
        except Exception:
            logger.exception("[%s] summarization failed — chat unaffected", ctx.correlation_id)

    def _maybe_summarize(self, ctx, conversation_id: str, messages: list[Message]) -> None:
        dsn = get_settings().app_db_url
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT (SELECT COUNT(*) FROM messages WHERE conversation_id=%s),
                          summarized_message_count
                   FROM conversations WHERE conversation_id=%s""",
                (conversation_id, conversation_id),
            )
            total, done = cur.fetchone()
        if total - done < SUMMARIZE_EVERY_N_MESSAGES:
            return

        transcript = "\n".join(
            f"{'User' if m.sender == 'user' else 'Assistant'}: {m.content}"
            for m in messages[-MAX_TRANSCRIPT_MESSAGES:]
        )
        response = self._llm.complete(
            LlmRequest(
                agent="memory_summarizer",
                messages=[
                    {"role": "system", "content": load_prompt("memory_summarizer")},
                    {"role": "user", "content": transcript},
                ],
            ),
            correlation_id=ctx.correlation_id,
        )
        data = _parse(response.content or "")
        if not data.get("summary"):
            logger.warning("[%s] summarizer returned no summary — skipped", ctx.correlation_id)
            return

        self._memory.add(MemoryItem(
            user_id=ctx.user.user_id,
            kind=MemoryKind.EPISODIC,
            content=data["summary"],
            intents=[str(i)[:80] for i in data.get("intents", [])][:5],
            actions=[str(a)[:120] for a in data.get("actions", [])][:5],
            source_conversation_id=conversation_id,
        ))
        existing = {f.content for f in self._memory.semantic_facts(ctx.user.user_id)}
        for fact in [str(f) for f in data.get("facts", [])][:MAX_FACTS]:
            if fact and fact not in existing:
                self._memory.add(MemoryItem(
                    user_id=ctx.user.user_id,
                    kind=MemoryKind.SEMANTIC,
                    content=fact,
                    source_conversation_id=conversation_id,
                ))

        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE conversations SET summarized_message_count=%s WHERE conversation_id=%s",
                (total, conversation_id),
            )
        logger.info(
            "[%s] 🧠 memory written | episodic=1 facts<=%d | conv=%s",
            ctx.correlation_id, MAX_FACTS, conversation_id[:8],
        )
