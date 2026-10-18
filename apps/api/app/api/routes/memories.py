from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app import auth
from app.api.deps import NowMs, RepoDep, require
from app.api.errors import ERROR_RESPONSES, Forbidden
from app.api.models import MemoryReviewIn, MemoryReviewOut
from app.auth import Principal
from app.graph.repository import GraphRepository
from app.ids import MemoryIdPath
from app.services import memories

router = APIRouter(prefix="/api/memories", tags=["memories"], responses=ERROR_RESPONSES)
Reviewer = Annotated[Principal, Depends(require(auth.REVIEW))]


def _responder(principal: Principal) -> str:
    if not principal.responder_id:
        raise Forbidden("the reviewer has no responder identity", code="no_responder_identity")
    return principal.responder_id


def _out(repo: GraphRepository, memory_id: str) -> MemoryReviewOut:
    mem = repo.get_node("AgentMemory", memory_id) or {}
    return MemoryReviewOut(id=memory_id, verification_status=mem.get("verification_status", "unknown"),
                           outcome=mem.get("outcome", "unknown"))


@router.post("/{memory_id}/validate", response_model=MemoryReviewOut)
def validate_memory(memory_id: MemoryIdPath, body: MemoryReviewIn, repo: RepoDep, now_ms: NowMs,
                    principal: Reviewer) -> MemoryReviewOut:
    """Verify a draft memory with a human outcome. Only memories derived from an executed action qualify; once
    verified it may appear in future retrievals."""
    memories.validate_by_human(repo, memory_id, responder_id=_responder(principal), outcome=body.outcome,
                               now_ms=now_ms)
    return _out(repo, memory_id)


@router.post("/{memory_id}/reject", response_model=MemoryReviewOut)
def reject_memory(memory_id: MemoryIdPath, repo: RepoDep, now_ms: NowMs, principal: Reviewer) -> MemoryReviewOut:
    """Reject a draft memory so it can never be retrieved."""
    memories.reject(repo, memory_id, responder_id=_responder(principal), now_ms=now_ms)
    return _out(repo, memory_id)
