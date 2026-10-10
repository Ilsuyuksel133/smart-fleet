#!/usr/bin/env bash
# Çalışan sistemi uçtan uca test eder: health -> araç -> veri -> alert -> metrik -> log (Loki)
# Kullanım: scripts/smoke_test.sh [API_URL] [LOKI_URL]
#   varsayılanlar: http://localhost:8000 ve http://localhost:3100
set -euo pipefail

API_URL="${1:-${API_URL:-http://localhost:8000}}"
LOKI_URL="${2:-${LOKI_URL:-http://localhost:3100}}"
RETRIES="${RETRIES:-30}"
LOKI_RETRIES="${LOKI_RETRIES:-45}"

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
# Önce değişkene al: "curl | grep -q" pipefail ile SIGPIPE yüzünden yanlış FAIL verebilir
alerts=$(curl -fsS "$API_URL/alerts")
if grep -qE "\"vehicle_id\":${vehicle_id}[,}]" <<< "$alerts"; then
  log "Alert created for vehicle $vehicle_id"
else
  fail "No alert found for vehicle $vehicle_id"
fi

# 5) Metrik sayaçları görünüyor mu?
metrics=$(curl -fsS "$API_URL/metrics")
grep -q "fleet_sensor_readings_total{vehicle_id=\"${vehicle_id}\"}" <<< "$metrics" \
  || fail "fleet_sensor_readings_total missing for vehicle $vehicle_id"
grep -q 'fleet_alerts_total{type="high_temperature"}' <<< "$metrics" \
  || fail "fleet_alerts_total missing"
log "Metrics OK"

# 6) Alert logu Alloy üzerinden Loki'ye ulaştı mı? (toplama birkaç saniye sürebilir)
query="{service=\"api\"} | json | message=\"alert created\" | vehicle_id=\"${vehicle_id}\""
for i in $(seq 1 "$LOKI_RETRIES"); do
  # Önce değişkene al: "curl | grep -q" pipefail ile SIGPIPE yüzünden yanlış FAIL verebilir
  loki_response=$(curl -fsS -G "$LOKI_URL/loki/api/v1/query_range" \
    --data-urlencode "query=$query" --data-urlencode "since=10m" 2>/dev/null || true)
  # Sonuç boşsa yanıtta "result":[] olur; doluysa log satırı bulunmuştur
  if grep -q '"result":\[{' <<< "$loki_response"; then
    log "Alert log found in Loki for vehicle $vehicle_id"
    break
  fi
  [ "$i" -eq "$LOKI_RETRIES" ] && fail "Alert log not found in Loki after $LOKI_RETRIES attempts"
  log "Waiting for alert log in Loki... ($i/$LOKI_RETRIES)"
  sleep 2
done

log "All checks passed ✅"
