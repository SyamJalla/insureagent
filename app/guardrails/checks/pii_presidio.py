"""PII redaction (Microsoft Presidio) — sensitive identifiers never persist.

Redacts to typed placeholders (<US_SSN>, <CREDIT_CARD>) BEFORE the message is
stored, traced, summarized into memory, or shown to the agent — one text
everywhere (decided policy). Email/phone are deliberately not redacted:
legitimate support context.

Presidio's SSN/card/bank recognizers are pattern+checksum based, so the small
spaCy model suffices (en_core_web_lg is the recall upgrade later). Engines
load lazily on first use; load failure degrades to ALLOW with a warning.
"""
from functools import lru_cache
import logging

from app.auth.models import RequestContext
from app.config import get_settings
from app.guardrails.base import Guardrail
from app.guardrails.models import GuardrailAction, GuardrailVerdict

logger = logging.getLogger("insureagent.guardrails")


@lru_cache
def _engines():
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from presidio_anonymizer import AnonymizerEngine

        # Pin the small spaCy model explicitly — Presidio's default config
        # otherwise downloads en_core_web_lg (~400 MB) at first use.
        nlp = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }).create_engine()
        return AnalyzerEngine(nlp_engine=nlp), AnonymizerEngine()
    except Exception as exc:  # missing package / spaCy model
        logger.warning("PII check disabled (%s: %s)", type(exc).__name__, exc)
        return None


class PiiRedaction(Guardrail):
    name = "pii_presidio"

    def check(self, text: str, ctx: RequestContext) -> GuardrailVerdict:
        engines = _engines()
        if engines is None:
            return GuardrailVerdict(check=self.name, action=GuardrailAction.ALLOW)
        analyzer, anonymizer = engines
        try:
            entities = get_settings().guardrail_pii_entities
            findings = analyzer.analyze(text=text, entities=entities, language="en")
            if not findings:
                return GuardrailVerdict(check=self.name, action=GuardrailAction.ALLOW)
            from presidio_anonymizer.entities import OperatorConfig

            redacted = anonymizer.anonymize(
                text=text,
                analyzer_results=findings,
                operators={"DEFAULT": OperatorConfig("replace", {"new_value": None})},
            )
            return GuardrailVerdict(
                check=self.name, action=GuardrailAction.REDACT,
                text=redacted.text,
                reason=",".join(sorted({f.entity_type for f in findings})),
                scores={f.entity_type: round(f.score, 3) for f in findings},
            )
        except Exception:
            logger.exception("PII check failed — allowing")
            return GuardrailVerdict(check=self.name, action=GuardrailAction.ALLOW)
