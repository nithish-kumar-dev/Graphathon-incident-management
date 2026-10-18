from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app import auth
from app.api.deps import NowMs, RepoDep, SettingsDep, require
from app.api.errors import ERROR_RESPONSES
from app.api.models import AlertIn, AlertIngestResult
from app.auth import Principal
from app.services import alerts

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.post("", response_model=AlertIngestResult, status_code=201, responses={
    200: {"model": AlertIngestResult, "description": "Duplicate within the window, or an exact replay"},
    **ERROR_RESPONSES})
def ingest_alert(body: AlertIn, response: Response, repo: RepoDep, settings: SettingsDep, now_ms: NowMs,
                 principal: Annotated[Principal, Depends(require(auth.INGEST))]) -> AlertIngestResult:
    """Ingest one synthetic alert. Idempotent on `source_ref`; deduplicated per tenant/env by `fingerprint`
    within `ALERT_DEDUP_WINDOW_S`. New alerts attach to the open incident for the service or open one."""
    out = alerts.ingest(repo, body, principal, settings, now_ms)
    if not out.created:
        response.status_code = 200
    return out.result
