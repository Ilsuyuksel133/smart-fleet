"""The Alembic migrations must create exactly the schema the models describe."""

import io
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

ALEMBIC_INI = Path(__file__).parent.parent / "api" / "alembic.ini"


def alembic_config(url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_upgrade_matches_the_models_and_downgrade_removes_everything(tmp_path):
    url = f"sqlite:///{tmp_path / 'migrations.db'}"
    config = alembic_config(url)

    command.upgrade(config, "head")
    # Raises if the models have changes that no migration contains
    command.check(config)

    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names())
    assert {"vehicles", "sensor_logs", "alerts"} <= tables
    indexes = {index["name"] for index in inspect(engine).get_indexes("sensor_logs")}
    assert "ix_sensor_logs_vehicle_id_timestamp" in indexes

    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()


def test_offline_mode_prints_the_sql():
    # alembic upgrade head --sql: the SQL a DBA could review before running it
    config = alembic_config("mysql+pymysql://user:pass@localhost/fleet")
    config.output_buffer = buffer = io.StringIO()
    command.upgrade(config, "head", sql=True)
    sql = buffer.getvalue()
    assert "CREATE TABLE sensor_logs" in sql
    assert "temperature DOUBLE NOT NULL" in sql
    assert "FOREIGN KEY(vehicle_id) REFERENCES vehicles (id)" in sql


def test_mysql_connections_are_checked_and_recycled():
    from database import engine_options

    assert engine_options("mysql") == {"pool_pre_ping": True, "pool_recycle": 3600}
    assert engine_options("sqlite") == {}
