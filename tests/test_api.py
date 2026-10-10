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
    assert "Yüksek sıcaklık" in reasons[0]


def test_abnormal_status_creates_alert_and_updates_vehicle(client, vehicle_id):
    client.post(f"/vehicles/{vehicle_id}/data", json={"temperature": 70, "status": "ERROR"})
    reasons = alert_reasons(client)
    assert len(reasons) == 1
    assert "Anormal durum" in reasons[0]
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
