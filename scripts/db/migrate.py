"""Postgres migration runner — the single owner of the app schema.

New machine:   python scripts/db/migrate.py      (creates the database too)
Schema change: add scripts/db/migrations/NNN_name.sql, re-run this script.

Files apply in filename order, each in its own transaction, and are recorded
in schema_migrations so they never run twice. Never edit an applied file —
add a new numbered one (that is what makes updates safe on every machine).
"""
from pathlib import Path
import sys

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import get_settings  # noqa: E402

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def ensure_database(dsn: str) -> None:
    """Create the target database if it doesn't exist (connects to 'postgres')."""
    base, _, dbname = dsn.rpartition("/")
    admin = psycopg2.connect(base + "/postgres")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
        if not cur.fetchone():
            cur.execute(f'CREATE DATABASE "{dbname}"')
            print(f"created database {dbname}")
    admin.close()


def apply_migrations(dsn: str) -> None:
    ensure_database(dsn)
    conn = psycopg2.connect(dsn)
    with conn, conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                   version    TEXT PRIMARY KEY,
                   applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
               )"""
        )
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.stem
        with conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (version,))
            if cur.fetchone():
                print(f"skip    {version} (already applied)")
                continue
            cur.execute(path.read_text(encoding="utf-8"))
            cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
            print(f"applied {version}")
    conn.close()


if __name__ == "__main__":
    apply_migrations(get_settings().app_db_url)
