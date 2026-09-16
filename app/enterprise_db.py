"""Connection helpers for the enterprise tables (customers, policies, claims, ...).

The single place database connections for enterprise data come from — NOT a
repository layer. Consumed by the tool layer (app/tools/*), where authorization
is enforced via RequestContext scoping in each tool's SQL.
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
    """Normalize DB types to JSON-safe primitives (Decimal→float, dates→ISO)."""
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
