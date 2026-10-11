import json
from pathlib import Path

from fastapi.testclient import TestClient

from agent.config import Settings
from agent.llm import FakeProvider, LLMResponse, ToolCall
from agent.main import create_app
from agent.tools import Tool
from eval.harness import (
    Evaluator,
    RunResult,
    Scenario,
    is_correct,
    load_scenarios,
    render_markdown,
    summarize,
)

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "eval" / "scenarios"


class FakeEnvironment:
    """Simulates the stack: alerts fire depending on the injected fault."""

    def __init__(self, fault_shows_up=True, dirty_for=0):
        self.now = 0.0
        self.mode = "random"
        self.stopped: set[str] = set()
        self.fault_shows_up = fault_shows_up
        self.dirty_for = dirty_for  # seconds an old alert keeps firing
        self.actions: list[str] = []

    def ensure_vehicles(self, count):
        self.actions.append(f"vehicles:{count}")

    def set_simulator_mode(self, mode):
        self.mode = mode
        self.actions.append(f"mode:{mode}")

    def stop(self, service):
        self.stopped.add(service)
        self.actions.append(f"stop:{service}")

    def start(self, service):
        self.stopped.discard(service)
        self.actions.append(f"start:{service}")

    def firing_alerts(self):
        alerts = set()
        if self.now < self.dirty_for:
            alerts.add("HighAlertRate")
        if self.fault_shows_up:
            if "api" in self.stopped:
                alerts.add("FleetApiDown")
            if self.mode == "overheat":
                alerts.add("VehicleOverheating")
            if self.mode == "storm":
                alerts.add("HighAlertRate")
        return alerts

    def alert_labels(self, alert_name):
        if alert_name == "VehicleOverheating" and alert_name in self.firing_alerts():
            return {"alertname": alert_name, "vehicle_id": "1"}
        return {}

    def sleep(self, seconds):
        self.now += seconds


class FakeAgent:
    """Answers each alert with a fixed category."""

    def __init__(self, answers, status="done"):
        self.answers = answers
        self.status = status
        self.asked = []
        self.labels = []

    def info(self):
        return {"llm_provider": "fake"}

    def investigate(self, alert_name, labels):
        self.asked.append(alert_name)
        self.labels.append(labels)
        return len(self.asked)

    def wait_for_report(self, investigation_id, timeout):
        category, confidence = self.answers[self.asked[investigation_id - 1]]
        report = {
            "root_cause_category": category,
            "confidence": confidence,
            "steps_used": 3,
            "duration_seconds": 40.0,
            "stop_reason": "completed",
            "summary": "s",
        }
        return {"status": self.status, "report": report if self.status == "done" else None}


def evaluator(env, agent):
    return Evaluator(env, agent, poll_seconds=10, clock=lambda: env.now, log=lambda _: None)


# --- Scenario files ---


def test_real_scenario_files_are_valid():
    scenarios = load_scenarios(SCENARIOS_DIR)
    assert [s.name for s in scenarios] == ["api_down", "overheating", "alert_storm", "control"]
    categories = {s.expected_category for s in scenarios}
    assert categories == {"service_down", "sensor_anomaly", "alert_storm", "unknown"}
    assert all(s.simulator_mode in {"calm", "overheat", "storm"} for s in scenarios)


def test_is_correct():
    normal = Scenario(name="a", description="", alert="X", expected_category="service_down")
    control = Scenario(
        name="c", description="", alert="X", expected_category="unknown", accept_low_confidence=True
    )
    report = {"root_cause_category": "service_down", "confidence": "high"}
    assert is_correct(normal, report)
    assert not is_correct(control, report)
    assert is_correct(control, {"root_cause_category": "service_down", "confidence": "low"})
    assert not is_correct(normal, {"root_cause_category": "unknown", "confidence": "low"})


# --- Orchestration ---


def test_full_evaluation_with_perfect_agent():
    scenarios = load_scenarios(SCENARIOS_DIR)
    agent = FakeAgent(
        {
            "FleetApiDown": ("service_down", "high"),
            "VehicleOverheating": ("sensor_anomaly", "high"),
            "HighAlertRate": ("alert_storm", "medium"),
        }
    )
    env = FakeEnvironment()
    results = evaluator(env, agent).run(scenarios, runs=2)

    assert len(results) == 8
    # The control scenario asks about FleetApiDown on a healthy system; this
    # agent answers service_down with high confidence, which is wrong there.
    assert [r.correct for r in results] == [True, True, True, False] * 2
    assert all(r.status == "ok" and r.clean_start for r in results)
    # Alertmanager is paused during the evaluation and everything is restored
    assert env.actions[:2] == ["vehicles:3", "stop:alertmanager"]
    assert env.actions[-2:] == ["mode:random", "start:alertmanager"]
    assert "api" not in env.stopped
    # The firing alert's labels are passed on, as Alertmanager would do
    assert agent.labels[1] == {"alertname": "VehicleOverheating", "vehicle_id": "1"}


