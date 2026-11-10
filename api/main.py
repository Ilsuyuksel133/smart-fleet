import logging
import os
import time
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from schemas import (
    AlertOut,
    AlertType,
    DataSavedOut,
    SensorData,
    StatsOut,
    VehicleCreate,
    VehicleOut,
    VehicleStatsOut,
    VehicleStatusOut,
)
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

import metrics
from database import engine, get_db
from logging_config import setup_logging
from models import Alert, Base, SensorLog, Vehicle

ALERT_TEMP_THRESHOLD = float(os.getenv("ALERT_TEMP_THRESHOLD", "80"))

setup_logging()
log = logging.getLogger("fleet-api")

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Smart Fleet API", version="1.0.0")


def parse_origins(value: str) -> list[str]:
    """CORS_ORIGINS="http://a.example,http://b.example" -> ["http://a.example", "http://b.example"]"""
    return [origin.strip() for origin in value.split(",") if origin.strip()]


def add_cors(application: FastAPI, origins: list[str]) -> None:
    """Allow browsers on these origins to call the API directly.

    Off by default: the web frontend calls the API through its own origin
    (Vite or nginx proxy), so CORS is not needed. Only GET and POST are used.
    """
    if origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )


add_cors(app, parse_origins(os.getenv("CORS_ORIGINS", "")))


# --- Middleware for HTTP metrics and request logs ---
@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    # Use the route template (/vehicles/{vehicle_id}/data) instead of the raw URL
    # (/vehicles/42/data); otherwise every vehicle ID would create a new time series.
    route = request.scope.get("route")
    path = route.path if route else "unmatched"

    metrics.HTTP_REQUESTS.labels(request.method, path, response.status_code).inc()
    metrics.HTTP_REQUEST_DURATION.labels(request.method, path).observe(duration)
    log.info(
        "request",
        extra={
            "method": request.method,
            "path": path,
            "status": response.status_code,
            "duration_ms": round(duration * 1000, 2),
        },
    )
    return response


# --- Endpoint 1: add a vehicle ---
@app.post("/vehicles", response_model=VehicleOut)
def add_vehicle(data: VehicleCreate, db: Session = Depends(get_db)):
    vehicle = Vehicle(name=data.name)
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return vehicle


# --- Endpoint 2: send sensor data ---
@app.post("/vehicles/{vehicle_id}/data", response_model=DataSavedOut)
def send_data(vehicle_id: int, data: SensorData, db: Session = Depends(get_db)):
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Store the reading and update the vehicle's latest status
    reading = SensorLog(vehicle_id=vehicle_id, temperature=data.temperature, status=data.status)
    db.add(reading)
    vehicle.status = data.status
    metrics.SENSOR_READINGS.labels(vehicle_id).inc()
    metrics.VEHICLE_TEMPERATURE.labels(vehicle_id).set(data.temperature)

    # Alert logic
    if data.temperature > ALERT_TEMP_THRESHOLD:
        alert = Alert(
            vehicle_id=vehicle_id,
            type="high_temperature",
            reason=f"High temperature: {data.temperature}°C",
        )
        db.add(alert)
        metrics.ALERTS.labels("high_temperature").inc()
        log.warning(
            "alert created",
            extra={
                "vehicle_id": vehicle_id,
                "alert_type": "high_temperature",
                "temperature": data.temperature,
            },
        )

    if data.status != "OK":
        alert = Alert(
            vehicle_id=vehicle_id,
            type="abnormal_status",
            reason=f"Abnormal status: {data.status}",
        )
        db.add(alert)
        metrics.ALERTS.labels("abnormal_status").inc()
        log.warning(
            "alert created",
            extra={
                "vehicle_id": vehicle_id,
                "alert_type": "abnormal_status",
                "temperature": data.temperature,
                "vehicle_status": data.status,
            },
        )

    db.commit()
    return {"message": "Data saved", "alerts_checked": True}


# --- Endpoint 3: list all vehicles ---
@app.get("/vehicles", response_model=list[VehicleOut])
def list_vehicles(db: Session = Depends(get_db)):
    return db.scalars(select(Vehicle).order_by(Vehicle.id)).all()


