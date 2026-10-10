#!/usr/bin/env bash
# Çalışan sistemi uçtan uca test eder: health -> araç -> veri -> alert -> metrik
# Kullanım: scripts/smoke_test.sh [API_URL]   (varsayılan: http://localhost:8000)
set -euo pipefail

API_URL="${1:-${API_URL:-http://localhost:8000}}"
RETRIES="${RETRIES:-30}"

log()  { echo "[smoke] $*"; }
fail() { echo "[smoke] FAIL: $*" >&2; exit 1; }

log "Target: $API_URL"

# 1) API hazır olana kadar bekle
for i in $(seq 1 "$RETRIES"); do
  if curl -fsS "$API_URL/health" > /dev/null 2>&1; then
    log "Health check OK"
    break
  fi
  [ "$i" -eq "$RETRIES" ] && fail "API did not become healthy after $RETRIES attempts"
  log "Waiting for API... ($i/$RETRIES)"
  sleep 2
done

# 2) Araç oluştur
vehicle=$(curl -fsS -X POST "$API_URL/vehicles" \
  -H "Content-Type: application/json" -d '{"name": "smoke-test"}')
vehicle_id=$(echo "$vehicle" | grep -oE '"id":[0-9]+' | cut -d: -f2)
[ -n "$vehicle_id" ] || fail "Could not create vehicle: $vehicle"
log "Created vehicle id=$vehicle_id"

# 3) Yüksek sıcaklık verisi gönder
curl -fsS -X POST "$API_URL/vehicles/$vehicle_id/data" \
  -H "Content-Type: application/json" -d '{"temperature": 95, "status": "OK"}' > /dev/null
log "Sent 95°C reading"

# 4) Bu araç için alert oluştu mu?
if curl -fsS "$API_URL/alerts" | grep -qE "\"vehicle_id\":$vehicle_id[,}]"; then
  log "Alert created for vehicle $vehicle_id"
else
  fail "No alert found for vehicle $vehicle_id"
fi

# 5) Metrik sayaçları görünüyor mu?
metrics=$(curl -fsS "$API_URL/metrics")
echo "$metrics" | grep -q "fleet_sensor_readings_total{vehicle_id=\"$vehicle_id\"}" \
  || fail "fleet_sensor_readings_total missing for vehicle $vehicle_id"
echo "$metrics" | grep -q 'fleet_alerts_total{type="high_temperature"}' \
  || fail "fleet_alerts_total missing"
log "Metrics OK"

log "All checks passed ✅"
