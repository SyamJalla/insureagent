"""Graph state. RequestContext deliberately NOT here — identity travels in
LangGraph's config channel so the LLM can never see or rewrite it."""
from typing import Annotated, TypedDict

from app.llm.models import Complexity


def _append(a: list, b: list) -> list:
    return a + b


class GraphState(TypedDict, total=False):
    # Input & context
    user_input: str
    conversation_history: str          # single writer: the runner. Specialists
                                       # write only collected_facts (parallel-safe)

    # Supervisor routing (LLM proposes; the routing function decides)
    next_agent: str
    task: str
    justification: str
    complexity: Complexity | None      # written every turn; routed on only when flag on
    n_iteration: int

    # Work products
    collected_facts: Annotated[list[str], _append]

    # Outcomes (first-class — no exceptions/monkeypatches)
    clarification_question: str | None
    requires_human_escalation: bool
    escalation_reason: str
    final_answer: str
    outcome: str                       # "answer" | "clarification" | "escalated"
