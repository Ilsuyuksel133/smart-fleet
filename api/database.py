import os

from sqlalchemy import create_engine, make_url
from sqlalchemy.orm import declarative_base, sessionmaker

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

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
