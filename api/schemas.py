"""Request and response schemas of the fleet API.

Declaring the response shapes (instead of returning ORM objects) documents the
API in the OpenAPI schema, which the web frontend uses to generate its types.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

AlertType = Literal["high_temperature", "abnormal_status"]


# --- Requests ---


class VehicleCreate(BaseModel):
    name: str


class SensorData(BaseModel):
    temperature: float
    status: str


# --- Responses ---


class VehicleOut(BaseModel):
    # Lets FastAPI build the schema from SQLAlchemy objects (attribute access)
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: str


class SensorLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_id: int
    temperature: float
    status: str
    timestamp: datetime


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_id: int
    type: AlertType
    reason: str
    timestamp: datetime


class DataSavedOut(BaseModel):
    message: str
    alerts_checked: bool


class VehicleStatusOut(BaseModel):
    vehicle_id: int
    logs: list[SensorLogOut]


class VehicleStatsOut(BaseModel):
    vehicle_id: int
    name: str
    readings: int
    avg_temperature: float
    max_temperature: float


class StatsOut(BaseModel):
    window_minutes: int
    vehicles_total: int
    vehicles_not_ok: int
    alerts_by_type: dict[AlertType, int]
    per_vehicle: list[VehicleStatsOut]
