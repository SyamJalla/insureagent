"""One-time migration: copy app-owned data (users, conversations, messages)
from the SQLite file into Postgres. Idempotent — existing rows are skipped.

The insurance tables (customers/policies/claims/...) stay in SQLite: the agent
tools in utils.py read them there until the tool layer migrates business data.

Run:  python scripts/migrate_app_to_postgres.py
"""
from datetime import datetime, timezone
import sqlite3
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

sys.path.insert(0, str(Path(__file__).resolve().parent / "db"))
from migrate import apply_migrations  # noqa: E402

from app.config import get_settings  # noqa: E402


def _ts(value) -> datetime:
    if isinstance(value, datetime):
        return value
    dt = datetime.fromisoformat(str(value))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def main() -> None:
    s = get_settings()
    apply_migrations(s.app_db_url)

    src = sqlite3.connect(s.db_path)
    src.row_factory = sqlite3.Row
    dst = psycopg2.connect(s.app_db_url)
    cur = dst.cursor()

    copied = {}
    users = src.execute("SELECT * FROM users").fetchall()
    for r in users:
        cur.execute(
            """INSERT INTO users (user_id, email, password_hash, display_name,
                                  role, customer_id, agent_id, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (user_id) DO NOTHING""",
            (r["user_id"], r["email"], r["password_hash"], r["display_name"],
             r["role"], r["customer_id"], r["agent_id"], _ts(r["created_at"])),
        )
    copied["users"] = len(users)

    convs = src.execute("SELECT * FROM conversations").fetchall()
    for r in convs:
        cur.execute(
            """INSERT INTO conversations VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (conversation_id) DO NOTHING""",
            (r["conversation_id"], r["user_id"], r["title"],
             _ts(r["created_at"]), _ts(r["updated_at"])),
        )
    copied["conversations"] = len(convs)

    msgs = src.execute("SELECT * FROM messages").fetchall()
    for r in msgs:
        cur.execute(
            """INSERT INTO messages VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (message_id) DO NOTHING""",
            (r["message_id"], r["conversation_id"], r["sender"], r["content"],
             bool(r["escalated"]), _ts(r["created_at"])),
        )
    copied["messages"] = len(msgs)

    dst.commit()
    for table, n in copied.items():
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"{table}: {n} in SQLite -> {cur.fetchone()[0]} now in Postgres")
    src.close()
    dst.close()


if __name__ == "__main__":
    main()
