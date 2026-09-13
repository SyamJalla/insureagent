"""Langfuse tracing — the AI-plane observability seam.

The ONLY module that imports the Langfuse SDK (v4, OTel-based). Everything is
defensive: tracing must never break a request. If keys are missing or the
server is unreachable, the tracer runs disabled and every call is a no-op.

ID mapping (the join key design):
  Langfuse trace id  <- seeded from correlation_id (one message turn)
  Langfuse session   <- conversation_id (thread-level filter in the UI)
  Langfuse user      <- user_id
  metadata           <- role, login session (jti)
Spans/generations nest automatically via OTel context inside request_trace().
"""
from contextlib import contextmanager
from functools import lru_cache
import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger("insureagent.tracing")


class Tracer:
    def __init__(self):
        self._client = None
        s = get_settings()
        if not (s.langfuse_public_key and s.langfuse_secret_key):
            logger.info("tracing disabled (no Langfuse keys configured)")
            return
        try:
            from langfuse import Langfuse

            client = Langfuse(
                public_key=s.langfuse_public_key,
                secret_key=s.langfuse_secret_key,
                host=s.langfuse_base_url or "http://localhost:3000",
            )
            if not client.auth_check():
                logger.warning("tracing disabled (Langfuse auth check failed)")
                return
            self._client = client
            logger.info("tracing enabled -> %s", s.langfuse_base_url)
        except Exception as exc:  # unreachable server, bad config, SDK drift
            logger.warning("tracing disabled (%s: %s)", type(exc).__name__, exc)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @contextmanager
    def request_trace(self, ctx, user_input: str):
        """Wrap one message turn. Child observations nest via OTel context."""
        if not self._client:
            yield None
            return
        try:
            trace_id = self._client.create_trace_id(seed=ctx.correlation_id)
            span_cm = self._client.start_as_current_observation(
                name="chat_request",
                as_type="span",
                input=user_input,
                trace_context={"trace_id": trace_id},
            )
        except Exception:
            logger.exception("failed to open trace")
            yield None
            return
        with span_cm as span:
            try:
                span.update_trace(
                    user_id=ctx.user.user_id,
                    session_id=ctx.conversation_id or ctx.correlation_id,
                    tags=[ctx.user.role.value],
                    metadata={
                        "correlation_id": ctx.correlation_id,
                        "login_session": ctx.session_id,
                    },
                )
            except Exception:
                logger.exception("failed to annotate trace")
            yield span

    def log_generation(
        self, *, agent: str, model: str, tier: str,
        messages: list, output: Any, input_tokens: int, output_tokens: int,
    ) -> None:
        if not self._client:
            return
        try:
            gen = self._client.start_observation(
                name=f"llm:{agent}", as_type="generation",
                input=messages, model=model, metadata={"tier": tier},
            )
            gen.update(
                output=output,
                usage_details={"input": input_tokens, "output": output_tokens},
            )
            gen.end()
        except Exception:
            logger.exception("failed to log generation")

    def log_tool_call(self, *, name: str, args: dict, ok: bool, output: Any) -> None:
        if not self._client:
            return
        try:
            span = self._client.start_observation(
                name=f"tool:{name}", as_type="span",
                input=args, metadata={"ok": ok},
            )
            span.update(output=output, level="ERROR" if not ok else "DEFAULT")
            span.end()
        except Exception:
            logger.exception("failed to log tool call")

    def finish_request(self, outcome: str, answer: str) -> None:
        """Annotate the current trace with the final result."""
        if not self._client:
            return
        try:
            self._client.update_current_span(output={"outcome": outcome, "answer": answer})
        except Exception:
            logger.exception("failed to finish trace")

    def score(self, correlation_id: str, name: str, value: float, comment: str | None = None) -> None:
        """Attach a score (e.g. user feedback) to the trace of a past request."""
        if not self._client:
            return
        try:
            trace_id = self._client.create_trace_id(seed=correlation_id)
            self._client.create_score(
                trace_id=trace_id, name=name, value=value, comment=comment
            )
            self._client.flush()
        except Exception:
            logger.exception("failed to score trace")

    def flush(self) -> None:
        if self._client:
            try:
                self._client.flush()
            except Exception:
                logger.exception("flush failed")


@lru_cache
def get_tracer() -> Tracer:
    return Tracer()
