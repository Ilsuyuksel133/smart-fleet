from datetime import UTC, datetime, timedelta

from models import Alert, SensorLog


def alert_reasons(client):
    return [a["reason"] for a in client.get("/alerts").json()]


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


def test_add_vehicle(client):
    response = client.post("/vehicles", json={"name": "Truck-1"})
    assert response.status_code == 200
    body = response.json()
    assert "id" in body
    assert body["name"] == "Truck-1"
    assert body["status"] == "OK"


def test_normal_data_creates_no_alert(client, vehicle_id):
    response = client.post(f"/vehicles/{vehicle_id}/data", json={"temperature": 70, "status": "OK"})
    assert response.status_code == 200
    assert alert_reasons(client) == []


def test_high_temperature_creates_alert(client, vehicle_id):
    client.post(f"/vehicles/{vehicle_id}/data", json={"temperature": 95, "status": "OK"})
    reasons = alert_reasons(client)
    assert len(reasons) == 1
    assert "High temperature" in reasons[0]


def test_abnormal_status_creates_alert_and_updates_vehicle(client, vehicle_id):
    client.post(f"/vehicles/{vehicle_id}/data", json={"temperature": 70, "status": "ERROR"})
    reasons = alert_reasons(client)
    assert len(reasons) == 1
    assert "Abnormal status" in reasons[0]
    assert client.get("/vehicles").json()[0]["status"] == "ERROR"


def test_data_for_unknown_vehicle_returns_404(client):
    response = client.post("/vehicles/999/data", json={"temperature": 70, "status": "OK"})
    assert response.status_code == 404


def test_vehicle_status_returns_logs(client, vehicle_id):
    client.post(f"/vehicles/{vehicle_id}/data", json={"temperature": 70, "status": "OK"})
    body = client.get(f"/vehicles/{vehicle_id}/status").json()
    assert body["vehicle_id"] == vehicle_id
    assert len(body["logs"]) == 1


def test_metrics_exposes_alert_counter(client, vehicle_id):
    client.post(f"/vehicles/{vehicle_id}/data", json={"temperature": 95, "status": "OK"})
    response = client.get("/metrics")
    assert response.status_code == 200
    assert 'fleet_alerts_total{type="high_temperature"}' in response.text
    assert 'path="/vehicles/{vehicle_id}/data"' in response.text


# --- Helpers for the query and statistics tests ---


def send(client, vehicle_id, temperature, status="OK"):
    response = client.post(
        f"/vehicles/{vehicle_id}/data", json={"temperature": temperature, "status": status}
    )
    assert response.status_code == 200


def minutes_ago(minutes):
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=minutes)


# --- /alerts ---


def test_alerts_have_a_type_and_are_newest_first(client, vehicle_id):
    send(client, vehicle_id, 95)  # alert 1: high_temperature
    send(client, vehicle_id, 70, "ERROR")  # alert 2: abnormal_status
    alerts = client.get("/alerts").json()
    assert [a["type"] for a in alerts] == ["abnormal_status", "high_temperature"]
    assert alerts[0]["id"] > alerts[1]["id"]


def test_alerts_filter_by_type_vehicle_and_limit(client, vehicle_id):
    other = client.post("/vehicles", json={"name": "Truck-2"}).json()["id"]
    send(client, vehicle_id, 95)
    send(client, vehicle_id, 96)
    send(client, other, 70, "ERROR")

    by_type = client.get("/alerts", params={"type": "abnormal_status"}).json()
    assert [a["vehicle_id"] for a in by_type] == [other]

    by_vehicle = client.get("/alerts", params={"vehicle_id": vehicle_id}).json()
    assert len(by_vehicle) == 2
    assert {a["type"] for a in by_vehicle} == {"high_temperature"}

    limited = client.get("/alerts", params={"limit": 1}).json()
    assert len(limited) == 1
    assert limited[0]["vehicle_id"] == other  # the newest one


def test_alerts_reject_invalid_parameters(client):
    assert client.get("/alerts", params={"type": "disk_full"}).status_code == 422
    assert client.get("/alerts", params={"limit": 0}).status_code == 422
    assert client.get("/alerts", params={"limit": 1001}).status_code == 422


# --- /vehicles/{id}/status ---


def test_vehicle_status_unknown_vehicle_returns_404(client):
    response = client.get("/vehicles/999/status")
    assert response.status_code == 404
    assert response.json()["detail"] == "Vehicle not found"


def test_vehicle_status_returns_newest_readings_oldest_first(client, vehicle_id):
    for temperature in [61, 62, 63, 64]:
        send(client, vehicle_id, temperature)
    logs = client.get(f"/vehicles/{vehicle_id}/status", params={"limit": 2}).json()["logs"]
    assert [log["temperature"] for log in logs] == [63, 64]


# --- /stats ---


def test_stats_counts_and_averages_within_the_window(client, session_factory, vehicle_id):
    other = client.post("/vehicles", json={"name": "Truck-2"}).json()["id"]
    idle = client.post("/vehicles", json={"name": "Van-1"}).json()["id"]
    send(client, vehicle_id, 70)
    send(client, vehicle_id, 90)  # high_temperature alert
    send(client, other, 60, "ERROR")  # abnormal_status alert, vehicle not OK

    # Old rows outside the 15-minute window must not be counted
    with session_factory() as db:
        db.add(
            SensorLog(
                vehicle_id=vehicle_id, temperature=200, status="OK", timestamp=minutes_ago(30)
            )
        )
        db.add(SensorLog(vehicle_id=idle, temperature=99, status="OK", timestamp=minutes_ago(30)))
        db.add(
            Alert(
                vehicle_id=vehicle_id,
                type="high_temperature",
                reason="old",
                timestamp=minutes_ago(30),
            )
        )
        db.commit()

    stats = client.get("/stats", params={"minutes": 15}).json()

    assert stats["window_minutes"] == 15
    assert stats["vehicles_total"] == 3
    assert stats["vehicles_not_ok"] == 1
    assert stats["alerts_by_type"] == {"high_temperature": 1, "abnormal_status": 1}
    assert stats["per_vehicle"] == [
        {"vehicle_id": vehicle_id, "name": "Truck-1", "readings": 2,
         "avg_temperature": 80.0, "max_temperature": 90.0},
        {"vehicle_id": other, "name": "Truck-2", "readings": 1,
         "avg_temperature": 60.0, "max_temperature": 60.0},
    ]  # fmt: skip


def test_stats_on_an_empty_database(client):
    stats = client.get("/stats").json()
    assert stats == {
        "window_minutes": 15,
        "vehicles_total": 0,
        "vehicles_not_ok": 0,
        "alerts_by_type": {"high_temperature": 0, "abnormal_status": 0},
        "per_vehicle": [],
    }


def test_stats_rejects_invalid_window(client):
    assert client.get("/stats", params={"minutes": 0}).status_code == 422


# --- OpenAPI ---


def test_openapi_documents_the_response_schemas(client):
    spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    for name in ["VehicleOut", "AlertOut", "SensorLogOut", "VehicleStatusOut", "StatsOut"]:
        assert name in schemas
    assert schemas["AlertOut"]["properties"]["type"]["enum"] == [
        "high_temperature",
        "abnormal_status",
    ]
    alert_params = {p["name"] for p in spec["paths"]["/alerts"]["get"]["parameters"]}
    assert alert_params == {"limit", "vehicle_id", "type"}
