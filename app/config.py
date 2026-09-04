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
    db_path: Path = Path("datasources/database/insurance_support.db")
    vector_db_path: Path = Path("datasources/vector_database")
    faq_collection_name: str = "insurance_data_FAQ_collection"

    # Conversation
    history_message_limit: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
