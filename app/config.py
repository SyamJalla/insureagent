"""Application configuration.

All paths, secrets, and tunables load from environment / .env via Pydantic.
Nothing elsewhere in the app reads os.getenv directly.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Deployment environment: "dev" (default) or "prod". In prod, unsafe
    # defaults refuse to boot (see get_settings).
    environment: str = "dev"

    # Secrets (from .env)
    openai_api_key: str
    jwt_secret: str = "change-me-in-.env"
    langfuse_secret_key: str | None = None
    langfuse_public_key: str | None = None
    langfuse_base_url: str | None = None

    # Auth
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60

    # Data sources — all app-owned and enterprise data lives in Postgres;
    # the vector store holds the FAQ + user-memory embeddings (Chroma).
    app_db_url: str = "postgresql://postgres:root@localhost:5432/insureagent"
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

    # Memory block: the write path (summarizer → memory_items) is always on;
    # this flag gates the READ path (memory injected into prompts).
    memory_enabled: bool = False

    # Prompt source: "file" (prompts/*.yaml, git-reviewed) or "langfuse"
    # (Prompt Management with file fallback). Seed via scripts/push_prompts.py.
    prompt_source: str = "file"

    # Guardrails (input safety pipeline, app/guardrails/):
    # mode "off" = not invoked · "shadow" = evaluate+log only · "enforce" = act.
    # Flip to enforce only alongside golden attack cases (eval-then-flip).
    guardrail_mode: str = "off"
    guardrail_max_input_chars: int = 4000
    guardrail_pii: bool = True
    guardrail_moderation: bool = True
    guardrail_injection: bool = True
    guardrail_pii_entities: list[str] = [
        "US_SSN", "CREDIT_CARD", "US_BANK_NUMBER", "US_DRIVER_LICENSE", "US_PASSPORT",
        "IN_AADHAAR", "IN_PAN",
    ]
    guardrail_self_harm_threshold: float = 0.5
    guardrail_toxicity_threshold: float = 0.7
    guardrail_injection_threshold: float = 0.9


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.environment == "prod" and s.jwt_secret == "change-me-in-.env":
        # The JWT secret is the ONLY thing preventing forged tokens; with
        # the default value, anyone can mint an admin session. Fail loud.
        raise RuntimeError(
            "Refusing to start: ENVIRONMENT=prod with the default JWT_SECRET. "
            "Set a real one, e.g.:  openssl rand -hex 32"
        )
    return s
