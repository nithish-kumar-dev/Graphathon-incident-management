"""FastAPI application factory."""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import errors
from app.api.logging import RequestContextMiddleware, configure_logging
from app.api.routes import actions, alerts, demo, health, incidents, investigations, memories, services
from app.config import get_settings

DESCRIPTION = """
Graph-grounded incident investigation API.

* **Synthetic data only**: NovaCommerce is a fictional company.
* **Identity**: send `X-Demo-User` (demo-viewer, demo-responder, payments-lead). This is a demo permission
  context, **not authentication**.
* Responses contain real graph ids and relationship names. Graph correlations are labelled
  `correlated`, never confirmed causes. No endpoint depends on an LLM.
* Investigations are run by the orchestrator worker (LangGraph, Postgres checkpoints) when
  `ORCHESTRATOR_ENABLED=true`. Actions are reviewed with `POST /api/actions/{id}/review`; an approved
  simulated rollback runs in simulation only (nothing real is changed) and leaves a draft memory a human validates.
  A paused run is resumed by the worker (LangGraph `interrupt()`); the executor is idempotent.
* Demo controls (`/api/demo/controls`) flip two graph edges and exist only when `DEMO_CONTROLS_ENABLED=true`.
"""

log = logging.getLogger("app.orchestrator")


def _start_worker(app: FastAPI, settings) -> None:
    if settings.orchestrator_enabled:
        from app.orchestrator.runner import Worker
        worker = Worker(settings)
        worker.start()
        app.state.orchestrator = worker


def _prepare_then_start(app: FastAPI, settings, stopping: threading.Event, lock: threading.Lock) -> None:
    """STARTUP_DATA runs here, off the event loop: the port opens at once (Render's port scan, Netlify's
    proxy timeout) and /readyz reports `data: false` until the graph is ready. The worker starts after,
    so it never polls a graph that does not exist yet."""
    from app.seeds.startup import prepare
    try:
        prepare(settings)
    except Exception:
        log.exception("startup data failed; the API stays up, /readyz reports data: false")
        return
    with lock:
        if stopping.is_set():
            return
        app.state.data_ready.set()
        _start_worker(app, settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Starts the in-process orchestrator worker when enabled, and stops it cleanly on shutdown.
    Settings honour a test override of get_settings, so a test client never starts a worker on the dev graph."""
    settings = app.dependency_overrides.get(get_settings, get_settings)()
    app.state.orchestrator = None
    stopping, lock = threading.Event(), threading.Lock()
    if settings.startup_data == "none":
        _start_worker(app, settings)
    else:
        app.state.data_ready = threading.Event()
        threading.Thread(target=_prepare_then_start, args=(app, settings, stopping, lock),
                         name="startup-data", daemon=True).start()
    try:
        yield
    finally:
        with lock:
            stopping.set()
            app.state.data_ready = None
        if app.state.orchestrator is not None:
            app.state.orchestrator.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="Graphathon incident API", version="0.2.0", description=DESCRIPTION, lifespan=lifespan)
    errors.install(app)
    for module in (health, alerts, incidents, investigations, actions, memories, services, demo):
        app.include_router(module.router)
    app.add_middleware(RequestContextMiddleware, max_body_bytes=settings.max_request_bytes)
    return app


app = create_app()
