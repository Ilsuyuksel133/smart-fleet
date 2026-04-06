from sqlalchemy import Column, Integer, String, Float, DateTime
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