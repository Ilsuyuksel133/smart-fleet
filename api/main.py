import logging
import os
import time

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

import metrics
from database import engine, get_db
from models import Alert, Base, SensorLog, Vehicle

ALERT_TEMP_THRESHOLD = float(os.getenv("ALERT_TEMP_THRESHOLD", "80"))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("fleet-api")

Base.metadata.create_all(bind=engine)

app = FastAPI()


# --- HTTP metrikleri için middleware ---
@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    # Gerçek URL (/vehicles/42/data) yerine route şablonunu (/vehicles/{vehicle_id}/data)
    # kullanıyoruz, yoksa her araç ID'si için yeni bir zaman serisi oluşur.
    route = request.scope.get("route")
    path = route.path if route else "unmatched"

    metrics.HTTP_REQUESTS.labels(request.method, path, response.status_code).inc()
    metrics.HTTP_REQUEST_DURATION.labels(request.method, path).observe(duration)
    return response


# --- Gelen veri için şablonlar ---
class VehicleCreate(BaseModel):
    name: str


class SensorData(BaseModel):
    temperature: float
    status: str


# --- Endpoint 1: Araç ekle ---
@app.post("/vehicles")
def add_vehicle(data: VehicleCreate, db: Session = Depends(get_db)):
    vehicle = Vehicle(name=data.name)
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return vehicle


# --- Endpoint 2: Sensör verisi gönder ---
@app.post("/vehicles/{vehicle_id}/data")
def send_data(vehicle_id: int, data: SensorData, db: Session = Depends(get_db)):
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Veriyi kaydet ve aracın son durumunu güncelle
    reading = SensorLog(vehicle_id=vehicle_id, temperature=data.temperature, status=data.status)
    db.add(reading)
    vehicle.status = data.status
    metrics.SENSOR_READINGS.labels(vehicle_id).inc()
    metrics.VEHICLE_TEMPERATURE.labels(vehicle_id).set(data.temperature)

    # Alert logic — asıl fark burada
    if data.temperature > ALERT_TEMP_THRESHOLD:
        alert = Alert(vehicle_id=vehicle_id, reason=f"Yüksek sıcaklık: {data.temperature}°C")
        db.add(alert)
        metrics.ALERTS.labels("high_temperature").inc()
        log.warning("Alert: vehicle %s high temperature %.1f°C", vehicle_id, data.temperature)

    if data.status != "OK":
        alert = Alert(vehicle_id=vehicle_id, reason=f"Anormal durum: {data.status}")
        db.add(alert)
        metrics.ALERTS.labels("abnormal_status").inc()
        log.warning("Alert: vehicle %s abnormal status %s", vehicle_id, data.status)

    db.commit()
    return {"message": "Veri kaydedildi", "alerts_checked": True}


# --- Endpoint 3: Tüm araçları listele ---
@app.get("/vehicles")
def list_vehicles(db: Session = Depends(get_db)):
    return db.query(Vehicle).all()


# --- Endpoint 4: Araç durumu ---
@app.get("/vehicles/{vehicle_id}/status")
def get_status(vehicle_id: int, db: Session = Depends(get_db)):
    logs = db.query(SensorLog).filter(SensorLog.vehicle_id == vehicle_id).all()
    return {"vehicle_id": vehicle_id, "logs": logs}


@app.get("/alerts")
def get_alerts(db: Session = Depends(get_db)):
    return db.query(Alert).all()


# --- Gözlemlenebilirlik ---
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
