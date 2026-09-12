"""Terminal nodes: final answer composition and human escalation."""
from langchain_core.runnables import RunnableConfig

from app.agents.base import load_prompt, render, _cfg
from app.llm.models import LlmRequest


def final_answer_node(state: dict, config: RunnableConfig) -> dict:
    ctx, llm, _tools = _cfg(config)
    system = render(
        load_prompt("final_answer_agent"),
        user_query=state.get("user_input", ""),
        specialist_response="\n".join(state.get("collected_facts", [])),
    )
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
