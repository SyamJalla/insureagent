"""Prompt sources — where agent prompts come from.

Default: YAML files in prompts/ (git-reviewed source of truth).
Optional: Langfuse Prompt Management (versioning, labels, rollback,
prompt<->trace linkage) with automatic file fallback — Langfuse being down
must never take the app down.

Flip via PROMPT_SOURCE=langfuse after seeding with scripts/push_prompts.py.
Same ship-dormant discipline as complexity routing: flip alongside an eval run.
"""
from abc import ABC, abstractmethod
from functools import lru_cache
import logging
from pathlib import Path

import yaml

from app.config import get_settings

logger = logging.getLogger("insureagent.prompts")
_PROMPTS_DIR = Path("prompts")


class PromptSource(ABC):
    @abstractmethod
    def get(self, name: str) -> str: ...


class FilePromptSource(PromptSource):
    def get(self, name: str) -> str:
        with open(_PROMPTS_DIR / f"{name}.yaml", encoding="utf-8") as f:
            return yaml.safe_load(f)["prompt"]


class LangfusePromptSource(PromptSource):
    """Langfuse-managed prompts, file fallback on any failure."""

    def __init__(self):
        self._fallback = FilePromptSource()

    def get(self, name: str) -> str:
        try:
            from app.tracing import get_tracer

            tracer = get_tracer()
            if not tracer.enabled:
                return self._fallback.get(name)
            prompt = tracer._client.get_prompt(name)  # cached by the SDK
            return prompt.prompt
        except Exception as exc:
            logger.warning("langfuse prompt %r unavailable (%s) — file fallback", name, exc)
            return self._fallback.get(name)


@lru_cache
def get_prompt_source() -> PromptSource:
    if get_settings().prompt_source == "langfuse":
        logger.info("prompt source: langfuse (file fallback)")
        return LangfusePromptSource()
    return FilePromptSource()
