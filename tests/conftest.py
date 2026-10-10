import os

# main.py import edilirken diskte data/fleet.db oluşmasın diye bellek içi DB kullan
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    """Her test için ayrı, geçici bir SQLite veritabanı."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def vehicle_id(client):
    return client.post("/vehicles", json={"name": "Truck-1"}).json()["id"]
