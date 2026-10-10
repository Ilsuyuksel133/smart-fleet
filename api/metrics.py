from prometheus_client import Counter, Gauge, Histogram

# --- İş (domain) metrikleri ---
SENSOR_READINGS = Counter(
    "fleet_sensor_readings_total",
    "Alınan sensör okuması sayısı",
    ["vehicle_id"],
)
ALERTS = Counter(
    "fleet_alerts_total",
    "Üretilen alert sayısı",
    ["type"],  # high_temperature | abnormal_status
)
VEHICLE_TEMPERATURE = Gauge(
    "fleet_vehicle_temperature_celsius",
    "Araçtan okunan son sıcaklık",
    ["vehicle_id"],
)

# --- HTTP metrikleri ---
HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP istek sayısı",
    ["method", "path", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP istek süresi (saniye)",
    ["method", "path"],
)
