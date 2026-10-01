"""Prompt sources — where agent prompts come from.

Default: YAML files in prompts/ (shared prompts) and prompts/tierN/ (overrides).
Optional: Langfuse Prompt Management (versioning, labels, rollback,
prompt<->trace linkage) with automatic file fallback — Langfuse being down
must never take the app down.

Flip via PROMPT_SOURCE=langfuse after seeding with scripts/push_prompts.py.
Same ship-dormant discipline as complexity routing: flip alongside an eval run.

Tier-aware loading (3-Tier architecture):
  FilePromptSource(tier=N) resolves:
    1. prompts/tier{N}/{name}.yaml   (tier-specific override, if it exists)
    2. prompts/{name}.yaml           (shared canonical prompt)
    3. prompts/tier1/{name}.yaml     (Tier 1 fallback)
    Tier 2/3 can override shared prompts and retain fallback compatibility with
    prompts stored under Tier 1.
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
    """YAML-based prompt loader with optional tier-specific override.

    name may be:
    - "billing_agent"       → prompts/tier{N}/billing_agent.yaml, then fallbacks
      - "tier3/router"        → prompts/tier3/router.yaml  (direct path)
      - "billing_agent" + tier=2 → tries prompts/tier2/billing_agent.yaml first
    """

    def __init__(self, tier: int = 0):
        # tier=0 means "root namespace only" (backward-compatible default)
        self._tier = tier

    def get(self, name: str) -> str:
        # If name already contains a slash it's an explicit sub-path — load directly.
        if "/" in name:
            path = _PROMPTS_DIR / f"{name}.yaml"
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f)["prompt"]

        # Tier-specific override: prompts/tier{N}/{name}.yaml
        if self._tier > 0:
            tier_path = _PROMPTS_DIR / f"tier{self._tier}" / f"{name}.yaml"
            if tier_path.exists():
                with open(tier_path, encoding="utf-8") as f:
                    return yaml.safe_load(f)["prompt"]

        # Root canonical fallback: prompts/{name}.yaml
        root_path = _PROMPTS_DIR / f"{name}.yaml"
        if root_path.exists():
            with open(root_path, encoding="utf-8") as f:
                return yaml.safe_load(f)["prompt"]

        # Tier 1 is canonical for prompts intentionally moved out of the root.
        tier1_path = _PROMPTS_DIR / "tier1" / f"{name}.yaml"
        with open(tier1_path, encoding="utf-8") as f:
            return yaml.safe_load(f)["prompt"]


class LangfusePromptSource(PromptSource):
    """Langfuse-managed prompts, file fallback on any failure."""

    def __init__(self, tier: int = 0):
        self._tier = tier
        self._fallback = FilePromptSource(tier=tier)

    def get(self, name: str) -> str:
        if "/" in name:
            return self._fallback.get(name)
        if self._tier > 0:
            tier_path = _PROMPTS_DIR / f"tier{self._tier}" / f"{name}.yaml"
            if tier_path.exists():
                return self._fallback.get(name)
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


@lru_cache(maxsize=8)
def get_prompt_source(tier: int = 0) -> PromptSource:
    """Return the configured PromptSource for the given tier.

    tier=0  → root namespace, then Tier 1 canonical prompt
    tier=1  → prompts/tier1/ canonical prompt
    tier=2  → prompts/tier2/ override, then root, then Tier 1
    tier=3  → prompts/tier3/ override, then root, then Tier 1

    lru_cache(maxsize=8) caches one instance per tier value.
    """
    if get_settings().prompt_source == "langfuse":
        logger.info("prompt source: langfuse (file fallback)")
        return LangfusePromptSource(tier=tier)
    return FilePromptSource(tier=tier)
