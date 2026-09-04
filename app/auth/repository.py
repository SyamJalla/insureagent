"""User persistence. The only module that reads the users table."""
from abc import ABC, abstractmethod
import sqlite3
from pathlib import Path

from app.auth.models import Role, User


class UserStore(ABC):
    @abstractmethod
    def get_by_email(self, email: str) -> tuple[User, str] | None:
        """Return (user, password_hash) or None."""

    @abstractmethod
    def get_by_id(self, user_id: str) -> User | None: ...

    @abstractmethod
    def policy_numbers_for_customer(self, customer_id: str) -> list[str]: ...


class SqliteUserStore(UserStore):
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _to_user(row: sqlite3.Row) -> User:
        return User(
            user_id=row["user_id"],
            email=row["email"],
            display_name=row["display_name"],
            role=Role(row["role"]),
            customer_id=row["customer_id"],
            agent_id=row["agent_id"],
        )

    def get_by_email(self, email: str) -> tuple[User, str] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return (self._to_user(row), row["password_hash"]) if row else None

    def get_by_id(self, user_id: str) -> User | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return self._to_user(row) if row else None

    def policy_numbers_for_customer(self, customer_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT policy_number FROM policies WHERE customer_id = ?", (customer_id,)
            ).fetchall()
        return [r["policy_number"] for r in rows]
