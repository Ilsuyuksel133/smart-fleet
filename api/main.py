import os

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import engine, get_db
from models import Alert, Base, SensorLog, Vehicle

ALERT_TEMP_THRESHOLD = float(os.getenv("ALERT_TEMP_THRESHOLD", "80"))

Base.metadata.create_all(bind=engine)

app = FastAPI()


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
    log = SensorLog(vehicle_id=vehicle_id, temperature=data.temperature, status=data.status)
    db.add(log)
    vehicle.status = data.status

    # Alert logic — asıl fark burada
    if data.temperature > ALERT_TEMP_THRESHOLD:
        alert = Alert(vehicle_id=vehicle_id, reason=f"Yüksek sıcaklık: {data.temperature}°C")
        db.add(alert)

    if data.status != "OK":
        alert = Alert(vehicle_id=vehicle_id, reason=f"Anormal durum: {data.status}")
        db.add(alert)

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
