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

    def moderate(self, text: str):
        """Pass-through to the provider's moderation endpoint (guardrails)."""
        return self._provider.moderate(text)

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
                        "[%s] llm call failed (agent=%s model=%s attempt=%d): %s",
                        correlation_id, request.agent, model, attempt, exc,
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
                from app.tracing import get_tracer  # local import: avoid cycle at module load

                get_tracer().log_generation(
                    agent=request.agent, model=model, tier=tier.value,
                    messages=request.messages,
                    output=response.content or [tc.model_dump() for tc in response.tool_calls],
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
                return response
            tier = self._next_tier(tier)
            if tier is not None:
                logger.warning("falling back to tier=%s for agent=%s", tier.value, request.agent)
        raise RuntimeError(f"LLM call failed for {request.agent} after retries") from last_error


def build_default_gateway(model_override: str | None = None) -> LlmGateway:
    s = get_settings()
    if not s.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required to use Tier 1.")
    models = {
        ModelTier.FAST: s.tier1_specialist_model,
        ModelTier.STANDARD: s.tier1_supervisor_model,
        ModelTier.REASONING: s.tier1_specialist_model,
    }
    if model_override:
        models[ModelTier.FAST] = model_override
    return LlmGateway(
        provider=OpenAiProvider(s.openai_api_key),
        router=ModelRouter(s.complexity_routing_enabled),
        models=models,
    )


def build_groq_gateway(specialist_model: str, supervisor_model: str | None = None) -> LlmGateway:
    """Build a Groq gateway, optionally assigning a separate supervisor model."""
    from app.llm.provider import GroqProvider

    s = get_settings()
    if not s.groq_api_key:
        raise RuntimeError(
            "GROQ_API_KEY is required to use Tier 2 or Tier 3. "
            "Set it in .env and restart."
        )
    return LlmGateway(
        provider=GroqProvider(s.groq_api_key),
        router=ModelRouter(complexity_routing_enabled=False),
        models={
            ModelTier.FAST: specialist_model,
            ModelTier.STANDARD: supervisor_model or specialist_model,
            ModelTier.REASONING: specialist_model,
        },
    )


def build_gateway_for_tier(tier: int, model_override: str | None = None) -> LlmGateway:
    """Select and build the appropriate gateway based on the active tier.

    Tier 1 → OpenAI (separate supervisor and specialist models)
    Tier 2 → Groq   (separate supervisor and specialist models)
    Tier 3 → Laya classifier + Groq open-source worker
    """
    s = get_settings()
    if tier == 2:
        return build_groq_gateway(
            s.tier2_specialist_model,
            supervisor_model=s.tier2_supervisor_model,
        )
    if tier == 3:
        return build_groq_gateway(model_override or s.tier3_worker_model)
    return build_default_gateway()  # tier 1 default
