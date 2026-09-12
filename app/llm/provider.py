"""LLM providers. The ONLY module in the codebase that imports an LLM SDK.

Provider swap (e.g. Bedrock — decision D1) = one new class here; nothing
above this layer changes.
"""
from abc import ABC, abstractmethod
import json

from openai import OpenAI

from app.llm.models import LlmRequest, LlmResponse, ToolCall


class LlmProvider(ABC):
    @abstractmethod
    def complete(self, request: LlmRequest, model: str) -> LlmResponse: ...


class OpenAiProvider(LlmProvider):
    def __init__(self, api_key: str):
        self._client = OpenAI(api_key=api_key)

    def complete(self, request: LlmRequest, model: str) -> LlmResponse:
        kwargs: dict = {
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
        }
        if request.tools:
            kwargs["tools"] = request.tools
        resp = self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0].message
        tool_calls = [
            ToolCall(
                call_id=tc.id,
                name=tc.function.name,
                arguments=json.loads(tc.function.arguments or "{}"),
            )
            for tc in (choice.tool_calls or [])
        ]
        usage = resp.usage
        return LlmResponse(
            content=choice.content,
            tool_calls=tool_calls,
            model=model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )
