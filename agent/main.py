"""HTTP entry point of the agent service.

Endpoints:
- POST /webhook/alertmanager  Alertmanager sends firing alerts here (202, runs in background)
- POST /investigate           start an investigation manually (202)
- GET  /reports, /reports/{id} investigation history and full RCA reports
- GET  /health, /metrics      liveness and Prometheus metrics
"""

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from agent import metrics
from agent.config import Settings, get_settings
from agent.llm import LLMProvider, get_provider
from agent.logging_config import setup_logging
from agent.loop import Investigator
from agent.report import Alert
from agent.service import InvestigationService
from agent.storage import ReportStore
from agent.tools import build_tools

log = logging.getLogger("fleet-agent")


class InvestigateRequest(BaseModel):
    alert_name: str
    labels: dict[str, str] = Field(default_factory=dict)


def alerts_from_webhook(payload: dict[str, Any]) -> list[Alert]:
    """Turn an Alertmanager webhook payload into one Alert per alert name.

    Alertmanager groups alerts by name (see alertmanager.yml), so four
    overheating vehicles arrive as one group: they become a single
    investigation, with the differing labels listed for the model.
    Resolved alerts are ignored; only firing ones are investigated.
    """
    by_name: dict[str, list[dict[str, Any]]] = {}
    for item in payload.get("alerts", []):
        if item.get("status") == "firing":
            name = item.get("labels", {}).get("alertname", "unknown")
            by_name.setdefault(name, []).append(item)

    alerts = []
    for name, group in by_name.items():
        first = group[0].get("labels", {})
        common = {
            key: value
            for key, value in first.items()
            if all(other.get("labels", {}).get(key) == value for other in group)
        }
        annotations = dict(group[0].get("annotations", {}))
        if len(group) > 1:
            varying = sorted(
                {
                    f"{key}={value}"
                    for other in group
                    for key, value in other.get("labels", {}).items()
                    if key not in common
                }
            )
            annotations["firing_instances"] = str(len(group))
            annotations["instance_labels"] = ", ".join(varying)
        alerts.append(Alert(name=name, labels=common, annotations=annotations))
    return alerts


def create_app(
    settings: Settings,
    provider: LLMProvider | None = None,
    start_worker: bool = True,
) -> FastAPI:
    """Build the app. Tests pass a FakeProvider and run the queue themselves."""
    provider = provider or get_provider(settings)
    tools = build_tools(settings)
    metrics.initialize(list(tools))
    investigator = Investigator(
        provider=provider,
        tools=tools,
        max_steps=settings.agent_max_steps,
        max_seconds=settings.agent_max_seconds,
    )
    service = InvestigationService(
        store=ReportStore(settings.agent_database_url),
        investigator=investigator,
        cooldown_seconds=settings.investigation_cooldown_seconds,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_worker:
            service.start_worker()
        log.info("agent started", extra={"llm_provider": provider.name})
        yield

    app = FastAPI(title="smart-fleet incident agent", lifespan=lifespan)
    app.state.service = service

    @app.get("/health")
    def health():
        # Liveness only: the agent must stay up even when Ollama is not running,
        # so the model is deliberately not contacted here.
        return {
            "status": "ok",
            "llm_provider": provider.name,
            "llm_model": getattr(provider, "model", None),
        }

    @app.get("/metrics")
    def prometheus_metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/webhook/alertmanager", status_code=202)
    def alertmanager_webhook(payload: dict[str, Any]):
        results = [
            service.submit(alert, trigger="alertmanager") for alert in alerts_from_webhook(payload)
        ]
        return {
            "accepted": [
                {"alert_name": r.alert_name, "investigation_id": r.investigation_id}
                for r in results
                if r.accepted
            ],
            "skipped": [
                {"alert_name": r.alert_name, "reason": r.reason} for r in results if not r.accepted
            ],
        }

    @app.post("/investigate", status_code=202)
    def investigate(request: InvestigateRequest):
        # A human asked for it explicitly: no cooldown, but never two at once
        alert = Alert(name=request.alert_name, labels=request.labels)
        result = service.submit(alert, trigger="manual", respect_cooldown=False)
        if not result.accepted:
            raise HTTPException(status_code=409, detail=result.reason)
        return {"alert_name": result.alert_name, "investigation_id": result.investigation_id}

    @app.get("/reports")
    def list_reports(limit: int = 50):
        return [row.to_dict() for row in service.store.latest(min(max(limit, 1), 200))]

    @app.get("/reports/{investigation_id}")
    def get_report(investigation_id: int):
        row = service.store.get(investigation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Investigation not found")
        return row.to_dict(include_report=True)

    return app


setup_logging()
app = create_app(get_settings())
