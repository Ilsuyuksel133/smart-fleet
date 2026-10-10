import json

import httpx
import respx

from eval import run_eval
from eval.harness import RunResult

PROM = "http://prom.test"
AGENT = "http://agent.test"
API = "http://api.test"


@respx.mock
def test_ensure_vehicles_creates_only_missing_ones():
    respx.get(f"{API}/vehicles").mock(return_value=httpx.Response(200, json=[{"id": 1}]))
    create = respx.post(f"{API}/vehicles").mock(return_value=httpx.Response(200, json={}))
    run_eval.DockerEnvironment(PROM, API).ensure_vehicles(3)
    names = [json.loads(call.request.content)["name"] for call in create.calls]
    assert names == ["eval-vehicle-2", "eval-vehicle-3"]


def test_docker_environment_runs_compose_commands(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs["env"].get("SIMULATOR_MODE"), kwargs["cwd"]))

    monkeypatch.setattr(run_eval.subprocess, "run", fake_run)
    env = run_eval.DockerEnvironment(PROM, API)
    env.set_simulator_mode("storm")
    env.stop("api")
    env.start("api")

    assert calls[0][0] == [
        "docker",
        "compose",
        "up",
        "-d",
        "--no-deps",
        "--force-recreate",
        "simulator",
    ]
    assert calls[0][1] == "storm"
    assert calls[0][2] == run_eval.ROOT
    assert [c[0][2:] for c in calls[1:]] == [["stop", "api"], ["start", "api"]]


@respx.mock
def test_firing_alerts_and_their_common_labels():
    respx.get(f"{PROM}/api/v1/alerts").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "alerts": [
                        {"labels": {"alertname": "FleetApiDown"}, "state": "firing"},
                        {"labels": {"alertname": "HighAlertRate"}, "state": "pending"},
                        {
                            "labels": {"alertname": "VehicleOverheating", "vehicle_id": "1"},
                            "state": "firing",
                        },
                        {
                            "labels": {"alertname": "VehicleOverheating", "vehicle_id": "2"},
                            "state": "firing",
                        },
                    ]
                }
            },
        )
    )
    env = run_eval.DockerEnvironment(PROM, API)
    assert env.firing_alerts() == {"FleetApiDown", "VehicleOverheating"}
    # Two vehicles: only the shared label is kept, like Alertmanager's commonLabels
    assert env.alert_labels("VehicleOverheating") == {"alertname": "VehicleOverheating"}
    assert env.alert_labels("HighAlertRate") == {}


@respx.mock
def test_http_agent_client(monkeypatch):
    monkeypatch.setattr(run_eval.time, "sleep", lambda _: None)
    respx.get(f"{AGENT}/health").mock(
        return_value=httpx.Response(200, json={"llm_provider": "ollama", "llm_model": "m"})
    )
    investigate = respx.post(f"{AGENT}/investigate").mock(
        return_value=httpx.Response(202, json={"investigation_id": 7})
    )
    respx.get(f"{AGENT}/reports/7").mock(
        side_effect=[
            httpx.Response(200, json={"status": "running"}),
            httpx.Response(200, json={"status": "done", "report": {}}),
        ]
    )
    client = run_eval.HttpAgentClient(AGENT)
    assert client.info()["llm_model"] == "m"
    assert client.investigate("FleetApiDown", {"job": "fleet-api"}) == 7
    sent = json.loads(investigate.calls.last.request.content)
    assert sent == {"alert_name": "FleetApiDown", "labels": {"job": "fleet-api"}}
    assert client.wait_for_report(7, timeout=60)["status"] == "done"


def test_main_writes_markdown_and_json(tmp_path, monkeypatch):
    class StubAgent:
        def __init__(self, url):
            pass

        def info(self):
            return {"llm_provider": "fake", "llm_model": None}

    class StubEvaluator:
        def __init__(self, env, agent):
            pass

        def run(self, scenarios, runs):
            assert [s.name for s in scenarios] == ["api_down"]
            assert runs == 1
            return [
                RunResult(
                    "api_down",
                    1,
                    "ok",
                    True,
                    "service_down",
                    "high",
                    True,
                    3,
                    50.0,
                    "completed",
                    "s",
                )
            ]

    monkeypatch.setattr(run_eval, "HttpAgentClient", StubAgent)
    monkeypatch.setattr(run_eval, "Evaluator", StubEvaluator)
    output = tmp_path / "results.md"

    assert run_eval.main(["--runs", "1", "--only", "api_down", "--output", str(output)]) == 0
    assert "**Overall: 1/1 correct** (100%)" in output.read_text()
    data = json.loads(output.with_suffix(".json").read_text())
    assert data["metadata"]["LLM provider"] == "fake"
    assert data["results"][0]["category"] == "service_down"
