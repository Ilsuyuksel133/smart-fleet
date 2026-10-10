# Smart Fleet — Runbook

Operational guide for the alerts defined in `monitoring/prometheus/alert_rules.yml` and common issues.
All commands are run from the repository root.

Useful links: API docs http://localhost:8000/docs · Prometheus alerts http://localhost:9090/alerts · Grafana http://localhost:3000

---

## FleetApiDown (critical)

**Symptom**
- Prometheus alert `FleetApiDown` is firing; the "API status" panel in Grafana shows **DOWN**.
- Dashboard shows "API'ye ulaşılamıyor", simulator logs connection errors.

**Possible causes**
- The `api` container stopped or crashed (bad deploy, Python exception at startup).
- The container is running but unhealthy (database not reachable → `/health` returns 503).
- Prometheus cannot reach `api:8000` (network or scrape config problem).

**Checks**
```bash
docker compose ps api                      # running? healthy?
docker compose logs --tail 100 api         # startup errors, tracebacks
curl -i http://localhost:8000/health       # 200 {"status":"ok","db":"ok"} expected
```
Prometheus → Status → Targets: is `fleet-api` UP, and what is the "Last error"?

**Fix**
- Container stopped: `docker compose up -d api`
- Crashing on startup: fix the error from the logs, then `docker compose up -d --build api`
- `/health` returns 503: check the database volume (`docker compose exec api ls -la /app/data`); as a last resort see *Resetting the database* below.
- Target down but API reachable from the host: check `monitoring/prometheus/prometheus.yml` and `docker compose restart prometheus`.

The alert resolves automatically after the next successful scrape.

---

## VehicleOverheating (warning)

**Symptom**
- Alert `VehicleOverheating` firing for a `vehicle_id`; the vehicle's line in "Temperature per vehicle" stays above 90 °C.

**Possible causes**
- A real overheating vehicle (cooling problem, heavy load).
- A faulty sensor reporting wrong values.
- In this demo: the simulator produces random temperatures between 60–100 °C.

**Checks**
```bash
curl -s http://localhost:8000/vehicles/<id>/status    # recent readings of the vehicle
curl -s http://localhost:8000/metrics | grep fleet_vehicle_temperature_celsius
```
Look at the trend in Grafana: a steady climb points to a real problem, sudden jumps to a sensor issue.

**Fix**
- Real vehicle: notify the vehicle operator / maintenance team, take the vehicle out of service if necessary.
- Faulty sensor: mark the vehicle for sensor maintenance.
- Demo: no action needed; the alert clears when the temperature drops below 90 °C.

---

## HighAlertRate (warning)

**Symptom**
- Alert `HighAlertRate` firing: more than 0.5 fleet alerts per second over 5 minutes.
- "Alert rate by type" panel is high; API logs are full of `WARNING Alert:` lines.

**Possible causes**
- Many vehicles in trouble at the same time (fleet-wide incident).
- The alert threshold is too low (`ALERT_TEMP_THRESHOLD`).
- A misbehaving client or the simulator sending too much data.
- In this demo the simulator intentionally produces many alerts, so this alert is expected to fire.

**Checks**
```bash
docker compose logs --tail 50 api | grep WARNING          # which vehicles / types?
curl -s http://localhost:8000/metrics | grep fleet_alerts_total
docker compose exec api printenv ALERT_TEMP_THRESHOLD
```
In Grafana, check whether one alert type or one vehicle dominates.

**Fix**
- One vehicle dominates: handle it like *VehicleOverheating* / a faulty sensor.
- Threshold too low: adjust `ALERT_TEMP_THRESHOLD` in `.env`, then `docker compose up -d api`.
- Simulator noise: `docker compose stop simulator` (or increase `INTERVAL_SECONDS`).

---

## No data in Grafana

**Symptom**
- Grafana panels show "No data", or the Fleet Overview dashboard is missing.

**Possible causes**
- Prometheus is down or cannot scrape the API.
- The API is up but nothing sends data (simulator stopped) — sensor panels stay empty.
- Datasource or dashboard provisioning failed.
- The time range in Grafana does not cover the period with data.

**Checks**
```bash
docker compose ps                                   # are prometheus, api, simulator running?
curl -s http://localhost:9090/api/v1/targets | grep -o '"health":"[a-z]*"'
docker compose logs --tail 50 simulator
docker compose logs grafana | grep -i -E "provision|error"
```
In Prometheus (http://localhost:9090) run `up` and `fleet_sensor_readings_total` — if they return data, the problem is on the Grafana side.

**Fix**
- Prometheus down / target down: see *FleetApiDown*, or `docker compose up -d prometheus`.
- Simulator stopped: `docker compose up -d simulator`.
- Provisioning errors: fix the files under `monitoring/grafana/`, then `docker compose restart grafana`.
- Time range: select "Last 15 minutes" and refresh.

---

## Resetting the database

**When:** corrupted SQLite file, or you want a clean demo state.

> ⚠️ This deletes all vehicles, sensor logs and alerts, and the Prometheus/Grafana data volumes.

```bash
docker compose down -v          # stop everything and remove named volumes
docker compose up -d --build    # start with empty volumes
make smoke                      # verify the stack
```
The simulator recreates its demo vehicles automatically on start.
