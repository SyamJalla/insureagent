"""GuardrailPipeline — ordered chain of checks over one user input.

Order (decided): length_cap → pii_presidio → moderation → injection.
The first two are deterministic and non-terminal for legitimate messages;
moderation runs before the injection classifier because it is the only check
that can ESCALATE, and the duty-of-care outcome (self-harm → empathetic
escalation) must win over a flat injection block when both would fire.

Modes (settings.guardrail_mode):
  off     — callers skip the pipeline entirely (service checks the flag).
  shadow  — every check runs and is logged/traced; NOTHING is acted on:
            no redaction applied, terminal action reported as ALLOW.
  enforce — verdicts applied: REDACT rewrites the text for later checks and
            the rest of the request; first BLOCK/ESCALATE short-circuits.

Observability: every non-ALLOW verdict emits a 🛡 log line and a Langfuse
span (Tracer.log_guardrail). ALLOW verdicts log at DEBUG to keep noise down.
"""
from functools import lru_cache
import logging

from app.auth.models import RequestContext
from app.config import get_settings
from app.guardrails.base import Guardrail
from app.guardrails.models import GuardrailAction, GuardrailVerdict, PipelineResult

logger = logging.getLogger("insureagent.guardrails")


class GuardrailPipeline:
    def __init__(self, checks: list[Guardrail]):
        self._checks = checks

    def run_input(self, text: str, ctx: RequestContext) -> PipelineResult:
        s = get_settings()
        enforce = s.guardrail_mode == "enforce"
        verdicts: list[GuardrailVerdict] = []
        current = text
        terminal = GuardrailAction.ALLOW
        user_reply: str | None = None

        for check in self._checks:
            try:
                verdict = check.check(current, ctx)
            except Exception:  # defense in depth; checks shouldn't raise
                logger.exception("guardrail %s raised — treating as ALLOW", check.name)
                verdict = GuardrailVerdict(check=check.name, action=GuardrailAction.ALLOW)
            verdicts.append(verdict)
            self._observe(ctx, verdict, s.guardrail_mode)

            if not enforce:
                continue  # shadow: measure everything, touch nothing
            if verdict.text is not None and verdict.action in (
                GuardrailAction.ALLOW, GuardrailAction.REDACT
            ):
                current = verdict.text
            if verdict.action in (GuardrailAction.BLOCK, GuardrailAction.ESCALATE):
                terminal = verdict.action
                user_reply = verdict.user_reply
                break

        if not enforce:
            return PipelineResult(action=GuardrailAction.ALLOW, text=text, verdicts=verdicts)
        return PipelineResult(
            action=terminal, text=current, user_reply=user_reply, verdicts=verdicts
        )

    @staticmethod
    def _observe(ctx: RequestContext, verdict: GuardrailVerdict, mode: str) -> None:
        line = (
            f"🛡 guardrail | check={verdict.check} action={verdict.action.value} "
            f"mode={mode} reason={verdict.reason or '-'}"
        )
        if verdict.action == GuardrailAction.ALLOW:
            logger.debug("[%s] %s", ctx.correlation_id, line)
            return
        logger.info("[%s] %s", ctx.correlation_id, line)
        from app.tracing import get_tracer  # local import: avoid cycle at module load

        get_tracer().log_guardrail(
            check=verdict.check, action=verdict.action.value,
            reason=verdict.reason, scores=verdict.scores, mode=mode,
        )


def _build() -> GuardrailPipeline:
    from app.guardrails.checks.injection_classifier import InjectionClassifier
    from app.guardrails.checks.length_cap import LengthCap
    from app.guardrails.checks.moderation import Moderation
    from app.guardrails.checks.pii_presidio import PiiRedaction

    s = get_settings()
    checks: list[Guardrail] = [LengthCap()]
    if s.guardrail_pii:
        checks.append(PiiRedaction())
    if s.guardrail_moderation:
        checks.append(Moderation())
    if s.guardrail_injection:
        checks.append(InjectionClassifier())
    return GuardrailPipeline(checks)


@lru_cache
def get_guardrail_pipeline() -> GuardrailPipeline:
    return _build()
