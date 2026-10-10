from fastapi.testclient import TestClient

from agent.main import app


def test_agent_health_does_not_need_the_llm():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["llm_provider"] in {"ollama", "fake"}
