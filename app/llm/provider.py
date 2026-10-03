"""LLM providers. The ONLY module in the codebase that imports an LLM SDK.

Provider swap (e.g. Bedrock — decision D1) = one new class here; nothing
above this layer changes.
"""
from abc import ABC, abstractmethod
import json
import math

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

    @staticmethod
    def _temperature_unsupported(error: Exception) -> bool:
        return (
            getattr(error, "param", None) == "temperature"
            and getattr(error, "code", None)
            in {"unsupported_parameter", "unsupported_value"}
        )

    def complete(self, request: LlmRequest, model: str) -> LlmResponse:
        print(f"[llm-provider] openai agent={request.agent} model={model} messages={len(request.messages)}")
        kwargs: dict = {
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
        }
        if request.tools:
            kwargs["tools"] = request.tools
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            if not self._temperature_unsupported(exc):
                raise
            kwargs.pop("temperature")
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
        print(f"[llm-provider] groq agent={request.agent} model={model} messages={len(request.messages)}")
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
    """Classify Tier 3 requests with the local Laya router."""

    VALID_DECISIONS = frozenset({"billing", "policy", "claims", "fallback"})

    def __init__(self):
        from laya.integrations.langchain import LayaRouter

        self._router_factory = LayaRouter
        self._router = None

    def classify(self, user_input: str, router_config: dict) -> dict:
        import logging

        logger = logging.getLogger("insureagent.laya")
        question = router_config["question"]
        from app.tracing import get_tracer

        print(f"[laya] classify input={user_input[:80]!r} prompt={question.get('name', 'unknown')}")
        tracer = get_tracer()
        with tracer.observation(
            "laya:classification",
            input={"character_count": len(user_input)},
            metadata={"provider": "laya", "execution": "local"},
        ) as span:
            try:
                if self._router is None:
                    self._router = self._router_factory(
                        criteria=router_config["allowed_answers"],
                        instructions=question["prompt"],
                    )
                decision = self._router.invoke(user_input)
                answer = (self._router.last_decision or {}).get("answers", {}).get("route", {})
                confidence = float(
                    answer.get("answer_confidence", answer.get("confidence", 0.0)) or 0.0
                )
                if (
                    decision not in self.VALID_DECISIONS
                    or not math.isfinite(confidence)
                    or not 0.0 <= confidence <= 1.0
                ):
                    decision, confidence = "fallback", 0.0
                outcome = {"decision": decision, "confidence": confidence}
                print(f"[laya] decision={decision} confidence={confidence} source={question.get('name', 'unknown')}")
                if span:
                    span.update(output=outcome)
                return outcome
            except Exception as exc:
                print(f"[laya] classification failed: {type(exc).__name__}: {exc}")
                logger.warning(
                    "Laya classification failed (%s) — using fallback",
                    type(exc).__name__,
                )
                if span:
                    span.update(
                        output={"decision": "fallback", "confidence": 0.0},
                        level="ERROR",
                        status_message=f"{type(exc).__name__}: local classification failed",
                    )
                return {"decision": "fallback", "confidence": 0.0}
