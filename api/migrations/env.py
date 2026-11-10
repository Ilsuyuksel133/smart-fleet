"""Alembic environment: runs the migrations against the API's database."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

import models  # noqa: F401  (registers the tables on Base.metadata)
from database import DATABASE_URL, Base

config = context.config

if config.config_file_name is not None:
    # Keep the application's loggers working when migrations run inside the tests
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# A URL set by the caller (e.g. a test) wins over DATABASE_URL
url = config.get_main_option("sqlalchemy.url") or DATABASE_URL


def run_migrations_offline() -> None:
    """Print the SQL instead of running it: alembic upgrade head --sql"""
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite cannot ALTER most things; batch mode copies the table instead
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
