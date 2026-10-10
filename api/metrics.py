from prometheus_client import Counter, Gauge, Histogram

# --- Domain metrics ---
SENSOR_READINGS = Counter(
    "fleet_sensor_readings_total",
    "Number of sensor readings received",
    ["vehicle_id"],
)
ALERTS = Counter(
    "fleet_alerts_total",
    "Number of alerts created",
    ["type"],  # high_temperature | abnormal_status
)
VEHICLE_TEMPERATURE = Gauge(
    "fleet_vehicle_temperature_celsius",
    "Last temperature reported by the vehicle",
    ["vehicle_id"],
)

# --- HTTP metrikleri ---
HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Number of HTTP requests",
    ["method", "path", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)
