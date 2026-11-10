from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy.sql import func

from database import Base


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    status = Column(String, default="OK")


class SensorLog(Base):
    __tablename__ = "sensor_logs"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer)
    temperature = Column(Float)
    status = Column(String)
    timestamp = Column(DateTime, default=func.now())


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer)
    # "high_temperature" or "abnormal_status": filterable and groupable in SQL,
    # instead of parsing the human-readable reason text
    type = Column(String(32))
    reason = Column(String)
    timestamp = Column(DateTime, default=func.now())
