# Smart Fleet — Runbook

Operational guide for the alerts defined in `monitoring/prometheus/alert_rules.yml` and common issues.
All commands are run from the repository root.

Useful links: API docs http://localhost:8000/docs · Prometheus alerts http://localhost:9090/alerts · Grafana http://localhost:3000 · Logs: Grafana → Explore → Loki

---

## FleetApiDown (critical)

**Symptom**
- Prometheus alert `FleetApiDown` is firing; the "API status" panel in Grafana shows **DOWN**.
- Dashboard shows "Cannot reach the API", simulator logs connection errors.

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

**Logs to check (Grafana → Explore → Loki)**
```logql
# Last lines of the API before it went down (startup errors, tracebacks)
{service="api"} | json | level=~"error|critical"
{service="api"}
# Health check failures logged by the API
{service="api"} |= "Health check"
```
If Loki itself shows nothing for the API, fall back to `docker compose logs api`.

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

**Logs to check**
```logql
# Alert history of the vehicle (replace 3 with the vehicle_id from the alert)
{service="api"} | json | message="alert created" | vehicle_id="3"
# Readings the simulator sent for it
{service="simulator"} | json | message="reading sent" | vehicle_id="3"
```

**Fix**
- Real vehicle: notify the vehicle operator / maintenance team, take the vehicle out of service if necessary.
- Faulty sensor: mark the vehicle for sensor maintenance.
- Demo: no action needed; the alert clears when the temperature drops below 90 °C.

---

## HighAlertRate (warning)

**Symptom**
- Alert `HighAlertRate` firing: more than 0.5 fleet alerts per second over 5 minutes.
- "Alert rate by type" panel is high; the API logs many `"message": "alert created"` lines at level `warning`.

**Possible causes**
- Many vehicles in trouble at the same time (fleet-wide incident).
- The alert threshold is too low (`ALERT_TEMP_THRESHOLD`).
- A misbehaving client or the simulator sending too much data.
- In this demo the simulator intentionally produces many alerts, so this alert is expected to fire.

**Checks**
```bash
docker compose logs --tail 50 api | grep "alert created"  # which vehicles / types?
curl -s http://localhost:8000/metrics | grep fleet_alerts_total
docker compose exec api printenv ALERT_TEMP_THRESHOLD
```
In Grafana, check whether one alert type or one vehicle dominates.

**Logs to check**
```logql
# Alerts per type and per vehicle over the last 5 minutes
sum by (alert_type) (count_over_time({service="api"} | json | message="alert created" [5m]))
sum by (vehicle_id) (count_over_time({service="api"} | json | message="alert created" [5m]))
```

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

## No logs in Loki

**Symptom**
- Log panels in Grafana are empty, or a Loki query such as `{service="api"}` returns nothing.
- The smoke test fails at "Waiting for alert log in Loki".