def test_fault_that_never_shows_up_is_not_scored():
    scenario = load_scenarios(SCENARIOS_DIR)[0]
    env = FakeEnvironment(fault_shows_up=False)
    agent = FakeAgent({"FleetApiDown": ("service_down", "high")})
    result = evaluator(env, agent).run_scenario(scenario, run=1)

    assert result.status == "injection_failed"
    assert result.correct is None
    assert agent.asked == []  # the agent was not even asked
    assert "api" not in env.stopped  # the fault is still undone


def test_missing_report_is_not_scored():
    scenario = load_scenarios(SCENARIOS_DIR)[0]
    agent = FakeAgent({"FleetApiDown": ("service_down", "high")}, status="failed")
    result = evaluator(FakeEnvironment(), agent).run_scenario(scenario, run=1)
    assert result.status == "agent_failed"
    assert result.correct is None


def test_dirty_start_is_recorded():
    scenario = load_scenarios(SCENARIOS_DIR)[1]
    env = FakeEnvironment(dirty_for=10_000)  # an old alert never clears
    agent = FakeAgent({"VehicleOverheating": ("sensor_anomaly", "high")})
    result = Evaluator(
        env, agent, poll_seconds=10, clean_timeout=60, clock=lambda: env.now, log=lambda _: None
    ).run_scenario(scenario, run=1)
    assert result.status == "ok"
    assert result.clean_start is False


# --- Reporting ---


def test_summary_and_markdown():
    scenarios = load_scenarios(SCENARIOS_DIR)[:2]
    results = [
        RunResult(
            "api_down", 1, "ok", True, "service_down", "high", True, 4, 80.0, "completed", "a|b"
        ),
        RunResult("api_down", 2, "ok", True, "unknown", "low", False, 2, 40.0, "completed", "x"),
        RunResult("overheating", 1, "injection_failed", True),
    ]
    rows = summarize(results, scenarios)
    assert rows[0]["accuracy"] == "50%"
    assert rows[0]["avg_steps"] == "3.0"
    assert rows[1]["accuracy"] == "n/a"
    assert rows[1]["not_scored"] == 1

    markdown = render_markdown(results, scenarios, {"Model": "qwen3:8b"})
    assert "**Overall: 1/2 correct** (50%)" in markdown
    assert "| Model | qwen3:8b |" in markdown
    assert "| api_down | service_down | 1/2 | 50% | 3.0 | 60.0 | 0 |" in markdown
    assert "a/b" in markdown  # pipes in summaries cannot break the table


# --- Harness against the real agent app with the FakeProvider (CI smoke test) ---


class InProcessAgent:
    """The real agent HTTP API (TestClient) with scripted model answers."""

    def __init__(self, tmp_path):
        report = {
            "summary": "API down",
            "root_cause_category": "service_down",
            "root_cause_explanation": "up == 0",
            "evidence": [],
            "confidence": "high",
            "suggested_actions": [],
        }
        script = [
            LLMResponse(tool_calls=[ToolCall("get_service_health", {})]),
            LLMResponse(content=json.dumps(report)),
        ]
        settings = Settings(agent_database_url=f"sqlite:///{tmp_path}/agent.db")
        app = create_app(settings, provider=FakeProvider(script), start_worker=False)
        app.state.service.investigator.tools = {
            "get_service_health": Tool("get_service_health", "h", {}, lambda: "API down")
        }
        self.client = TestClient(app)
        self.service = app.state.service

    def info(self):
        return self.client.get("/health").json()

    def investigate(self, alert_name, labels):
        response = self.client.post(
            "/investigate", json={"alert_name": alert_name, "labels": labels}
        )
        return response.json()["investigation_id"]

    def wait_for_report(self, investigation_id, timeout):
        self.service.process_next(timeout=1)
        return self.client.get(f"/reports/{investigation_id}").json()


def test_harness_with_real_agent_api_and_fake_provider(tmp_path):
    scenario = load_scenarios(SCENARIOS_DIR)[0]
    result = evaluator(FakeEnvironment(), InProcessAgent(tmp_path)).run_scenario(scenario, 1)
    assert result.status == "ok"
    assert result.category == "service_down"
    assert result.correct is True
    assert result.steps == 2
