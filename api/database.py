import os

from sqlalchemy import create_engine, make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/fleet.db")

connect_args = {}
url = make_url(DATABASE_URL)
if url.get_backend_name() == "sqlite":
    # Create the SQLite file's directory if needed (an in-memory DB has no file)
    if url.database and url.database != ":memory:":
        db_dir = os.path.dirname(url.database)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
    # FastAPI may handle requests in different threads; required for SQLite
    connect_args = {"check_same_thread": False}


def engine_options(backend: str) -> dict:
    """Connection pool settings per database backend."""
    if backend == "mysql":
        # MySQL closes idle connections after wait_timeout (8 h by default). pool_pre_ping
        # tests a pooled connection before using it, pool_recycle replaces connections
        # older than an hour, so a request never gets a connection the server dropped.
        return {"pool_pre_ping": True, "pool_recycle": 3600}
    return {}


engine = create_engine(
    DATABASE_URL, connect_args=connect_args, **engine_options(url.get_backend_name())
)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
