from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app import auth
from app.api.deps import NowMs, RepoDep, require
from app.api.errors import ERROR_RESPONSES
from app.api.models import InvestigationIn, InvestigationOut
from app.auth import Principal
from app.ids import InvestigationIdPath
from app.services import investigations

router = APIRouter(prefix="/api/investigations", tags=["investigations"], responses=ERROR_RESPONSES)


@router.post("", response_model=InvestigationOut, status_code=201,
             responses={200: {"model": InvestigationOut, "description": "An active investigation already exists"}})
def create_investigation(body: InvestigationIn, response: Response, repo: RepoDep, now_ms: NowMs,
                         principal: Annotated[Principal, Depends(require(auth.INVESTIGATE))]) -> InvestigationOut:
    """Create an investigation (status `queued`). The orchestrator worker claims it and runs it
    (`running` -> completed / awaiting_review / escalated / inconclusive / failed / timed_out).
    `recommendation_only` never executes anything; `simulation` may later run allowlisted simulated actions."""
    out, created = investigations.create(repo, body, principal, now_ms)
    if not created:
        response.status_code = 200
    return out


@router.get("/{investigation_id}", response_model=InvestigationOut)
def get_investigation(investigation_id: InvestigationIdPath, repo: RepoDep,
                      _: Annotated[Principal, Depends(require(auth.READ))]) -> InvestigationOut:
    """Status, per-branch retrieval state, findings with claim types and confidence, the gate decision with
    its violations, proposed actions (AgentAction nodes PART_OF the session), and only evidence ids that exist."""
    return investigations.get(repo, investigation_id)
