import json
import logging

import pytest

from agent.config import Settings
from agent.llm import FakeProvider, LLMProvider, LLMResponse, OllamaProvider, ToolCall
from agent.logging_config import JsonFormatter
from agent.loop import DUPLICATE_CALL_MESSAGE, Investigator, create_investigator
from agent.report import Alert, RootCauseCategory, parse_model_report
from agent.tools import Tool

ALERT = Alert(name="FleetApiDown", labels={"severity": "critical"})

VALID_REPORT = {
    "summary": "The API container is down.",
    "root_cause_category": "service_down",
    "root_cause_explanation": "Prometheus reports up == 0 for fleet-api.",
    "evidence": [{"tool": "get_service_health", "query": "{}", "finding": "API unreachable"}],
    "confidence": "high",
    "suggested_actions": ["Runbook FleetApiDown: docker compose up -d api"],
}


def final(report=None, wrap=False):
    text = json.dumps(report or VALID_REPORT)
    return LLMResponse(content=f"Here is the report:\n```json\n{text}\n```" if wrap else text)


def call(name, call_id=None, **arguments):
    return LLMResponse(tool_calls=[ToolCall(name=name, arguments=arguments, id=call_id)])


@pytest.fixture
def tools():
    """Tools that return canned text and count how often they ran."""
    counter = {"health": 0}

    def health():
        counter["health"] += 1
        return "API /health: ERROR: could not connect (ConnectError)"

    def failing(promql, minutes=15):
        raise RuntimeError("prometheus exploded")

    registry = {
        "get_service_health": Tool("get_service_health", "health", {}, health),
        "get_runbook": Tool("get_runbook", "runbook", {}, lambda alert_name: "## FleetApiDown"),
        "query_prometheus": Tool("query_prometheus", "prom", {}, failing),
    }
    registry["counter"] = counter
    return registry


def investigator(provider, tools, **kwargs):
    counter = tools.pop("counter")
    agent = Investigator(provider, tools, **kwargs)
    agent.counter = counter
    return agent


# --- Scenarios ---


def test_answer_without_tools_is_sent_back_for_evidence(tools):
    # The model answers immediately, is asked to use tools, then does so
    fake = FakeProvider([final(), call("get_service_health"), final()])
    report = investigator(fake, tools).investigate(ALERT)

    assert report.root_cause_category == RootCauseCategory.service_down
    assert report.confidence == "high"
    assert report.alert_name == "FleetApiDown"
    assert report.steps_used == 3
    assert report.stop_reason == "completed"
    nudge = fake.calls[1][-1]
    assert nudge["role"] == "user"
    assert "not used any tool" in nudge["content"]
    # The model received the system prompt, the alert and the tool definitions
    first_call = fake.calls[0]
    assert first_call[0]["role"] == "system"
    assert "FleetApiDown" in first_call[1]["content"]
    assert '"severity": "critical"' in first_call[1]["content"]


def test_answer_without_any_evidence_gets_low_confidence(tools):
    # The model ignores the request for evidence: the answer is kept, confidence is capped
    fake = FakeProvider([final(), final()])
    report = investigator(fake, tools).investigate(ALERT)

    assert report.stop_reason == "completed"
    assert report.root_cause_category == RootCauseCategory.service_down
    assert report.confidence == "low"
    assert report.steps_used == 2


def test_multi_step_tool_use(tools):
    fake = FakeProvider(
        [
            call("get_runbook", call_id="c1", alert_name="FleetApiDown"),
            call("get_service_health", call_id="c2"),
            final(wrap=True),
        ]
    )
    agent = investigator(fake, tools)
    report = agent.investigate(ALERT)

    assert report.stop_reason == "completed"
    assert report.steps_used == 3
    assert agent.counter["health"] == 1
    # Before the final answer the model saw both tool results, linked to their calls
    history = fake.calls[2]
    tool_messages = [m for m in history if m["role"] == "tool"]
    assert [m["tool_name"] for m in tool_messages] == ["get_runbook", "get_service_health"]
    assert [m["tool_call_id"] for m in tool_messages] == ["c1", "c2"]
    assert tool_messages[1]["content"].startswith("API /health: ERROR")
    # ...and its own earlier tool requests
    assistant = [m for m in history if m["role"] == "assistant"]
    assert assistant[0]["tool_calls"][0]["function"]["name"] == "get_runbook"


def test_several_tool_calls_in_one_step(tools):
    both = LLMResponse(
        tool_calls=[
            ToolCall("get_runbook", {"alert_name": "FleetApiDown"}),
            ToolCall("get_service_health", {}),
        ]
    )
    fake = FakeProvider([both, final()])
    report = investigator(fake, tools).investigate(ALERT)
    assert report.steps_used == 2
    assert len([m for m in fake.calls[1] if m["role"] == "tool"]) == 2


def test_step_limit(tools):
    # The model keeps asking for different data and never answers
    responses = [call("get_runbook", alert_name=f"Alert{i}") for i in range(10)]
    fake = FakeProvider(responses)
    report = investigator(fake, tools, max_steps=3).investigate(ALERT)

    assert len(fake.calls) == 3
    assert report.stop_reason == "max_steps"
    assert report.root_cause_category == RootCauseCategory.unknown
    assert report.confidence == "low"
    assert report.steps_used == 3
    # The tool results collected so far are kept as evidence for a human
    assert [e.tool for e in report.evidence] == ["get_runbook"] * 3


