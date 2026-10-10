import json
import logging

from logging_config import JsonFormatter, setup_logging


def formatted(record):
    """Format the record with the app's formatter and parse it as JSON."""
    return json.loads(JsonFormatter().format(record))


def test_request_log_is_json_with_expected_fields(client, caplog):
    caplog.set_level(logging.INFO, logger="fleet-api")
    client.get("/vehicles")

    records = [r for r in caplog.records if r.getMessage() == "request"]
    assert records, "middleware should log one line per request"

    entry = formatted(records[-1])
    assert entry["level"] == "info"
    assert entry["logger"] == "fleet-api"
    assert entry["message"] == "request"
    assert "timestamp" in entry
    assert entry["method"] == "GET"
    assert entry["path"] == "/vehicles"
    assert entry["status"] == 200
    assert isinstance(entry["duration_ms"], float)


def test_request_log_uses_route_template(client, caplog, vehicle_id):
    caplog.set_level(logging.INFO, logger="fleet-api")
    client.post(f"/vehicles/{vehicle_id}/data", json={"temperature": 70, "status": "OK"})

    paths = [r.path for r in caplog.records if r.getMessage() == "request"]
    assert "/vehicles/{vehicle_id}/data" in paths


def test_alert_log_is_warning_with_alert_fields(client, caplog, vehicle_id):
    caplog.set_level(logging.INFO, logger="fleet-api")
    client.post(f"/vehicles/{vehicle_id}/data", json={"temperature": 95, "status": "OK"})

    alerts = [r for r in caplog.records if r.getMessage() == "alert created"]
    assert len(alerts) == 1

    entry = formatted(alerts[0])
    assert entry["level"] == "warning"
    assert entry["vehicle_id"] == vehicle_id
    assert entry["alert_type"] == "high_temperature"
    assert entry["temperature"] == 95


def test_uvicorn_access_log_is_disabled():
    # Our middleware logs every request once; uvicorn's access log would duplicate it
    setup_logging()
    access_logger = logging.getLogger("uvicorn.access")
    assert access_logger.handlers == []
    assert access_logger.propagate is False
