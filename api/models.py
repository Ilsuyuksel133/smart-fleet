from datetime import UTC, datetime

from sqlalchemy import Double, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


def utc_now() -> datetime:
    """Naive UTC timestamp, the same on every database.

    Set in Python instead of the database's NOW(): MySQL's NOW() follows the
    session time zone, SQLite's CURRENT_TIMESTAMP is always UTC.
    """
    return datetime.now(UTC).replace(tzinfo=None)


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    # MySQL needs a length for VARCHAR columns
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="OK")


class SensorLog(Base):
    __tablename__ = "sensor_logs"
    # The vehicle page and /stats filter by vehicle and time range; this index serves
    # both, and also serves the foreign key (vehicle_id is its first column)
    __table_args__ = (Index("ix_sensor_logs_vehicle_id_timestamp", "vehicle_id", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    # Double, not Float: MySQL's FLOAT is single precision (85.7 -> 85.69999694824219)
    temperature: Mapped[float] = mapped_column(Double)
    status: Mapped[str] = mapped_column(String(20))
    timestamp: Mapped[datetime] = mapped_column(default=utc_now)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    # "high_temperature" or "abnormal_status": filterable and groupable in SQL,
    # instead of parsing the human-readable reason text
    type: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(255))
    # /alerts sorts by time and /stats filters by a time window
    timestamp: Mapped[datetime] = mapped_column(default=utc_now, index=True)
