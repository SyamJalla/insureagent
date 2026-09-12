"""Connection helpers for the enterprise tables (customers, policies, claims, ...).

The single place database connections for enterprise data come from. Exists so
utils.py's tools stop hardcoding sqlite3 paths — NOT a repository layer. When
the tool gateway lands (delivery plan Epic 5), typed repositories with
RequestContext authorization replace direct SQL in tools, and this module is
absorbed into that layer.
"""
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator

import psycopg2
import psycopg2.extras

from app.config import get_settings


@contextmanager
def enterprise_connection() -> Iterator[psycopg2.extensions.connection]:
    """Yield a dict-row connection; commits on success, rolls back on error."""
    conn = psycopg2.connect(
        get_settings().app_db_url,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _jsonable(value: Any) -> Any:
    """Normalize DB types to what the SQLite-era tools produced (JSON-safe)."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def fetch_all(query: str, params: tuple = ()) -> list[dict[str, Any]]:
    with enterprise_connection() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        return [{k: _jsonable(v) for k, v in dict(r).items()} for r in cur.fetchall()]


def fetch_one(query: str, params: tuple = ()) -> dict[str, Any] | None:
    rows = fetch_all(query, params)
    return rows[0] if rows else None


# --- Temporary sqlite3-compatibility adapter for utils.py tools -------------
# The POC tools use the sqlite3 API shape (connect -> cursor -> execute with
# "?" placeholders -> description/fetchone/fetchall). This adapter preserves
# that shape over Postgres so the tools' SQL stays untouched until the tool
# gateway rewrite. Do not use in new code — use fetch_one/fetch_all above.


class _QmarkCursor:
    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql: str, params: tuple = ()):
        self._cur.execute(sql.replace("?", "%s"), params)
        return self

    def fetchone(self):
        row = self._cur.fetchone()
        return tuple(_jsonable(v) for v in row) if row is not None else None

    def fetchall(self):
        return [tuple(_jsonable(v) for v in row) for row in self._cur.fetchall()]

    @property
    def description(self):
        return self._cur.description

    def close(self) -> None:
        self._cur.close()


class QmarkConnection:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self) -> _QmarkCursor:
        return _QmarkCursor(self._conn.cursor())

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def qmark_connection() -> QmarkConnection:
    """sqlite3-style connection over Postgres (read paths in utils.py only)."""
    return QmarkConnection(psycopg2.connect(get_settings().app_db_url))
