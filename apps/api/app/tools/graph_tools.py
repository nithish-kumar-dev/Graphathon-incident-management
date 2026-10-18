"""Named, read-only, bounded graph tools (Phase 3). Phase 4 agents call these via `run_tool`.

- **Read-only by construction.** Tools receive a repository whose graph handle has no write method
  (`ReadOnlyGraph`), so they cannot write even by mistake.
- **Bounded.** Every argument is a strict Pydantic model: depth at most 3, result counts and time windows
  capped. The repository applies tenant/env scope and a per-query timeout.
- **No invented Cypher.** Tools use only the named queries in app/graph/queries, verified on FalkorDB 4.22.
- **Traceable output.** Results are typed and carry real graph ids. `truncated` says when a limit cut
  results off.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from falkordb import Graph
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api import models as m
from app.api.errors import NotFound
from app.graph.client import ReadOnlyViolation
from app.graph.repository import GraphRepository
from app.ids import IncidentId, ServiceId
from app.services import incidents as incident_svc
from app.services.service_context import _deps, in_effect

MAX_DEPTH = 3


class ToolArgumentError(ValueError):
    """Arguments failed validation. Message lists field locations only, never values."""


class ReadOnlyGraph:
    """Exposes only GRAPH.RO_QUERY. Any write attempt fails before reaching the server."""

    def __init__(self, graph: Graph) -> None:
        self._graph = graph
        self.name = graph.name

    def ro_query(self, *args, **kwargs):
        return self._graph.ro_query(*args, **kwargs)

    def query(self, *args, **kwargs):
        raise ReadOnlyViolation("graph tools are read-only")


@dataclass(frozen=True)
class ToolContext:
    repo: GraphRepository
    now_ms: int

    @classmethod
    def read_only(cls, graph: Graph, scope, *, now_ms: int, timeout_ms: int = 1500) -> ToolContext:
        return cls(GraphRepository(ReadOnlyGraph(graph), scope, timeout_ms=timeout_ms), now_ms)


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Result(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    truncated: bool = False


# ---------------------------------------------------------------- expand_dependencies
class ExpandDependenciesArgs(_Args):
    service_id: ServiceId
    direction: Literal["downstream", "upstream"] = "downstream"
    max_depth: Annotated[int, Field(ge=1, le=MAX_DEPTH)] = 2
    limit: Annotated[int, Field(ge=1, le=50)] = 25


class DependenciesResult(_Result):
    service_id: str
    direction: str
    max_depth: int
    items: list[m.DependencyOut]


def expand_dependencies(ctx: ToolContext, a: ExpandDependenciesArgs) -> DependenciesResult:
    _require(ctx, "Service", a.service_id)
    rows = ctx.repo.service_neighbourhood(a.service_id, upstream=a.direction == "upstream", depth=a.max_depth,
                                          limit=a.limit * 4)
    items = _deps(rows)
    return DependenciesResult(tool="expand_dependencies", service_id=a.service_id, direction=a.direction,
                              max_depth=a.max_depth, items=items[:a.limit], truncated=len(items) > a.limit)


# ---------------------------------------------------------------- get_recent_deployments
class RecentDeploymentsArgs(_Args):
    service_ids: Annotated[list[ServiceId], Field(min_length=1, max_length=10)]
    window_hours: Annotated[int, Field(ge=1, le=720)] = 72
    limit: Annotated[int, Field(ge=1, le=50)] = 20


class DeploymentHit(m.DeploymentRef):
    service_id: str


class DeploymentsResult(_Result):
    window_hours: int
    items: list[DeploymentHit]


def get_recent_deployments(ctx: ToolContext, a: RecentDeploymentsArgs) -> DeploymentsResult:
    since = ctx.now_ms - a.window_hours * 3_600_000
    hits: list[DeploymentHit] = []
    for sid in dict.fromkeys(a.service_ids):
        for d in ctx.repo.neighbors("Service", sid, "DEPLOYED_TO", "Deployment", outgoing=False,
                                    order_by="deployed_at_ms", descending=True, limit=a.limit + 1):
            if since <= d["deployed_at_ms"] <= ctx.now_ms:
                hits.append(DeploymentHit(id=d["id"], version=d["version"], deployed_at=m.to_dt(d["deployed_at_ms"]),
                                          status=d.get("status"), source_ref=d.get("source_ref"), service_id=sid))
    hits.sort(key=lambda h: (h.deployed_at, h.id), reverse=True)
    return DeploymentsResult(tool="get_recent_deployments", window_hours=a.window_hours, items=hits[:a.limit],
                             truncated=len(hits) > a.limit)


# ---------------------------------------------------------------- get_incident_evidence
class IncidentEvidenceArgs(_Args):
    incident_id: IncidentId
    limit: Annotated[int, Field(ge=1, le=100)] = 50


class EvidenceResult(_Result):
    incident_id: str
    items: list[m.EvidenceOut]


def get_incident_evidence(ctx: ToolContext, a: IncidentEvidenceArgs) -> EvidenceResult:
    _require(ctx, "Incident", a.incident_id)
    rows = ctx.repo.incident_evidence(a.incident_id, limit=a.limit + 1)
    items = [m.EvidenceOut(**incident_svc.evidence_ref(r["evidence"]).model_dump(),
                           observed_on_service_ids=sorted(r["observed_on"]),
                           refers_to_deployment_ids=sorted(r["refers_to"])) for r in rows]
    return EvidenceResult(tool="get_incident_evidence", incident_id=a.incident_id, items=items[:a.limit],
                          truncated=len(items) > a.limit)


# ---------------------------------------------------------------- get_service_ownership
class ServiceOwnershipArgs(_Args):
    service_id: ServiceId


class OwnershipResult(_Result):
    service_id: str
    teams: list[m.TeamOut]


def get_service_ownership(ctx: ToolContext, a: ServiceOwnershipArgs) -> OwnershipResult:
    _require(ctx, "Service", a.service_id)
    teams = [m.TeamOut(id=t["team_id"], name=t["team_name"],
                       members=[m.ResponderRef(id=r["id"], handle=r["handle"], roles=r.get("roles") or [])
                                for r in sorted(t["members"], key=lambda x: x["id"])])
             for t in ctx.repo.service_owners(a.service_id)]
    return OwnershipResult(tool="get_service_ownership", service_id=a.service_id, teams=teams)


# ---------------------------------------------------------------- get_current_decisions
class CurrentDecisionsArgs(_Args):
    service_id: ServiceId


class DecisionsResult(_Result):
    service_id: str
    as_of: datetime
    items: list[m.DecisionOut]


def get_current_decisions(ctx: ToolContext, a: CurrentDecisionsArgs) -> DecisionsResult:
    _require(ctx, "Service", a.service_id)
    items = [
        m.DecisionOut(id=p["id"], title=p["title"], statement=p["statement"], status=p["status"],
                      effective_from=m.to_dt(p["effective_from_ms"]), effective_to=m.to_dt(p.get("effective_to_ms")),
                      required_approver_role=p.get("required_approver_role"),
                      documented_in=[m.DocumentRef(**doc) for doc in d["documents"]], supersedes=sorted(d["supersedes"]))
        for d in ctx.repo.service_decisions(a.service_id) if in_effect(p := d["decision"], ctx.now_ms)
    ]
    return DecisionsResult(tool="get_current_decisions", service_id=a.service_id, as_of=m.to_dt(ctx.now_ms),
                           items=items)


# ---------------------------------------------------------------- get_applicable_runbooks
class ApplicableRunbooksArgs(_Args):
    service_id: ServiceId
    action_type: Annotated[str | None, Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")] = None
    limit: Annotated[int, Field(ge=1, le=20)] = 10


class RunbooksResult(_Result):
    service_id: str
    items: list[m.RunbookRef]


def get_applicable_runbooks(ctx: ToolContext, a: ApplicableRunbooksArgs) -> RunbooksResult:
    _require(ctx, "Service", a.service_id)
    rows = ctx.repo.neighbors("Service", a.service_id, "APPLIES_TO", "Runbook", outgoing=False, limit=a.limit + 1)
    items = [m.RunbookRef(id=r["id"], title=r["title"], version=r["version"], uri=r.get("uri"),
                          allowed_action_types=r.get("allowed_action_types") or []) for r in rows
             if a.action_type is None or a.action_type in (r.get("allowed_action_types") or [])]
    return RunbooksResult(tool="get_applicable_runbooks", service_id=a.service_id, items=items[:a.limit],
                          truncated=len(items) > a.limit)


# ---------------------------------------------------------------- get_verified_memories
class VerifiedMemoriesArgs(_Args):
    incident_id: IncidentId
    include_failed: bool = True
    limit: Annotated[int, Field(ge=1, le=20)] = 10


class MemoriesResult(_Result):
    incident_id: str
    items: list[m.MemoryOut]
    excluded_unverified: int


def get_verified_memories(ctx: ToolContext, a: VerifiedMemoriesArgs) -> MemoriesResult:
    """Only verified memories with provenance. Drafts, rejected and superseded ones are counted, never returned."""
    every = incident_svc.memories(ctx.repo, a.incident_id, include_unverified=True, limit=50)
    verified = [x for x in every.memories if x.verification_status == "verified" and x.grounded_in
                and (x.validated_by or x.validation_method == "ground_truth")
                and (a.include_failed or x.outcome != "failed")]
    return MemoriesResult(tool="get_verified_memories", incident_id=a.incident_id, items=verified[:a.limit],
                          excluded_unverified=sum(1 for x in every.memories if x.verification_status != "verified"),
                          truncated=len(verified) > a.limit)


# ---------------------------------------------------------------- get_explanation_path
class ExplanationPathArgs(_Args):
    incident_id: IncidentId


class ExplanationResult(_Result):
    incident_id: str
    paths: list[m.ExplanationPath]


def get_explanation_path(ctx: ToolContext, a: ExplanationPathArgs) -> ExplanationResult:
    _require(ctx, "Incident", a.incident_id)
    evidence = {r["evidence"]["id"]: incident_svc.evidence_ref(r["evidence"])
                for r in ctx.repo.incident_evidence(a.incident_id)}
    return ExplanationResult(tool="get_explanation_path", incident_id=a.incident_id,
                             paths=incident_svc.explanation_paths(ctx.repo, a.incident_id, evidence, ctx.now_ms))


# ---------------------------------------------------------------- registry
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: type[_Args]
    fn: object


TOOLS: dict[str, ToolSpec] = {t.name: t for t in [
    ToolSpec("expand_dependencies", "Services reachable over DEPENDS_ON (downstream or upstream), depth <= 3.",
             ExpandDependenciesArgs, expand_dependencies),
    ToolSpec("get_recent_deployments", "Deployments to up to 10 services within a time window.",
             RecentDeploymentsArgs, get_recent_deployments),
    ToolSpec("get_incident_evidence", "Evidence attached to an incident, with source refs.",
             IncidentEvidenceArgs, get_incident_evidence),
    ToolSpec("get_service_ownership", "Owning teams and their responders.", ServiceOwnershipArgs, get_service_ownership),
    ToolSpec("get_current_decisions", "Policy decisions in effect now for a service, with documents.",
             CurrentDecisionsArgs, get_current_decisions),
    ToolSpec("get_applicable_runbooks", "Runbooks that apply to a service, optionally for one action type.",
             ApplicableRunbooksArgs, get_applicable_runbooks),
    ToolSpec("get_verified_memories", "Verified, provenance-checked memories relevant to an incident.",
             VerifiedMemoriesArgs, get_verified_memories),
    ToolSpec("get_explanation_path", "Evidence-backed graph paths from an incident to candidate deployments.",
             ExplanationPathArgs, get_explanation_path),
]}


def run_tool(ctx: ToolContext, name: str, raw_args: dict) -> _Result:
    spec = TOOLS.get(name)
    if spec is None:
        raise ToolArgumentError(f"unknown tool {name!r}")
    try:
        args = spec.args.model_validate(raw_args)
    except ValidationError as exc:
        raise ToolArgumentError("; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())) from None
    return spec.fn(ctx, args)


def _require(ctx: ToolContext, label: str, node_id: str) -> None:
    if ctx.repo.get_node(label, node_id) is None:
        raise NotFound(f"{label.lower()} {node_id} not found")
