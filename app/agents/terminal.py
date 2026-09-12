"""Terminal nodes: final answer composition and human escalation."""
import logging

from langchain_core.runnables import RunnableConfig

from app.agents.base import load_prompt, render, _cfg
from app.llm.models import LlmRequest

logger = logging.getLogger("insureagent.agents")


_GROUNDING_RULES = """

GROUNDING RULES (mandatory):
- Use ONLY facts present in the specialist findings and conversation history above.
- NEVER invent amounts, dates, statuses, or policy details. No placeholder values.
- If the needed information is not present above, say you could not retrieve it
  and invite the user to ask again — do not guess."""


def final_answer_node(state: dict, config: RunnableConfig) -> dict:
    ctx, llm, _tools = _cfg(config)
    facts = state.get("collected_facts", [])
    if not facts:
        # Legitimate when the answer already exists in history (repeat question),
        # but worth flagging: without history grounding this is where models invent.
        logger.warning(
            "[%s] ✍️ final_answer with 0 new facts — answering from history only",
            ctx.correlation_id,
        )
    else:
        logger.info(
            "[%s] ✍️ final_answer | composing from %d fact(s)", ctx.correlation_id, len(facts)
        )
    # The known-facts block: this turn's findings + the conversation history,
    # so repeat questions are answered from the record, never fabricated.
    known = "\n".join(facts) if facts else "(no new specialist findings this turn)"
    known += "\n\n[Conversation history]\n" + state.get("conversation_history", "")
    system = render(
        load_prompt("final_answer_agent"),
        user_query=state.get("user_input", ""),
        specialist_response=known,
    ) + _GROUNDING_RULES
    response = llm.complete(
        LlmRequest(
            agent="final_answer_agent",
            messages=[{"role": "system", "content": system}],
            complexity=state.get("complexity"),
        ),
        correlation_id=ctx.correlation_id,
    )
    return {
        "final_answer": response.content or "Sorry, I could not generate a response.",
        "outcome": "answer",
    }


def escalation_node(state: dict, config: RunnableConfig) -> dict:
    ctx, llm, _tools = _cfg(config)
    logger.warning(
        "[%s] 🚨 escalation | reason=%r",
        ctx.correlation_id, state.get("escalation_reason", "supervisor decision"),
    )
    system = render(
        load_prompt("human_escalation_agent"),
        task=state.get("task", state.get("user_input", "")),
        conversation_history=state.get("conversation_history", ""),
    )
    response = llm.complete(
        LlmRequest(
            agent="human_escalation_agent",
            messages=[{"role": "system", "content": system}],
        ),
        correlation_id=ctx.correlation_id,
    )
    # Tranche A follow-up: also insert a `cases` row here (CSR workflow).
    return {
        "final_answer": response.content
        or "I'm connecting you with a human specialist who can help further.",
        "requires_human_escalation": True,
        "outcome": "escalated",
    }
