"""User persistence. The only module that reads the users table.

Identity and policy ownership both live in Postgres (since migration 002).
"""
from abc import ABC, abstractmethod

import psycopg2
import psycopg2.extras

from app.auth.models import Role, User


class UserStore(ABC):
    @abstractmethod
    def get_by_email(self, email: str) -> tuple[User, str] | None:
        """Return (user, password_hash) or None."""

    @abstractmethod
    def get_by_id(self, user_id: str) -> User | None: ...

    @abstractmethod
    def policy_numbers_for_customer(self, customer_id: str) -> list[str]: ...


def _to_user(row) -> User:
    return User(
        user_id=row["user_id"],
        email=row["email"],
        display_name=row["display_name"],
        role=Role(row["role"]),
        customer_id=row["customer_id"],
        agent_id=row["agent_id"],
    )


class PostgresUserStore(UserStore):
    """Identity and policy directory, both in Postgres (since migration 002)."""

    def __init__(self, dsn: str):
        # Schema is owned by scripts/db/migrate.py — run it on a new machine.
        self._dsn = dsn

    def _connect(self):
        return psycopg2.connect(self._dsn, cursor_factory=psycopg2.extras.RealDictCursor)

    def get_by_email(self, email: str) -> tuple[User, str] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
        return (_to_user(row), row["password_hash"]) if row else None

    def get_by_id(self, user_id: str) -> User | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
        return _to_user(row) if row else None

    def policy_numbers_for_customer(self, customer_id: str) -> list[str]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT policy_number FROM policies WHERE customer_id = %s", (customer_id,)
            )
            rows = cur.fetchall()
        return [r["policy_number"] for r in rows]
