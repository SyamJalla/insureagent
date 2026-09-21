"""Reset all user activity — a clean conversation start for every user.

Deletes, for ALL users:
  * messages + conversations (chat history, incl. summarization watermarks)
  * conversation_scratch (short-term memory table)
  * long-term memory: memory_items rows AND their Chroma embeddings, via the
    memory store's own delete contract; then reconciles any orphaned
    embeddings left in the user_memory collection
  * Langfuse traces (when keys are configured and the server is reachable —
    otherwise skipped with a note; deletion is queued server-side, so traces
    may take a minute to disappear from the UI)

Deliberately KEPT: users/logins (demo personas stay valid), all enterprise
data (customers/policies/billing/claims), the FAQ vector collection.

Idempotent — safe to run any time. Run:  python scripts/reset_activity.py
"""
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402


def wipe_postgres_and_memory(dsn: str) -> None:
    from app.memory.store import get_memory_store

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()

    for table in ("messages", "conversations", "conversation_scratch", "memory_items"):
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"{table}: {cur.fetchone()[0]} rows before")

    # Memory first, through the store, so rows and embeddings go together.
    store = get_memory_store()
    cur.execute("SELECT user_id FROM users ORDER BY user_id")
    removed = 0
    for (user_id,) in cur.fetchall():
        removed += store.delete(user_id)
    print(f"memory: {removed} items removed (rows + embeddings)")

    # FK order: children before parents.
    for table in ("messages", "conversation_scratch", "conversations", "memory_items"):
        cur.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()

    # Reconcile: rows are truth and are now gone, so the index must be empty.
    try:
        import chromadb

        collection = chromadb.PersistentClient(
            path=str(get_settings().vector_db_path)
        ).get_or_create_collection("user_memory")
        orphans = collection.get()["ids"]
        if orphans:
            collection.delete(ids=orphans)
            print(f"chroma: removed {len(orphans)} orphaned embedding(s)")
        print(f"chroma user_memory: {collection.count()} embeddings after")
    except Exception as exc:
        print(f"chroma reconcile skipped ({type(exc).__name__}: {exc})")


def wipe_langfuse() -> None:
    s = get_settings()
    if not (s.langfuse_public_key and s.langfuse_secret_key):
        print("langfuse: no keys configured — skipped")
        return
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=s.langfuse_public_key,
            secret_key=s.langfuse_secret_key,
            host=s.langfuse_base_url or "http://localhost:3000",
        )
        if not client.auth_check():
            print("langfuse: auth check failed — skipped")
            return
        api = client.api

        # Collect ids first, then delete — deletes are processed async
        # server-side, so re-listing in a delete loop can spin.
        trace_ids: list[str] = []
        page = 1
        while True:
            batch = api.trace.list(page=page, limit=100)
            ids = [t.id for t in batch.data]
            if not ids:
                break
            trace_ids.extend(ids)
            page += 1
        for i in range(0, len(trace_ids), 100):
            api.trace.delete_multiple(trace_ids=trace_ids[i : i + 100])
        print(f"langfuse: deletion queued for {len(trace_ids)} trace(s)")
    except Exception as exc:
        print(f"langfuse: unreachable — skipped ({type(exc).__name__}: {exc})")


def main() -> None:
    dsn = get_settings().app_db_url
    wipe_postgres_and_memory(dsn)
    wipe_langfuse()
    print("done — every user starts with a clean slate (logins unchanged)")


if __name__ == "__main__":
    main()