**Possible causes**
- The `alloy` or `loki` container is down.
- Alloy cannot read the Docker socket (missing mount or permission problem).
- The containers belong to a different Compose project name — Alloy only collects containers labelled `com.docker.compose.project=smart-fleet`.
- Labels differ from what the query expects (e.g. `service="api"` vs. a different service name).
- Loki rejects the pushed logs (check Alloy's logs for push errors).

**Checks**
```bash
docker compose ps alloy loki
docker compose logs --tail 50 alloy | grep -iE "error|warn"
docker compose logs --tail 50 loki | grep -iE "error|warn"
curl -s http://localhost:3100/ready                                  # "ready" (first ~15 s after start: "Ingester not ready")
curl -s http://localhost:3100/loki/api/v1/label/service/values       # which services have logs?
docker inspect smart-fleet-api-1 --format '{{ index .Config.Labels "com.docker.compose.project" }}'
```
The Alloy UI at http://localhost:12345 shows every pipeline component and whether it is healthy.

**Fix**
- Container down: `docker compose up -d loki alloy`
- Docker socket: make sure `/var/run/docker.sock` is mounted into `alloy` (see `docker-compose.yml`) and exists on the host.
- Wrong project name: start the stack from the repository's `docker-compose.yml` (it sets `name: smart-fleet`).
- After changing `monitoring/alloy/config.alloy` or `monitoring/loki/loki-config.yml`: `docker compose restart alloy loki`.

---

## Reading an incident agent report

When an alert fires, the incident agent investigates it automatically (usually within 1–2 minutes) and stores a report. Open it on the **Incidents** page of the dashboard (http://localhost:8501/Incidents) or via `curl -s http://localhost:8100/reports`.

Read a report in this order:

1. **`stop_reason`:** `completed` means the model wrote the report. Anything else means the loop stopped the model and wrote it itself: `max_steps`, `timeout`, `invalid_output` or `llm_error`. Such a report is always `unknown` / low; only its evidence is useful.
2. **Evidence:** the tool calls and what they returned. This is the part you can trust most, because it is real data from Prometheus, Loki, the runbook and the health check. Check that the conclusion actually follows from it.
3. **Category and confidence:** `service_down`, `sensor_anomaly`, `alert_storm` or `unknown`, with `low` / `medium` / `high` confidence. Treat `low` and `unknown` as "not investigated", not as "no problem".
4. **Suggested actions:** proposals, usually copied from this runbook. **Nothing has been executed.** The agent's tools are read-only, so any action is your decision.

## When the agent is wrong

The agent uses a small local model; in the evaluation it found the right category in about 4 of 5 cases (see `eval/README.md`). Typical mistakes:
- It queries a metric with a label the metric does not have (e.g. `fleet_alerts_total{vehicle_id=...}`), gets "no data" and treats that as evidence.
- It is over-cautious and answers `unknown` despite clear evidence.
- It contradicts its own health check.

**What to do**
1. Ignore the conclusion and **follow this runbook manually** for the alert. The agent's evidence list is a good starting point.
2. Re-run a suspicious query from the evidence yourself (Prometheus or Grafana Explore). If it returns "no data", check that every label exists for that metric.
3. Start a new investigation if the situation has changed: the "Investigate" button on the Incidents page or `curl -X POST http://localhost:8100/investigate -H "Content-Type: application/json" -d '{"alert_name": "FleetApiDown"}'`.
4. Do not act on a suggested action you cannot back with the evidence.

## The agent produces no reports

**Symptom**
- An alert is firing, but no new report appears on the Incidents page.
- Reports end with `stop_reason: llm_error`.

**Possible causes**
- Alertmanager or the agent is down, or Prometheus cannot reach Alertmanager.
- The alert was skipped on purpose:
  - it is already queued or running
  - it was investigated less than 15 minutes ago
  - Alertmanager re-sends a firing alert only every 4 hours
- Ollama is not running on the host, or the model is not pulled (→ `llm_error`).
- `LLM_PROVIDER=fake` is set, so reports are scripted demo reports.

**Checks**
```bash
docker compose ps agent alertmanager
curl -s http://localhost:8100/health                        # provider and model
curl -s http://localhost:9090/api/v1/alertmanagers          # Prometheus -> Alertmanager
docker compose logs --tail 50 agent | grep -E "queued|skipped|failed|finished"
curl -s http://localhost:11434/api/tags                     # Ollama on the host, models pulled
```
Agent logs in Grafana Explore → Loki: `{service="agent"} | json | message=~"investigation.*|llm call failed"`.

**Fix**
- Agent or Alertmanager down: `docker compose up -d agent alertmanager`
- Ollama: `brew services start ollama` and `ollama pull qwen3:8b`
- Skipped alert: start it manually with `POST /investigate` (no cooldown for manual requests).

---

## Resetting the database

**When:** corrupted SQLite file, or you want a clean demo state.

> ⚠️ This deletes all vehicles, sensor logs and alerts, the incident agent's reports, and the Prometheus/Grafana/Loki data volumes.

```bash
docker compose down -v          # stop everything and remove named volumes
docker compose up -d --build    # start with empty volumes
make smoke                      # verify the stack
```
The simulator recreates its demo vehicles automatically on start.
