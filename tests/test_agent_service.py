import json

import pytest
from fastapi.testclient import TestClient

from agent.config import Settings
from agent.llm import FakeProvider, LLMResponse, ToolCall
from agent.loop import Investigator
from agent.main import alerts_from_webhook, create_app
from agent.report import Alert
from agent.service import InvestigationService
from agent.storage import ReportStore
from agent.tools import Tool

REPORT = {
    "summary": "API down",
    "root_cause_category": "service_down",
    "root_cause_explanation": "up == 0",
    "evidence": [{"tool": "get_service_health", "query": "{}", "finding": "down"}],
    "confidence": "high",
    "suggested_actions": ["Runbook FleetApiDown: restart the api container"],
}


def scripted_investigation():
    """One tool call followed by a valid report."""
    return [
        LLMResponse(tool_calls=[ToolCall("get_service_health", {})]),
        LLMResponse(content=json.dumps(REPORT)),
    ]


@pytest.fixture
def store(tmp_path):
    return ReportStore(f"sqlite:///{tmp_path}/agent.db")


def make_service(store, responses, clock=lambda: 0.0, cooldown=900.0):
    tools = {"get_service_health": Tool("get_service_health", "h", {}, lambda: "down")}
    investigator = Investigator(FakeProvider(responses), tools)
    return InvestigationService(store, investigator, cooldown_seconds=cooldown, clock=clock)


# --- InvestigationService ---


def test_submit_and_process_stores_the_report(store):
    service = make_service(store, scripted_investigation())
    result = service.submit(Alert(name="FleetApiDown"), trigger="manual")

    assert result.accepted
    assert store.get(result.investigation_id).status == "queued"

    assert service.process_next(timeout=1) is True
    row = store.get(result.investigation_id)
    assert row.status == "done"
    assert row.category == "service_down"
    assert row.confidence == "high"
    assert row.finished_at is not None
    assert row.to_dict(include_report=True)["report"]["steps_used"] == 2


def test_same_alert_is_not_queued_twice(store):
    service = make_service(store, scripted_investigation())
    assert service.submit(Alert(name="FleetApiDown"), trigger="alertmanager").accepted
    second = service.submit(Alert(name="FleetApiDown"), trigger="alertmanager")
    assert not second.accepted
    assert second.reason == "already queued or running"
    # A different alert is still accepted
    assert service.submit(Alert(name="HighAlertRate"), trigger="alertmanager").accepted


def test_cooldown_after_investigation(store):
    now = {"t": 0.0}
    service = make_service(
        store, scripted_investigation() * 2, clock=lambda: now["t"], cooldown=600
    )
    service.submit(Alert(name="HighAlertRate"), trigger="alertmanager")
    service.process_next(timeout=1)

    now["t"] = 300
    skipped = service.submit(Alert(name="HighAlertRate"), trigger="alertmanager")
    assert not skipped.accepted
    assert skipped.reason == "cooldown (300 s left)"

    # A manual request ignores the cooldown
    assert service.submit(Alert(name="HighAlertRate"), "manual", respect_cooldown=False).accepted


def test_cooldown_expires(store):
    now = {"t": 0.0}
    service = make_service(
        store, scripted_investigation() * 2, clock=lambda: now["t"], cooldown=600
    )
    service.submit(Alert(name="HighAlertRate"), trigger="alertmanager")
    service.process_next(timeout=1)
    now["t"] = 601
    assert service.submit(Alert(name="HighAlertRate"), trigger="alertmanager").accepted


def test_failure_is_stored_and_alert_released(store, monkeypatch):
    service = make_service(store, scripted_investigation())
    result = service.submit(Alert(name="FleetApiDown"), trigger="manual")

    def broken_save(*args):
        raise OSError("disk full")

    monkeypatch.setattr(store, "save_report", broken_save)
    service.process_next(timeout=1)

    row = store.get(result.investigation_id)
    assert row.status == "failed"
    assert row.error == "OSError: disk full"
    assert "FleetApiDown" not in service.active


def test_process_next_with_empty_queue(store):
    assert make_service(store, []).process_next(timeout=0.01) is False


def test_worker_thread_processes_queue(store):
    service = make_service(store, scripted_investigation())
    result = service.submit(Alert(name="FleetApiDown"), trigger="manual")
    thread = service.start_worker()
    service.queue.join()  # wait until the worker finished the job
    assert thread.daemon
    assert store.get(result.investigation_id).status == "done"


def test_latest_returns_newest_first(store):
    for name in ["A", "B", "C"]:
        store.create(Alert(name=name), trigger="manual")
    assert [row.alert_name for row in store.latest(limit=2)] == ["C", "B"]


# --- Alertmanager payload ---


def webhook_payload(*alerts):
    return {"status": "firing", "alerts": list(alerts)}


