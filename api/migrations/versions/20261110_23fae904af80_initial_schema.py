"""Initial schema: vehicles, sensor_logs and alerts

Replaces Base.metadata.create_all(). Compared with the old tables: string lengths
(MySQL needs them), alerts.type, foreign keys to vehicles, DOUBLE temperatures and
indexes for the queries of the vehicle page, /alerts and /stats.

Revision ID: 23fae904af80
Revises:
Create Date: 2026-11-10 20:48:45
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "23fae904af80"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_timestamp", "alerts", ["timestamp"])
    op.create_index("ix_alerts_vehicle_id", "alerts", ["vehicle_id"])
    op.create_table(
        "sensor_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("temperature", sa.Double(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sensor_logs_vehicle_id_timestamp", "sensor_logs", ["vehicle_id", "timestamp"]
    )


def downgrade() -> None:
    op.drop_index("ix_sensor_logs_vehicle_id_timestamp", table_name="sensor_logs")
    op.drop_table("sensor_logs")
    op.drop_index("ix_alerts_vehicle_id", table_name="alerts")
    op.drop_index("ix_alerts_timestamp", table_name="alerts")
    op.drop_table("alerts")
    op.drop_table("vehicles")
