"""LLM providers. The ONLY module in the codebase that imports an LLM SDK.

Provider swap (e.g. Bedrock — decision D1) = one new class here; nothing
above this layer changes.
"""
from abc import ABC, abstractmethod
import json

from openai import OpenAI

from app.llm.models import LlmRequest, LlmResponse, ModerationScores, ToolCall


class LlmProvider(ABC):
    @abstractmethod
    def complete(self, request: LlmRequest, model: str) -> LlmResponse: ...

    @abstractmethod
    def moderate(self, text: str) -> ModerationScores:
        """Content-safety classification of one text (guardrails use this)."""


class OpenAiProvider(LlmProvider):
    def __init__(self, api_key: str):
        self._client = OpenAI(api_key=api_key)

    def complete(self, request: LlmRequest, model: str) -> LlmResponse:
        kwargs: dict = {
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
        }
        if request.tools:
            kwargs["tools"] = request.tools
        resp = self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0].message
        tool_calls = [
            ToolCall(
                call_id=tc.id,
                name=tc.function.name,
                arguments=json.loads(tc.function.arguments or "{}"),
            )
            for tc in (choice.tool_calls or [])
        ]
        usage = resp.usage
        return LlmResponse(
            content=choice.content,
            tool_calls=tool_calls,
            model=model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )

    def moderate(self, text: str) -> ModerationScores:
        resp = self._client.moderations.create(
            model="omni-moderation-latest", input=text
        )
        result = resp.results[0]
        scores = {
            k.replace("-", "_").replace("/", "_"): float(v or 0.0)
            for k, v in result.category_scores.model_dump().items()
        }
        return ModerationScores(flagged=bool(result.flagged), scores=scores)


class GroqProvider(LlmProvider):
    """Groq SDK wrapper — same LlmProvider interface as OpenAiProvider.

    Used for Tier 2 (full pipeline) and Tier 3 (execution/content generation
    calls after Laya has routed to a domain agent).
    Groq models are configured per tier in app.config.Settings.
    """

    def __init__(self, api_key: str):
        from groq import Groq  # lazy: not imported unless tier 2/3 is active
        self._client = Groq(api_key=api_key)

    def complete(self, request: LlmRequest, model: str) -> LlmResponse:
        kwargs: dict = {
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
        }
        if request.tools:
            kwargs["tools"] = request.tools
        resp = self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0].message
        tool_calls = [
            ToolCall(
                call_id=tc.id,
                name=tc.function.name,
                arguments=json.loads(tc.function.arguments or "{}"),
            )
            for tc in (choice.tool_calls or [])
        ]
        usage = resp.usage
        return LlmResponse(
            content=choice.content,
            tool_calls=tool_calls,
            model=model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )

    def moderate(self, text: str) -> ModerationScores:
        # Groq has no moderation endpoint; return a safe pass-through default.
        return ModerationScores(flagged=False, scores={})


class LayaClassifier:
    """Thin HTTP wrapper around the Laya non-autoregressive classification endpoint.

    Deliberately NOT a subclass of LlmProvider — it classifies requests into
    insurance domains rather than generating text.  The result drives the Tier-3
    domain-routing decision.

    Input : user message (str) + router system prompt (str)
    Output: {'decision': 'billing'|'policy'|'claims'|'fallback',
             'confidence': float 0.0–1.0}

    Any HTTP error, timeout, or unrecognised label is caught and returned as
    {'decision': 'fallback', 'confidence': 0.0} so the pipeline can gracefully
    fall back to Tier-2 Groq without crashing.
    """

    VALID_DOMAINS = frozenset({"billing", "policy", "claims"})

    def __init__(self, api_key: str, base_url: str, model: str):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model

    def classify(self, user_input: str, router_prompt: str) -> dict:
        import logging
        import httpx

        _log = logging.getLogger("insureagent.laya")
        try:
            r = httpx.post(
                f"{self._base_url}/classify",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "system": router_prompt,
                    "input": user_input,
                },
                timeout=5.0,
            )
            r.raise_for_status()
            data = r.json()
            decision = data.get("decision", "fallback")
            if decision not in self.VALID_DOMAINS:
                decision = "fallback"
            return {
                "decision": decision,
                "confidence": float(data.get("confidence", 0.0)),
            }
        except Exception as exc:
            _log.warning("Laya classify failed (%s) — using fallback", exc)
            return {"decision": "fallback", "confidence": 0.0}
