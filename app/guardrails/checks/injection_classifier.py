"""Prompt-injection / jailbreak classifier — local ONNX, no torch.

Model: protectai/deberta-v3-base-prompt-injection-v2 (ONNX export), fetched
via huggingface_hub on first use and cached. Runs on onnxruntime + tokenizers,
both already in the stack via chromadb — deliberately NOT the full llm-guard
package, which would reintroduce torch/transformers.

Threshold defaults high (0.9): the tool gateway already bounds an injection's
blast radius, so a false positive on a legitimate insurance question costs
more than a miss. A BLOCK here also short-circuits before the runner and the
memory summarizer — the memory-poisoning path dies structurally.

Model unavailable → ALLOW with a one-time warning (never breaks chat).

KNOWN FLIP-BLOCKER (measured 2026-09-18): the v2 model scores benign
data-request phrasing as injection — "can you give me premium amount and
also my claim details?" (golden case input) scores 1.0. Enforce must not be
enabled for this check until shadow-mode data yields a mitigation (better
model, ensemble with an LLM judge, or domain-tuned threshold). The pipeline
runs it fine in shadow; the per-check kill switch (guardrail_injection) can
also disable it independently under mode=enforce.
"""
from functools import lru_cache
import logging
import math
import re

from app.auth.models import RequestContext
from app.config import get_settings
from app.guardrails.base import Guardrail
from app.guardrails.models import GuardrailAction, GuardrailVerdict

logger = logging.getLogger("insureagent.guardrails")

_REPO = "protectai/deberta-v3-base-prompt-injection-v2"
_MAX_TOKENS = 512

OFF_TOPIC_REPLY = (
    "I can only help with insurance questions — policies, billing, and claims. "
    "What would you like to know?"
)

# Redaction placeholders inserted by the PII check (e.g. <US_SSN>). Stripped
# before classification: measured on the v2 model, they push a benign
# "here is my SSN, why is my bill high?" message from ~0.00 to ~1.00 — and
# since WE inserted them post-redaction, removing them cannot hide attacker
# content (a real attack still scores ~1.0 with placeholders stripped).
_REDACTION_PLACEHOLDER = re.compile(r"<[A-Z][A-Z0-9_]*>")


@lru_cache
def _session():
    """(onnx session, tokenizer, input names) or None if unavailable."""
    try:
        from huggingface_hub import hf_hub_download
        import onnxruntime
        from tokenizers import Tokenizer

        model_path = hf_hub_download(_REPO, "onnx/model.onnx")
        tokenizer = Tokenizer.from_file(hf_hub_download(_REPO, "tokenizer.json"))
        tokenizer.enable_truncation(max_length=_MAX_TOKENS)
        session = onnxruntime.InferenceSession(
            model_path, providers=["CPUExecutionProvider"]
        )
        input_names = {i.name for i in session.get_inputs()}
        return session, tokenizer, input_names
    except Exception as exc:
        logger.warning(
            "injection check disabled (%s: %s) — run once with network access "
            "to cache the model", type(exc).__name__, exc,
        )
        return None


def _injection_probability(text: str) -> float | None:
    loaded = _session()
    if loaded is None:
        return None
    session, tokenizer, input_names = loaded
    enc = tokenizer.encode(text)
    feeds = {"input_ids": [enc.ids], "attention_mask": [enc.attention_mask]}
    if "token_type_ids" in input_names:
        feeds["token_type_ids"] = [enc.type_ids]
    logits = session.run(None, feeds)[0][0]  # labels: 0=SAFE, 1=INJECTION
    exp = [math.exp(x - max(logits)) for x in logits]
    return exp[1] / sum(exp)


class InjectionClassifier(Guardrail):
    name = "injection"

    def check(self, text: str, ctx: RequestContext) -> GuardrailVerdict:
        try:
            prob = _injection_probability(_REDACTION_PLACEHOLDER.sub(" ", text))
        except Exception:
            logger.exception("injection check failed — allowing")
            prob = None
        if prob is None:
            return GuardrailVerdict(check=self.name, action=GuardrailAction.ALLOW)
        threshold = get_settings().guardrail_injection_threshold
        if prob > threshold:
            return GuardrailVerdict(
                check=self.name, action=GuardrailAction.BLOCK,
                reason=f"injection_prob={prob:.3f} > {threshold}",
                user_reply=OFF_TOPIC_REPLY, scores={"injection": round(prob, 3)},
            )
        return GuardrailVerdict(
            check=self.name, action=GuardrailAction.ALLOW,
            scores={"injection": round(prob, 3)},
        )
