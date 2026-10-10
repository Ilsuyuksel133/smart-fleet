"""LLM providers behind one small interface.

The agent loop only talks to ``LLMProvider.chat``. That makes it possible to
swap the real model (Ollama) for scripted answers (FakeProvider) in tests and
CI, where no model is available.
"""

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
    def chat(self, messages: list[Message], tools: list[ToolDefinition]) -> LLMResponse: ...


class OllamaProvider(LLMProvider):
    """Calls a local Ollama server through its HTTP chat API."""

    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float, think: bool = False):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.think = think

    def chat(self, messages: list[Message], tools: list[ToolDefinition]) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            # One complete answer instead of a token stream: simpler to handle
            "stream": False,
            # "Thinking" models (e.g. qwen3) can reason before answering;
            # slower but sometimes more accurate. Configurable via OLLAMA_THINK.
            "think": self.think,
        }
        response = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
        response.raise_for_status()
        message = response.json().get("message", {})

        tool_calls = [
            ToolCall(
                name=call["function"]["name"],
                arguments=call["function"].get("arguments") or {},
                id=call.get("id"),
            )
            for call in message.get("tool_calls") or []
        ]
        return LLMResponse(content=message.get("content", ""), tool_calls=tool_calls)


class FakeProvider(LLMProvider):
    """Returns pre-written responses in order. Used in tests and CI.

    It also records every conversation it receives, so tests can check what
    the agent actually sent to the model.
    """

    name = "fake"

    def __init__(self, responses: list[LLMResponse] | None = None):
        self.responses = list(responses or [])
        self.calls: list[list[Message]] = []

    def chat(self, messages: list[Message], tools: list[ToolDefinition]) -> LLMResponse:
        self.calls.append(list(messages))
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(content="FakeProvider has no scripted responses left.")


def get_provider(settings: Settings) -> LLMProvider:
    """Create the provider selected by the LLM_PROVIDER setting."""
    if settings.llm_provider == "ollama":
        return OllamaProvider(
            base_url=settings.ollama_url,
            model=settings.ollama_model,
            timeout=settings.ollama_timeout_seconds,
            think=settings.ollama_think,
        )
    return FakeProvider()
