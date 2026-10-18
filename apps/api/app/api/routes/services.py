from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app import auth
from app.api.deps import NowMs, RepoDep, require
from app.api.errors import ERROR_RESPONSES
from app.api.models import ServiceContext
from app.auth import Principal
from app.ids import ServiceIdPath
from app.services import service_context

router = APIRouter(prefix="/api/services", tags=["services"], responses=ERROR_RESPONSES)


@router.get("/{service_id}/context", response_model=ServiceContext)
def get_service_context(service_id: ServiceIdPath, repo: RepoDep, now_ms: NowMs,
                        _: Annotated[Principal, Depends(require(auth.READ))],
                        depth: Annotated[int, Query(ge=1, le=3)] = 2,
                        deployment_days: Annotated[int, Query(ge=1, le=90)] = 30,
                        limit: Annotated[int, Query(ge=1, le=100)] = 50) -> ServiceContext:
    """Owners, DEPENDS_ON neighbourhood (bounded depth), decisions in effect now, runbooks, recent deployments."""
    return service_context.get_context(repo, service_id, depth=depth, deployment_days=deployment_days,
                                       limit=limit, now_ms=now_ms)