def test_invalid_json_is_retried_once(tools):
    fake = FakeProvider(
        [call("get_service_health"), LLMResponse(content="The API is down, I think."), final()]
    )
    report = investigator(fake, tools).investigate(ALERT)

    assert report.stop_reason == "completed"
    assert report.confidence == "high"
    assert report.steps_used == 3
    fix_request = fake.calls[2][-1]
    assert fix_request["role"] == "user"
    assert "could not be used" in fix_request["content"]


def test_invalid_category_is_retried(tools):
    wrong = dict(VALID_REPORT, root_cause_category="disk_full")
    fake = FakeProvider([call("get_service_health"), final(wrong), final()])
    report = investigator(fake, tools).investigate(ALERT)
    assert report.root_cause_category == RootCauseCategory.service_down
    assert "root_cause_category" in fake.calls[2][-1]["content"]


def test_invalid_json_twice_gives_unknown_report(tools):
    fake = FakeProvider(
        [
            call("get_service_health"),
            LLMResponse(content="{not json"),
            LLMResponse(content="still no"),
        ]
    )
    report = investigator(fake, tools).investigate(ALERT)

    assert report.stop_reason == "invalid_output"
    assert report.root_cause_category == RootCauseCategory.unknown
    assert report.steps_used == 3
    # Evidence from the tools is kept even though the model failed
    assert [e.tool for e in report.evidence] == ["get_service_health"]


def test_tool_error_does_not_break_the_loop(tools):
    fake = FakeProvider([call("query_prometheus", promql="up"), final()])
    report = investigator(fake, tools).investigate(ALERT)

    assert report.stop_reason == "completed"
    tool_message = [m for m in fake.calls[1] if m["role"] == "tool"][0]
    assert tool_message["content"] == (
        "ERROR: query_prometheus failed: RuntimeError: prometheus exploded"
    )


def test_unknown_tool_is_reported_to_the_model(tools):
    fake = FakeProvider([call("restart_container", container="api"), final()])
    investigator(fake, tools).investigate(ALERT)
    tool_message = [m for m in fake.calls[1] if m["role"] == "tool"][0]
    assert tool_message["content"].startswith("ERROR: unknown tool 'restart_container'")


def test_duplicate_call_is_not_executed_again(tools):
    fake = FakeProvider(
        [call("get_service_health"), call("get_service_health"), final()],
    )
    agent = investigator(fake, tools)
    report = agent.investigate(ALERT)

    assert agent.counter["health"] == 1
    tool_messages = [m for m in fake.calls[2] if m["role"] == "tool"]
    assert tool_messages[1]["content"] == DUPLICATE_CALL_MESSAGE
    assert report.stop_reason == "completed"


def test_same_arguments_in_different_order_count_as_duplicate(tools):
    tools["query_loki"] = Tool("query_loki", "loki", {}, lambda logql, limit=20: "lines")
    fake = FakeProvider(
        [
            LLMResponse(tool_calls=[ToolCall("query_loki", {"logql": "x", "limit": 5})]),
            LLMResponse(tool_calls=[ToolCall("query_loki", {"limit": 5, "logql": "x"})]),
            final(),
        ]
    )
    investigator(fake, tools).investigate(ALERT)
    assert [m for m in fake.calls[2] if m["role"] == "tool"][1]["content"] == (
        DUPLICATE_CALL_MESSAGE
    )


def test_time_limit(tools):
    # Every clock() call advances 100 s, like a very slow model
    ticks = iter(range(0, 10_000, 100))
    fake = FakeProvider([call("get_runbook", alert_name=f"A{i}") for i in range(10)])
    agent = investigator(fake, tools, max_seconds=250, clock=lambda: next(ticks))
    report = agent.investigate(ALERT)

    assert report.stop_reason == "timeout"
    assert report.root_cause_category == RootCauseCategory.unknown
    assert len(fake.calls) < 10


class BrokenProvider(LLMProvider):
    name = "broken"

    def chat(self, messages, tools):
        raise ConnectionError("ollama is not running")


def test_llm_error_gives_unknown_report(tools):
    report = investigator(BrokenProvider(), tools).investigate(ALERT)
    assert report.stop_reason == "llm_error"
    assert report.root_cause_category == RootCauseCategory.unknown
    assert report.evidence == []


def test_every_step_is_logged_as_json(tools, caplog):
    caplog.set_level(logging.INFO, logger="fleet-agent")
    fake = FakeProvider([call("get_service_health"), final()])
    investigator(fake, tools).investigate(ALERT)

    entries = [json.loads(JsonFormatter().format(r)) for r in caplog.records]
    messages = [e["message"] for e in entries]
    assert messages == [
        "investigation started",
        "llm call",
        "tool call",
        "llm call",
        "investigation finished",
    ]
    tool_entry = entries[2]
    assert tool_entry["tool"] == "get_service_health"
    assert tool_entry["arguments"] == {}
    assert tool_entry["result_preview"].startswith("API /health")
    assert "duration_ms" in tool_entry
    assert entries[-1]["category"] == "service_down"
    assert entries[-1]["stop_reason"] == "completed"


# --- Report parsing ---


def test_parse_model_report_accepts_fenced_json():
    report = parse_model_report("```json\n" + json.dumps(VALID_REPORT) + "\n```")
    assert report.summary == VALID_REPORT["summary"]


def test_parse_model_report_rejects_missing_json():
    with pytest.raises(ValueError, match="no JSON object"):
        parse_model_report("I could not find anything.")


def test_parse_model_report_rejects_missing_fields():
    with pytest.raises(ValueError):
        parse_model_report('{"summary": "only this"}')


def test_create_investigator_uses_settings():
    agent = create_investigator(Settings(llm_provider="ollama", agent_max_steps=5))
    assert isinstance(agent.provider, OllamaProvider)
    assert agent.max_steps == 5
    assert "query_loki" in agent.tools
