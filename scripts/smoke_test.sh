#!/usr/bin/env bash
# End-to-end test of the running stack: health -> vehicle -> data -> alert -> metrics -> log (Loki)
# -> agent (webhook alert -> RCA report) -> web UI and its proxy
# Usage: scripts/smoke_test.sh [API_URL] [LOKI_URL] [AGENT_URL] [WEB_URL]
#   defaults: http://localhost:8000, http://localhost:3100, http://localhost:8100,
#             http://localhost:8080
set -euo pipefail

API_URL="${1:-${API_URL:-http://localhost:8000}}"
LOKI_URL="${2:-${LOKI_URL:-http://localhost:3100}}"
AGENT_URL="${3:-${AGENT_URL:-http://localhost:8100}}"
WEB_URL="${4:-${WEB_URL:-http://localhost:8080}}"
RETRIES="${RETRIES:-30}"
LOKI_RETRIES="${LOKI_RETRIES:-45}"
# With a real local model an investigation takes about a minute
REPORT_RETRIES="${REPORT_RETRIES:-120}"

log()  { echo "[smoke] $*"; }
fail() { echo "[smoke] FAIL: $*" >&2; exit 1; }

log "Target: $API_URL"

# 1) Wait until the API is ready
for i in $(seq 1 "$RETRIES"); do
  if curl -fsS "$API_URL/health" > /dev/null 2>&1; then
    log "Health check OK"
    break
  fi
  [ "$i" -eq "$RETRIES" ] && fail "API did not become healthy after $RETRIES attempts"
  log "Waiting for API... ($i/$RETRIES)"
  sleep 2
done

# 2) Create a vehicle
vehicle=$(curl -fsS -X POST "$API_URL/vehicles" \
  -H "Content-Type: application/json" -d '{"name": "smoke-test"}')
vehicle_id=$(echo "$vehicle" | grep -oE '"id":[0-9]+' | cut -d: -f2)
[ -n "$vehicle_id" ] || fail "Could not create vehicle: $vehicle"
log "Created vehicle id=$vehicle_id"

# 3) Send a high-temperature reading
curl -fsS -X POST "$API_URL/vehicles/$vehicle_id/data" \
  -H "Content-Type: application/json" -d '{"temperature": 95, "status": "OK"}' > /dev/null
log "Sent 95°C reading"

# 4) Was an alert created for this vehicle?
# Store the response first: with pipefail, "curl | grep -q" can fail spuriously because of SIGPIPE
alerts=$(curl -fsS "$API_URL/alerts")
if grep -qE "\"vehicle_id\":${vehicle_id}[,}]" <<< "$alerts"; then
  log "Alert created for vehicle $vehicle_id"
else
  fail "No alert found for vehicle $vehicle_id"
fi

# 5) Are the metric counters exposed?
metrics=$(curl -fsS "$API_URL/metrics")
grep -q "fleet_sensor_readings_total{vehicle_id=\"${vehicle_id}\"}" <<< "$metrics" \
  || fail "fleet_sensor_readings_total missing for vehicle $vehicle_id"
grep -q 'fleet_alerts_total{type="high_temperature"}' <<< "$metrics" \
  || fail "fleet_alerts_total missing"
log "Metrics OK"

# 6) Did the alert log reach Loki through Alloy? (collection can take a few seconds)
query="{service=\"api\"} | json | message=\"alert created\" | vehicle_id=\"${vehicle_id}\""
for i in $(seq 1 "$LOKI_RETRIES"); do
  # Store the response first: with pipefail, "curl | grep -q" can fail spuriously because of SIGPIPE
  loki_response=$(curl -fsS -G "$LOKI_URL/loki/api/v1/query_range" \
    --data-urlencode "query=$query" --data-urlencode "since=10m" 2>/dev/null || true)
  # An empty result looks like "result":[]; anything else means the log line was found
  if grep -q '"result":\[{' <<< "$loki_response"; then
    log "Alert log found in Loki for vehicle $vehicle_id"
    break
  fi
  [ "$i" -eq "$LOKI_RETRIES" ] && fail "Alert log not found in Loki after $LOKI_RETRIES attempts"
  log "Waiting for alert log in Loki... ($i/$LOKI_RETRIES)"
  sleep 2
done

# 7) Is the incident agent up?
for i in $(seq 1 "$RETRIES"); do
  if curl -fsS "$AGENT_URL/health" > /dev/null 2>&1; then
    log "Agent health check OK"
    break
  fi
  [ "$i" -eq "$RETRIES" ] && fail "Agent did not become healthy after $RETRIES attempts"
  log "Waiting for agent... ($i/$RETRIES)"
  sleep 2
done

# 8) Does a webhook alert turn into a stored RCA report? (fake or real LLM)
# Unique name per run, so the agent's per-alert cooldown never skips it
alert_name="SmokeTest$(date +%s)"
webhook_payload='{"status": "firing", "alerts": [{"status": "firing",
  "labels": {"alertname": "'"$alert_name"'", "severity": "info"},
  "annotations": {"summary": "Synthetic alert from the smoke test"}}]}'
accepted=$(curl -fsS -X POST "$AGENT_URL/webhook/alertmanager" \
  -H "Content-Type: application/json" -d "$webhook_payload")
investigation_id=$(grep -oE '"investigation_id":[0-9]+' <<< "$accepted" | cut -d: -f2)
[ -n "$investigation_id" ] || fail "Agent did not accept the webhook alert: $accepted"
log "Agent accepted $alert_name as investigation $investigation_id"

for i in $(seq 1 "$REPORT_RETRIES"); do
  report=$(curl -fsS "$AGENT_URL/reports/$investigation_id")
  if grep -q '"status":"done"' <<< "$report"; then
    grep -q '"root_cause_category":' <<< "$report" || fail "Report has no root cause: $report"
    log "RCA report stored for investigation $investigation_id"
    break
  fi
  grep -q '"status":"failed"' <<< "$report" && fail "Investigation failed: $report"
  [ "$i" -eq "$REPORT_RETRIES" ] && fail "No report after $REPORT_RETRIES attempts"
  log "Waiting for the agent's report... ($i/$REPORT_RETRIES)"
  sleep 2
done

# 9) Does the web UI load, and does nginx forward /api and /agent?
for i in $(seq 1 "$RETRIES"); do
  if curl -fsS "$WEB_URL/" > /dev/null 2>&1; then
    log "Web UI OK"
    break
  fi
  [ "$i" -eq "$RETRIES" ] && fail "Web UI did not respond after $RETRIES attempts"
  log "Waiting for the web UI... ($i/$RETRIES)"
  sleep 2
done
# A client-side route must return the app too (SPA fallback)
curl -fsS "$WEB_URL/incidents/$investigation_id" | grep -q '<div id="root">' \
  || fail "SPA fallback: $WEB_URL/incidents/$investigation_id did not return index.html"
web_health=$(curl -fsS "$WEB_URL/api/health")
grep -q '"status":"ok"' <<< "$web_health" || fail "Proxy to the API failed: $web_health"
web_report=$(curl -fsS "$WEB_URL/agent/reports/$investigation_id")
grep -q '"status":"done"' <<< "$web_report" || fail "Proxy to the agent failed: $web_report"
log "Web proxy to API and agent OK"

log "All checks passed ✅"
