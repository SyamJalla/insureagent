"""Length cap + input normalization — the deterministic first rung.

Caps denial-of-wallet inputs (a pasted document is not a chat message) and
strips control characters that have no business in chat text.
"""
import re

from app.auth.models import RequestContext
from app.config import get_settings
from app.guardrails.base import Guardrail
from app.guardrails.models import GuardrailAction, GuardrailVerdict

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EXCESS_NEWLINES = re.compile(r"\n{3,}")

TOO_LONG_REPLY = (
    "That message is too long for me to handle in chat. Please summarize the "
    "key question, or ask to speak with a person if you need to share a document."
)


def _normalize(text: str) -> str:
    text = _CONTROL_CHARS.sub("", text)
    return _EXCESS_NEWLINES.sub("\n\n", text)


class LengthCap(Guardrail):
    name = "length_cap"

    def check(self, text: str, ctx: RequestContext) -> GuardrailVerdict:
        cleaned = _normalize(text)
        cap = get_settings().guardrail_max_input_chars
        if len(cleaned) > cap:
            return GuardrailVerdict(
                check=self.name, action=GuardrailAction.BLOCK,
                reason=f"input {len(cleaned)} chars > cap {cap}",
                user_reply=TOO_LONG_REPLY,
            )
        action = GuardrailAction.ALLOW
        return GuardrailVerdict(check=self.name, action=action, text=cleaned)
