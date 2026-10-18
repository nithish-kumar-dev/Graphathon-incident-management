"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import errors
from app.api.logging import RequestContextMiddleware, configure_logging
from app.api.routes import alerts, health, incidents, investigations, services
from app.config import get_settings

DESCRIPTION = """
Graph-grounded incident investigation API.

* **Synthetic data only**: NovaCommerce is a fictional company.
* **Identity**: send `X-Demo-User` (demo-viewer, demo-responder, payments-lead). This is a demo permission
  context, **not authentication**.
* Responses contain real graph ids and relationship names. Graph correlations are labelled
  `correlated`, never confirmed causes. No endpoint depends on an LLM.
* Investigations are run by the orchestrator worker (LangGraph, Postgres checkpoints) when
  `ORCHESTRATOR_ENABLED=true`. Action review (`POST /api/actions/{id}/review`) arrives in Phase 5.
"""

log = logging.getLogger("app.orchestrator")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Starts the in-process orchestrator worker when enabled, and stops it cleanly on shutdown.
    Settings honour a test override of get_settings, so a test client never starts a worker on the dev graph."""
    settings = app.dependency_overrides.get(get_settings, get_settings)()
    worker = None
    if settings.orchestrator_enabled:
        from app.orchestrator.runner import Worker
        worker = Worker(settings)
        worker.start()
    app.state.orchestrator = worker
    try:
        yield
    finally:
        if worker is not None:
            worker.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="Graphathon incident API", version="0.2.0", description=DESCRIPTION, lifespan=lifespan)
    errors.install(app)
    for module in (health, alerts, incidents, investigations, services):
        app.include_router(module.router)
    app.add_middleware(RequestContextMiddleware, max_body_bytes=settings.max_request_bytes)
    return app


app = create_app()
