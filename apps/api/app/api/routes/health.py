from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.deps import SettingsDep
from app.db import postgres
from app.graph import client as graph_client

log = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(settings: SettingsDep) -> JSONResponse:
    checks = {
        "falkordb": graph_client.ping_url(settings.falkordb_url),
        "postgres": postgres.ping(settings.postgres_dsn.get_secret_value()),
    }
    ready = all(checks.values())
    if not ready:
        log.warning("readiness failed: %s", sorted(k for k, v in checks.items() if not v))
    return JSONResponse(status_code=200 if ready else 503,
                        content={"status": "ready" if ready else "unavailable", "checks": checks})