# --- Endpoint 4: vehicle status ---
@app.get("/vehicles/{vehicle_id}/status", response_model=VehicleStatusOut)
def get_status(
    vehicle_id: int,
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    if db.get(Vehicle, vehicle_id) is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    # Take the newest N readings, then return them oldest first (ready for a chart)
    newest = db.scalars(
        select(SensorLog)
        .where(SensorLog.vehicle_id == vehicle_id)
        .order_by(SensorLog.timestamp.desc(), SensorLog.id.desc())
        .limit(limit)
    ).all()
    return {"vehicle_id": vehicle_id, "logs": list(reversed(newest))}


# --- Endpoint 5: alerts ---
@app.get("/alerts", response_model=list[AlertOut])
def get_alerts(
    limit: int = Query(100, ge=1, le=1000),
    vehicle_id: int | None = None,
    # "type" is a Python builtin, so the parameter gets another name and an alias
    alert_type: AlertType | None = Query(None, alias="type"),
    db: Session = Depends(get_db),
):
    query = select(Alert)
    if vehicle_id is not None:
        query = query.where(Alert.vehicle_id == vehicle_id)
    if alert_type is not None:
        query = query.where(Alert.type == alert_type)
    # Newest first; timestamps have second precision, so the id breaks ties
    query = query.order_by(Alert.timestamp.desc(), Alert.id.desc()).limit(limit)
    return db.scalars(query).all()


# --- Endpoint 6: aggregated statistics ---
@app.get("/stats", response_model=StatsOut)
def get_stats(minutes: int = Query(15, ge=1, le=1440), db: Session = Depends(get_db)):
    # Timestamps are stored in UTC (the database's CURRENT_TIMESTAMP)
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=minutes)

    # SELECT COUNT(*) FROM vehicles;
    vehicles_total = db.scalar(select(func.count()).select_from(Vehicle))
    # SELECT COUNT(*) FROM vehicles WHERE status != 'OK';
    vehicles_not_ok = db.scalar(
        select(func.count()).select_from(Vehicle).where(Vehicle.status != "OK")
    )

    # SELECT type, COUNT(*) FROM alerts
    # WHERE timestamp >= :since
    # GROUP BY type;
    alert_rows = db.execute(
        select(Alert.type, func.count()).where(Alert.timestamp >= since).group_by(Alert.type)
    ).all()
    # Every type is present, with 0 if there were no alerts of that type
    alerts_by_type = {"high_temperature": 0, "abnormal_status": 0}
    alerts_by_type.update({alert_type: count for alert_type, count in alert_rows if alert_type})

    # SELECT v.id, v.name, COUNT(*), AVG(s.temperature), MAX(s.temperature)
    # FROM sensor_logs s JOIN vehicles v ON v.id = s.vehicle_id
    # WHERE s.timestamp >= :since
    # GROUP BY v.id, v.name
    # ORDER BY v.id;
    vehicle_rows = db.execute(
        select(
            Vehicle.id,
            Vehicle.name,
            func.count(SensorLog.id),
            func.avg(SensorLog.temperature),
            func.max(SensorLog.temperature),
        )
        .join(SensorLog, SensorLog.vehicle_id == Vehicle.id)
        .where(SensorLog.timestamp >= since)
        .group_by(Vehicle.id, Vehicle.name)
        .order_by(Vehicle.id)
    ).all()
    per_vehicle = [
        VehicleStatsOut(
            vehicle_id=vehicle_id,
            name=name,
            readings=readings,
            avg_temperature=round(avg, 2),
            max_temperature=maximum,
        )
        for vehicle_id, name, readings, avg, maximum in vehicle_rows
    ]

    return StatsOut(
        window_minutes=minutes,
        vehicles_total=vehicles_total,
        vehicles_not_ok=vehicles_not_ok,
        alerts_by_type=alerts_by_type,
        per_vehicle=per_vehicle,
    )


# --- Observability ---
@app.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        log.exception("Health check: database unreachable")
        return JSONResponse(status_code=503, content={"status": "error", "db": "error"})
    return {"status": "ok", "db": "ok"}


@app.get("/metrics")
def prometheus_metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
