from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app import auth
from app.api.deps import EmbedderDep, GraphDep, NowMs, RepoDep, SettingsDep, require
from app.api.errors import ERROR_RESPONSES
from app.api.models import (
    IncidentDetail,
    IncidentList,
    IncidentMemories,
    IncidentStatus,
    IncidentSummary,
    IncidentTimeline,
    IncidentUpdate,
)
from app.auth import Principal
from app.graph.repository import Scope
from app.ids import IncidentIdPath
from app.rag.retrieval import RetrievalBundle, retrieve
from app.services import incidents
from app.tools.graph_tools import ToolContext

router = APIRouter(prefix="/api/incidents", tags=["incidents"], responses=ERROR_RESPONSES)
Reader = Annotated[Principal, Depends(require(auth.READ))]


@router.get("", response_model=IncidentList)
def list_incidents(repo: RepoDep, _: Reader, status: IncidentStatus | None = None,
                   limit: Annotated[int, Query(ge=1, le=100)] = 50,
                   offset: Annotated[int, Query(ge=0, le=10_000)] = 0) -> IncidentList:
    """Incidents in the caller's tenant/env, newest first."""
    return incidents.list_incidents(repo, status=status, limit=limit, offset=offset)


@router.get("/{incident_id}", response_model=IncidentDetail)
def get_incident(incident_id: IncidentIdPath, repo: RepoDep, now_ms: NowMs, _: Reader) -> IncidentDetail:
    """Incident with alerts, evidence (source refs) and graph explanation paths (real ids + relationship names)."""
    return incidents.get_detail(repo, incident_id, now_ms)


@router.patch("/{incident_id}", response_model=IncidentSummary)
def update_incident(incident_id: IncidentIdPath, body: IncidentUpdate, repo: RepoDep, now_ms: NowMs,
                    principal: Annotated[Principal, Depends(require(auth.WRITE))]) -> IncidentSummary:
    """Change status (forward-only transitions) and/or severity. Every change is recorded on the timeline."""
    return incidents.update_incident(repo, incident_id, body, principal, now_ms)


@router.get("/{incident_id}/timeline", response_model=IncidentTimeline)
def get_timeline(incident_id: IncidentIdPath, repo: RepoDep, _: Reader,
                 limit: Annotated[int, Query(ge=1, le=200)] = 200) -> IncidentTimeline:
    return incidents.timeline(repo, incident_id, limit)


@router.get("/{incident_id}/memories", response_model=IncidentMemories)
def get_memories(incident_id: IncidentIdPath, repo: RepoDep, _: Reader, include_unverified: bool = False,
                 limit: Annotated[int, Query(ge=1, le=50)] = 20) -> IncidentMemories:
    """Memories about this incident or incidents sharing an affected service. Verified only unless
    `include_unverified`; `precedent` says whether a memory supports or warns against an action."""
    return incidents.memories(repo, incident_id, include_unverified=include_unverified, limit=limit)


@router.get("/{incident_id}/retrieval", response_model=RetrievalBundle)
def get_retrieval(incident_id: IncidentIdPath, graph: GraphDep, settings: SettingsDep, now_ms: NowMs,
                  embedder: EmbedderDep, principal: Reader) -> RetrievalBundle:
    """Hybrid investigator context (graph + keyword + optional vector), read-only and tenant-scoped.
    Every item carries real graph ids, source refs, score components and a rationale. Knowledge chunks
    are `claim_type: context`, never causes. `steps` reports each step's status; if the embedding
    provider is down the vector step is `failed` and the response still succeeds (graph + keyword)."""
    ctx = ToolContext.read_only(graph, Scope(principal.tenant_id, principal.env), now_ms=now_ms,
                                timeout_ms=settings.graph_query_timeout_ms)
    return retrieve(ctx, incident_id, embedder=embedder, allowed_classifications=settings.allowed_classifications)
