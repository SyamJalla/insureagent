"""Guardrail ABC — one concrete class per check, one file per class
(app/guardrails/checks/). A check must never raise out of `check()`: failures
degrade to ALLOW with a logged warning — guardrails protect the chat, they do
not get to break it. Cloud-stage checks (Bedrock Guardrails, Lakera) are new
files implementing this same contract.
"""
from abc import ABC, abstractmethod

from app.auth.models import RequestContext
from app.guardrails.models import GuardrailVerdict


class Guardrail(ABC):
    name: str

    @abstractmethod
    def check(self, text: str, ctx: RequestContext) -> GuardrailVerdict: ...
