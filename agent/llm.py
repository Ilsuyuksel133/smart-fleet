"""LLM providers behind one small interface.

The agent loop only talks to ``LLMProvider.chat``. That makes it possible to
swap the real model (Ollama) for scripted answers (FakeProvider) in tests and
CI, where no model is available.
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

from agent.config import Settings

# Messages and tool definitions use the Ollama/OpenAI chat format, e.g.
# {"role": "user", "content": "..."} and {"type": "function", "function": {...}}
Message = dict[str, Any]
ToolDefinition = dict[str, Any]


@dataclass
class ToolCall:
    """A request from the model to run one tool with the given arguments."""

    name: str
    arguments: dict[str, Any]
    id: str | None = None  # set by Ollama; echoed back with the tool result


@dataclass
class LLMResponse:
    """One model turn: either tool calls to execute, or a final text answer."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)

    def as_message(self) -> Message:
        """Convert the response into an assistant message for the chat history."""
        message: Message = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            message["tool_calls"] = [
                {"id": call.id, "function": {"name": call.name, "arguments": call.arguments}}
                if call.id
                else {"function": {"name": call.name, "arguments": call.arguments}}
                for call in self.tool_calls
            ]
        return message


class LLMProvider(ABC):
    """Anything that can answer a chat conversation, optionally using tools."""

    name: str

    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """One model turn. With `response_schema`, the answer must be JSON matching it."""


class OllamaProvider(LLMProvider):
    """Calls a local Ollama server through its HTTP chat API."""

    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float,
        think: bool = False,
        max_tokens: int = 1024,
        attempts: int = 2,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.think = think
        self.max_tokens = max_tokens
        self.attempts = attempts

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            # One complete answer instead of a token stream: simpler to handle
            "stream": False,
            # "Thinking" models (e.g. qwen3) can reason before answering;
            # slower but sometimes more accurate. Configurable via OLLAMA_THINK.
            "think": self.think,
            # Upper limit on generated tokens. A report needs a few hundred; the
            # limit stops a model that starts repeating itself from running into
            # the timeout (this happened once in the evaluation).
            "options": {"num_predict": self.max_tokens},
        }
        if response_schema:
            # Structured output: Ollama constrains generation to this JSON schema,
            # so the answer is always valid JSON with the right fields and enums.
            payload["format"] = response_schema
        message = self._post(payload)

        tool_calls = [
            ToolCall(
                name=call["function"]["name"],
                arguments=call["function"].get("arguments") or {},
                id=call.get("id"),
            )
            for call in message.get("tool_calls") or []
        ]
        return LLMResponse(content=message.get("content", ""), tool_calls=tool_calls)

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to Ollama; a timed-out call is tried once more before giving up."""
        for attempt in range(1, self.attempts + 1):
            try:
                response = httpx.post(
                    f"{self.base_url}/api/chat", json=payload, timeout=self.timeout
                )
                response.raise_for_status()
                return response.json().get("message", {})
            except httpx.TimeoutException:
                if attempt == self.attempts:
                    raise
        raise AssertionError("unreachable")  # pragma: no cover


class FakeProvider(LLMProvider):
    """Returns pre-written responses in order. Used in tests and CI.

    It also records every conversation it receives, so tests can check what
    the agent actually sent to the model.
    """

    name = "fake"

    def __init__(self, responses: list[LLMResponse] | None = None):
        self.responses = list(responses or [])
        self.calls: list[list[Message]] = []
        self.requests: list[dict[str, Any]] = []  # tools and schema of each call

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls.append(list(messages))
        self.requests.append({"tools": tools, "response_schema": response_schema})
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(content="FakeProvider has no scripted responses left.")


class DemoProvider(LLMProvider):
    """A stand-in for a real model, used when LLM_PROVIDER=fake (e.g. in CI).

    Unlike FakeProvider it is stateless, so it can serve any number of
    investigations: it first asks for get_service_health, then answers with a
    valid report that quotes the tool result. This exercises the whole path
    (webhook, queue, loop, tool call, report, storage) without a model.
    """

    name = "fake"

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        tool_results = [m["content"] for m in messages if m["role"] == "tool"]
        if not tool_results:
            return LLMResponse(tool_calls=[ToolCall(name="get_service_health", arguments={})])
        report = {
            "summary": "Demo report from the fake LLM provider (no real analysis).",
            "root_cause_category": "unknown",
            "root_cause_explanation": "LLM_PROVIDER=fake: the report is scripted, not reasoned.",
            "evidence": [
                {"tool": "get_service_health", "query": "{}", "finding": tool_results[-1][:300]}
            ],
            "confidence": "low",
            "suggested_actions": ["Set LLM_PROVIDER=ollama to get a real investigation."],
        }
        return LLMResponse(content=json.dumps(report))


def get_provider(settings: Settings) -> LLMProvider:
    """Create the provider selected by the LLM_PROVIDER setting."""
    if settings.llm_provider == "ollama":
        return OllamaProvider(
            base_url=settings.ollama_url,
            model=settings.ollama_model,
            timeout=settings.ollama_timeout_seconds,
            think=settings.ollama_think,
            max_tokens=settings.ollama_max_tokens,
        )
    return DemoProvider()
