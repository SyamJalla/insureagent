"""Content moderation — toxicity, person-directed threats, and self-harm.

Uses the provider's moderation endpoint through the LLM gateway (the single
SDK chokepoint rule holds). The self-harm branch is the insurance-specific
duty of care: it ESCALATES with an empathetic reply, never a filter message.
The only check that can ESCALATE — which is why it runs before the injection
classifier (pipeline-order decision).

API unreachable → ALLOW with a warning; the chain continues.
"""
import logging

from app.auth.models import RequestContext
from app.config import get_settings
from app.guardrails.base import Guardrail
from app.guardrails.models import GuardrailAction, GuardrailVerdict

logger = logging.getLogger("insureagent.guardrails")

SELF_HARM_REPLY = (
    "I'm really sorry you're going through this — it sounds serious, and I want "
    "to make sure you speak with a person rather than a bot. I'm connecting you "
    "with one of our support specialists now. If you are in immediate danger, "
    "please contact your local emergency number, or call or text 988 (Suicide & "
    "Crisis Lifeline) to talk with someone right away."
)
TOXICITY_REPLY = (
    "I want to help, but I can't continue with this conversation in this tone. "
    "If you'd prefer, I can connect you with a person to take it from here."
)


class Moderation(Guardrail):
    name = "moderation"

    def check(self, text: str, ctx: RequestContext) -> GuardrailVerdict:
        try:
            from app.agents.runner import _gateways

            llm, _ = _gateways()
            result = llm.moderate(text)
        except Exception as exc:
            logger.warning("moderation unavailable (%s) — allowing", exc)
            return GuardrailVerdict(check=self.name, action=GuardrailAction.ALLOW)

        s = get_settings()
        scores = result.scores
        self_harm = max(
            (v for k, v in scores.items() if k.startswith("self_harm")), default=0.0
        )
        if self_harm >= s.guardrail_self_harm_threshold:
            return GuardrailVerdict(
                check=self.name, action=GuardrailAction.ESCALATE,
                reason=f"self_harm={self_harm:.2f}",
                user_reply=SELF_HARM_REPLY, scores=scores,
            )
        toxic = max(
            (v for k, v in scores.items()
             if k.startswith(("violence", "harassment", "hate"))),
            default=0.0,
        )
        if toxic >= s.guardrail_toxicity_threshold:
            return GuardrailVerdict(
                check=self.name, action=GuardrailAction.BLOCK,
                reason=f"toxicity={toxic:.2f}",
                user_reply=TOXICITY_REPLY, scores=scores,
            )
        return GuardrailVerdict(
            check=self.name, action=GuardrailAction.ALLOW, scores=scores
        )