def am_alert(name, status="firing", **labels):
    return {
        "status": status,
        "labels": {"alertname": name, "severity": "warning", **labels},
        "annotations": {"summary": f"{name} summary"},
    }


def test_alerts_from_webhook_groups_by_name_and_ignores_resolved():
    payload = webhook_payload(
        am_alert("VehicleOverheating", vehicle_id="3"),
        am_alert("VehicleOverheating", vehicle_id="4"),
        am_alert("HighAlertRate"),
        am_alert("FleetApiDown", status="resolved"),
    )
    alerts = {alert.name: alert for alert in alerts_from_webhook(payload)}

    assert set(alerts) == {"VehicleOverheating", "HighAlertRate"}
    overheating = alerts["VehicleOverheating"]
    assert overheating.labels == {"alertname": "VehicleOverheating", "severity": "warning"}
    assert overheating.annotations["firing_instances"] == "2"
    assert overheating.annotations["instance_labels"] == "vehicle_id=3, vehicle_id=4"
    assert "firing_instances" not in alerts["HighAlertRate"].annotations


def test_alerts_from_empty_webhook():
    assert alerts_from_webhook({}) == []


# --- HTTP API ---


@pytest.fixture
def client(tmp_path):
    settings = Settings(agent_database_url=f"sqlite:///{tmp_path}/agent.db")
    app = create_app(settings, provider=FakeProvider(scripted_investigation()), start_worker=False)
    # Real tools would call Prometheus/Loki; replace them with a canned one
    service = app.state.service
    service.investigator.tools = {
        "get_service_health": Tool("get_service_health", "h", {}, lambda: "down")
    }
    with TestClient(app) as test_client:
        test_client.service = service
        yield test_client


def test_webhook_accepts_and_returns_202(client):
    response = client.post("/webhook/alertmanager", json=webhook_payload(am_alert("FleetApiDown")))
    assert response.status_code == 202
    body = response.json()
    assert body["accepted"][0]["alert_name"] == "FleetApiDown"
    assert body["skipped"] == []

    # Same alert again while the first is still queued: skipped
    again = client.post("/webhook/alertmanager", json=webhook_payload(am_alert("FleetApiDown")))
    assert again.json()["skipped"] == [
        {"alert_name": "FleetApiDown", "reason": "already queued or running"}
    ]


def test_full_flow_webhook_to_report(client):
    client.post("/webhook/alertmanager", json=webhook_payload(am_alert("FleetApiDown")))
    client.service.process_next(timeout=1)

    reports = client.get("/reports").json()
    assert reports[0]["alert_name"] == "FleetApiDown"
    assert reports[0]["status"] == "done"
    assert reports[0]["category"] == "service_down"
    assert reports[0]["trigger"] == "alertmanager"

    detail = client.get(f"/reports/{reports[0]['id']}").json()
    assert detail["report"]["suggested_actions"] == REPORT["suggested_actions"]
    assert detail["alert"]["labels"]["severity"] == "warning"

    metrics = client.get("/metrics").text
    assert 'agent_investigations_total{category="service_down"}' in metrics
    assert 'agent_tool_calls_total{tool="get_service_health"}' in metrics
    assert "agent_steps_per_investigation_bucket" in metrics
    assert "agent_investigation_duration_seconds_bucket" in metrics


def test_manual_investigation(client):
    response = client.post("/investigate", json={"alert_name": "HighAlertRate"})
    assert response.status_code == 202
    assert response.json()["investigation_id"] is not None

    conflict = client.post("/investigate", json={"alert_name": "HighAlertRate"})
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "already queued or running"


def test_report_not_found(client):
    assert client.get("/reports/999").status_code == 404


def test_queued_report_has_no_report_yet(client):
    investigation_id = client.post("/investigate", json={"alert_name": "X"}).json()[
        "investigation_id"
    ]
    detail = client.get(f"/reports/{investigation_id}").json()
    assert detail["status"] == "queued"
    assert detail["report"] is None


def test_metrics_series_exist_before_the_first_investigation(client):
    # Without this, increase() in Grafana would miss the first investigation
    metrics = client.get("/metrics").text
    for category in ["service_down", "sensor_anomaly", "alert_storm", "unknown"]:
        assert f'agent_investigations_total{{category="{category}"}}' in metrics
    for tool in ["query_prometheus", "query_loki", "get_runbook", "get_service_health"]:
        assert f'agent_tool_calls_total{{tool="{tool}"}}' in metrics


def test_skipped_investigation_is_logged(store, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="fleet-agent")
    service = make_service(store, scripted_investigation())
    service.submit(Alert(name="FleetApiDown"), trigger="alertmanager")
    service.submit(Alert(name="FleetApiDown"), trigger="alertmanager")
    skipped = [r for r in caplog.records if r.getMessage() == "investigation skipped"]
    assert len(skipped) == 1
    assert skipped[0].reason == "already queued or running"
