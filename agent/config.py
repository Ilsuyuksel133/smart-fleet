"""All agent settings in one place.

Every field can be overridden with an environment variable of the same name
(case-insensitive), e.g. ``LLM_PROVIDER=fake`` or ``OLLAMA_MODEL=qwen3:4b``.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Which LLM backend to use: the real local model or scripted test responses
    llm_provider: Literal["ollama", "fake"] = "ollama"

    # Ollama runs on the host (not in Docker) so it can use the Mac's GPU
    ollama_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen3:8b"
    ollama_timeout_seconds: float = 120.0
    ollama_think: bool = False

    # Guard rails of the agent loop
    agent_max_steps: int = 8
    agent_max_seconds: float = 300.0

    # Read-only data sources the agent's tools will query
    prometheus_url: str = "http://prometheus:9090"
    loki_url: str = "http://loki:3100"
    api_url: str = "http://api:8000"

    # Inside the image the runbook is copied to /app/docs, next to the package;
    # in the repository it is docs/RUNBOOK.md. Both resolve to the same relative path.
    runbook_path: Path = Path(__file__).resolve().parent.parent / "docs" / "RUNBOOK.md"

    # Tool limits: keep the model's context small and every call bounded in time
    tool_timeout_seconds: float = 10.0
    max_query_minutes: int = 60
    max_log_lines: int = 50
    max_series: int = 10
    max_tool_output_chars: int = 4000

    # The agent's own database for investigations and reports
    agent_database_url: str = "sqlite:///./data/agent.db"
    # Skip an alert from Alertmanager if it was investigated less than this ago
    investigation_cooldown_seconds: float = 900.0

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Read the settings once and reuse them (environment is fixed at startup)."""
    return Settings()
