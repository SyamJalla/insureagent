"""SpecialistAgent — the shared pattern all domain agents follow:
load YAML prompt → call LLM (via LlmGateway) with the agent's allowed tools →
execute tool calls via ToolGateway (ctx from config, never from the LLM) →
feed results back → land facts in state.
"""
import json
import logging
from pathlib import Path

import yaml
from langchain_core.runnables import RunnableConfig

logger = logging.getLogger("insureagent.agents")

from app.auth.models import RequestContext
from app.llm.models import LlmRequest

_MAX_TOOL_ROUNDS = 4
_PROMPTS_DIR = Path("prompts")


class _SafeDict(dict):
    def __missing__(self, key):  # tolerate placeholders a given turn doesn't fill
        return ""


def load_prompt(name: str) -> str:
    with open(_PROMPTS_DIR / f"{name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["prompt"]


def render(template: str, **fields) -> str:
    return template.format_map(_SafeDict(fields))


def _cfg(config: dict):
    c = config["configurable"]
    return c["ctx"], c["llm"], c["tools"]


class SpecialistAgent:
    name: str = ""            # node name (also the router's tier key)
    prompt_name: str = ""
    tool_names: list[str] = []

    def __call__(self, state: dict, config: RunnableConfig) -> dict:
        ctx, llm, tools = _cfg(config)
        logger.info(
            "[%s] 🤖 %s start | task=%r",
            ctx.correlation_id, self.name, state.get("task", "")[:100],
        )
        system = render(
            load_prompt(self.prompt_name),
            task=state.get("task", state.get("user_input", "")),
            conversation_history=state.get("conversation_history", ""),
            **self.extra_fields(state, ctx, tools),
        )
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": state.get("user_input", "")},
        ]
        specs = tools.specs_for(self.tool_names, ctx) if self.tool_names else None

        for _ in range(_MAX_TOOL_ROUNDS):
            response = llm.complete(
                LlmRequest(
                    agent=self.name,
                    messages=messages,
                    tools=specs,
                    complexity=state.get("complexity"),
                ),
                correlation_id=ctx.correlation_id,
            )
            if not response.tool_calls:
                break
            messages.append({
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.call_id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in response.tool_calls
                ],
            })
            for tc in response.tool_calls:
                logger.info(
                    "[%s] 🤖 %s → tool %s(%s)",
                    ctx.correlation_id, self.name, tc.name,
                    json.dumps(tc.arguments)[:120],
                )
                result = tools.invoke(ctx, tc.name, tc.arguments)
                payload = result.data if result.ok else {"error": result.error}
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.call_id,
                    "content": json.dumps(payload, default=str),
                })

        answer = response.content or "I could not complete this task."
        logger.info("[%s] 🤖 %s done | answer=%r", ctx.correlation_id, self.name, answer[:100])
        return {
            "collected_facts": [f"[{self.name}] {answer}"],
            "conversation_history": state.get("conversation_history", "")
            + f"\n{self.name}: {answer}",
        }

    def extra_fields(self, state: dict, ctx: RequestContext, tools) -> dict:
        """Per-agent prompt fields beyond task/history. Override as needed."""
        return {}
