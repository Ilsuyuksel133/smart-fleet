"""All agent settings in one place.

Every field can be overridden with an environment variable of the same name
(case-insensitive), e.g. ``LLM_PROVIDER=fake`` or ``OLLAMA_MODEL=qwen3:4b``.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Which LLM backend to use: the real local model or scripted test responses
    llm_provider: Literal["ollama", "fake"] = "ollama"

    # Ollama runs on the host (not in Docker) so it can use the Mac's GPU
    ollama_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen3:8b"
    ollama_timeout_seconds: float = 120.0

    # Read-only data sources the agent's tools will query
    prometheus_url: str = "http://prometheus:9090"
    loki_url: str = "http://loki:3100"
    api_url: str = "http://api:8000"

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Read the settings once and reuse them (environment is fixed at startup)."""
    return Settings()
