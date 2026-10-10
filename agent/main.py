"""HTTP entry point of the agent service."""

import logging

from fastapi import FastAPI

from agent.config import get_settings
from agent.llm import get_provider
from agent.logging_config import setup_logging

settings = get_settings()
setup_logging()
log = logging.getLogger("fleet-agent")

app = FastAPI(title="smart-fleet incident agent")
provider = get_provider(settings)

log.info("agent started", extra={"llm_provider": provider.name})


@app.get("/health")
def health():
    # Liveness only: the agent must stay up even when Ollama is not running,
    # so the model is deliberately not contacted here.
    return {"status": "ok", "llm_provider": provider.name}
