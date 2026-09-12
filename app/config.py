"""Application configuration.

All paths, secrets, and tunables load from environment / .env via Pydantic.
Nothing elsewhere in the app reads os.getenv directly.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Secrets (from .env)
    openai_api_key: str
    jwt_secret: str = "change-me-in-.env"
    langfuse_secret_key: str | None = None
    langfuse_public_key: str | None = None
    langfuse_base_url: str | None = None

    # Auth
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60

    # Data sources
    # App-owned stores (users, conversations, messages) live in Postgres.
    # The synthetic insurance data stays in SQLite (the stand-in "enterprise
    # system") until the tool layer migrates it.
    app_db_url: str = "postgresql://postgres:root@localhost:5432/insureagent"
    db_path: Path = Path("datasources/database/insurance_support.db")
    vector_db_path: Path = Path("datasources/vector_database")
    faq_collection_name: str = "insurance_data_FAQ_collection"

    # Conversation
    history_message_limit: int = 20

    # LLM gateway — tier → concrete model (models change; code shouldn't)
    model_fast: str = "gpt-4o-mini"
    model_standard: str = "gpt-4o"
    model_reasoning: str = "gpt-4o"  # upgrade when a reasoning tier is adopted
    # Complexity-based routing (v2): built and tested, shipped OFF.
    # Flip only alongside an eval run — it changes cost/quality baselines.
    complexity_routing_enabled: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
