import httpx
import pytest
import respx

from agent.config import Settings
from agent.llm import FakeProvider, LLMResponse, OllamaProvider, ToolCall, get_provider

OLLAMA = "http://ollama.test:11434"


def test_settings_defaults():
    settings = Settings()
    assert settings.llm_provider == "ollama"
    assert settings.ollama_url == "http://host.docker.internal:11434"
    assert settings.prometheus_url == "http://prometheus:9090"


def test_settings_can_be_overridden_by_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("OLLAMA_MODEL", "some-model:1b")
    settings = Settings()
    assert settings.llm_provider == "fake"
    assert settings.ollama_model == "some-model:1b"


def test_settings_reject_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(ValueError):
        Settings()


def test_get_provider_returns_selected_provider():
    assert isinstance(get_provider(Settings(llm_provider="fake")), FakeProvider)
    ollama = get_provider(Settings(llm_provider="ollama", ollama_model="m:1b"))
    assert isinstance(ollama, OllamaProvider)
    assert ollama.model == "m:1b"


def test_fake_provider_returns_scripted_responses_in_order():
    first = LLMResponse(tool_calls=[ToolCall(name="get_service_health", arguments={})])
    second = LLMResponse(content="done")
    fake = FakeProvider([first, second])

    assert fake.chat([{"role": "user", "content": "hi"}], tools=[]) is first
    assert fake.chat([{"role": "user", "content": "again"}], tools=[]) is second
    assert "no scripted responses" in fake.chat([], tools=[]).content
    assert len(fake.calls) == 3
    assert fake.calls[0][0]["content"] == "hi"


def test_response_as_message_includes_tool_calls():
    response = LLMResponse(tool_calls=[ToolCall(name="query_loki", arguments={"limit": 5})])
    message = response.as_message()
    assert message["role"] == "assistant"
    assert message["tool_calls"] == [
        {"function": {"name": "query_loki", "arguments": {"limit": 5}}}
    ]
    assert "tool_calls" not in LLMResponse(content="final").as_message()


@respx.mock
def test_ollama_provider_parses_tool_calls():
    route = respx.post(f"{OLLAMA}/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "query_prometheus", "arguments": {"promql": "up"}}}
                    ],
                }
            },
        )
    )
    provider = OllamaProvider(base_url=OLLAMA + "/", model="m:1b", timeout=5)
    tools = [{"type": "function", "function": {"name": "query_prometheus"}}]

    response = provider.chat([{"role": "user", "content": "check"}], tools=tools)

    assert response.tool_calls == [ToolCall(name="query_prometheus", arguments={"promql": "up"})]
    sent = route.calls.last.request
    body = httpx.Response(200, content=sent.content).json()
    assert body["model"] == "m:1b"
    assert body["stream"] is False
    assert body["tools"] == tools


@respx.mock
def test_ollama_provider_parses_final_answer():
    respx.post(f"{OLLAMA}/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": "final answer"}})
    )
    response = OllamaProvider(OLLAMA, "m:1b", 5).chat([], tools=[])
    assert response.content == "final answer"
    assert response.tool_calls == []


@respx.mock
def test_ollama_provider_raises_on_http_error():
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        OllamaProvider(OLLAMA, "m:1b", 5).chat([], tools=[])


def test_response_as_message_keeps_tool_call_id():
    response = LLMResponse(tool_calls=[ToolCall(name="get_runbook", arguments={}, id="call_1")])
    assert response.as_message()["tool_calls"][0]["id"] == "call_1"


@respx.mock
def test_ollama_provider_passes_think_flag_and_reads_call_id():
    route = respx.post(f"{OLLAMA}/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {
                    "content": "",
                    "tool_calls": [{"id": "call_9", "function": {"name": "x", "arguments": {}}}],
                }
            },
        )
    )
    response = OllamaProvider(OLLAMA, "m:1b", 5, think=True).chat([], tools=[])
    assert response.tool_calls[0].id == "call_9"
    body = httpx.Response(200, content=route.calls.last.request.content).json()
    assert body["think"] is True
