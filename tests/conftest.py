import os
import tempfile

# Use an in-memory DB so importing main.py does not create data/fleet.db on disk
os.environ.setdefault("DATABASE_URL", "sqlite://")
# Same for the agent's own database: a throwaway file instead of ./data/agent.db
os.environ.setdefault(
    "AGENT_DATABASE_URL", f"sqlite:///{tempfile.mkdtemp(prefix='agent-test-')}/agent.db"
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402

# Set to run the API tests against a real server, e.g. MySQL in CI:
# TEST_DATABASE_URL=mysql+pymysql://fleet:fleet@127.0.0.1:3306/fleet_test
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture
def session_factory(tmp_path):
    """A fresh database for each test: a temporary SQLite file, or the empty
    tables of TEST_DATABASE_URL.

    Tests can also open sessions on it directly, e.g. to insert rows with
    timestamps in the past.
    """
    if TEST_DATABASE_URL:
        engine = create_engine(TEST_DATABASE_URL)
        Base.metadata.drop_all(bind=engine)
    else:
        engine = create_engine(
            f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
        )
    Base.metadata.create_all(bind=engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


@pytest.fixture
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def vehicle_id(client):
    return client.post("/vehicles", json={"name": "Truck-1"}).json()["id"]
