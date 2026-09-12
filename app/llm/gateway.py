"""LlmGateway — the single chokepoint for every LLM call.

Responsibilities: tier routing, tier→model resolution (config), retries with
backoff, tier-fallback on repeated failure, and a CallRecord per call for
cost/latency observability. Agents call gateway.complete(); nothing above
this layer touches an LLM SDK.
"""
import logging
import time

from app.config import get_settings
from app.llm.models import CallRecord, LlmRequest, LlmResponse, ModelTier
from app.llm.provider import LlmProvider, OpenAiProvider
from app.llm.router import ModelRouter

logger = logging.getLogger("llm_gateway")

_MAX_ATTEMPTS = 2  # per tier; then fall back one tier stronger


class LlmGateway:
    def __init__(self, provider: LlmProvider, router: ModelRouter, models: dict[ModelTier, str]):
        self._provider = provider
        self._router = router
        self._models = models
        self.records: list[CallRecord] = []  # process-local; mirrored to logs

    def _model_for(self, tier: ModelTier) -> str:
        return self._models[tier]

    @staticmethod
    def _next_tier(tier: ModelTier) -> ModelTier | None:
        order = [ModelTier.FAST, ModelTier.STANDARD, ModelTier.REASONING]
        i = order.index(tier)
        return order[i + 1] if i + 1 < len(order) else None

    def complete(self, request: LlmRequest, correlation_id: str | None = None) -> LlmResponse:
        tier = self._router.tier_for(request.agent, request.complexity)
        last_error: Exception | None = None
        while tier is not None:
            model = self._model_for(tier)
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                start = time.monotonic()
                try:
                    response = self._provider.complete(request, model)
                except Exception as exc:  # provider/network errors: retry, then fall back
                    last_error = exc
                    logger.warning(
                        "llm call failed (agent=%s model=%s attempt=%d): %s",
                        request.agent, model, attempt, exc,
                    )
                    continue
                record = CallRecord(
                    agent=request.agent,
                    model=model,
                    tier=tier,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    latency_ms=int((time.monotonic() - start) * 1000),
                    correlation_id=correlation_id,
                )
                self.records.append(record)
                logger.info("🧠 llm_call %s", record.model_dump_json())
                return response
            tier = self._next_tier(tier)
            if tier is not None:
                logger.warning("falling back to tier=%s for agent=%s", tier.value, request.agent)
        raise RuntimeError(f"LLM call failed for {request.agent} after retries") from last_error


def build_default_gateway() -> LlmGateway:
    s = get_settings()
    return LlmGateway(
        provider=OpenAiProvider(s.openai_api_key),
        router=ModelRouter(s.complexity_routing_enabled),
        models={
            ModelTier.FAST: s.model_fast,
            ModelTier.STANDARD: s.model_standard,
            ModelTier.REASONING: s.model_reasoning,
        },
    )
