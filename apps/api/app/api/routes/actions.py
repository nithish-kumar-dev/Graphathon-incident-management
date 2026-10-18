from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app import auth
from app.api.deps import NowMs, RepoDep, require
from app.api.errors import ERROR_RESPONSES
from app.api.models import ProposedActionOut, ReviewIn, ReviewResult
from app.auth import Principal
from app.ids import ActionIdPath
from app.services import actions

router = APIRouter(prefix="/api/actions", tags=["actions"], responses=ERROR_RESPONSES)


def get_resumer(request: Request, repo: RepoDep) -> actions.Resumer | None:
    """Continues the paused run through the in-process orchestrator, if this process runs one."""
    worker = getattr(request.app.state, "orchestrator", None)
    return None if worker is None else (lambda session_id: worker.resume_review(session_id, repo.scope))


ResumerDep = Annotated[actions.Resumer | None, Depends(get_resumer)]


@router.get("/{action_id}", response_model=ProposedActionOut)
def get_action(action_id: ActionIdPath, repo: RepoDep, now_ms: NowMs,
               _: Annotated[Principal, Depends(require(auth.READ))]) -> ProposedActionOut:
    """One proposed action with its evidence, required approver role, review records and simulated outcome."""
    return actions.get_action(repo, action_id, now_ms)


@router.post("/{action_id}/review", response_model=ReviewResult)
def review_action(action_id: ActionIdPath, body: ReviewIn, repo: RepoDep, now_ms: NowMs, resume: ResumerDep,
                  principal: Annotated[Principal, Depends(require(auth.REVIEW))]) -> ReviewResult:
    """Decide a `pending_review` action (simulation runs only). APPROVE needs the role the governing Decision
    requires; the first decision wins (409 otherwise). The paused investigation is then resumed, and the restricted
    executor runs an approved `rollback_deployment_simulated` as a SIMULATION once, leaving a draft memory;
    nothing real is ever changed."""
    return actions.review(repo, action_id, body, principal, now_ms, resume)
