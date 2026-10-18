"""Investigation records (AgentSession). The API creates them `queued`; the Phase 4 orchestrator worker
(app/orchestrator) claims and runs them, and writes the outcome read back here."""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api import models as m
from app.api.errors import Conflict, NotFound
from app.auth import Principal
from app.domain.actions import canonical_json
from app.graph.repository import GraphRepository
from app.graph.repository import now_ms as wall_clock_ms
from app.ids import new_id
from app.orchestrator import events as run_events
from app.rag.retrieval import RunRetrieval
from app.services import actions as action_service
from app.services.incidents import add_timeline, evidence_ref, require_incident

log = logging.getLogger(__name__)

ACTIVE = {"queued", "running", "awaiting_review"}
BRANCHES = ("graph_context", "memory_context", "telemetry_context")


class StoredFinding(BaseModel):
    """Shape of AgentSession.findings_json entries (written by app/orchestrator/persist.py).
    `evidence_ids` are the supporting ids; the other fields are optional for older records."""
    model_config = ConfigDict(extra="forbid")
    claim_type: m.ClaimType
    statement: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    contradicting_evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    uncertainty: str | None = Field(default=None, max_length=1000)


class StoredBranch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: m.BranchStatus
    detail: str | None = Field(default=None, max_length=500)


def create(repo: GraphRepository, body: m.InvestigationIn, principal: Principal,
           now_ms: int) -> tuple[m.InvestigationOut, bool]:
    inc = require_incident(repo, body.incident_id)
    if inc["status"] == "resolved":
        raise Conflict("incident is resolved", code="incident_resolved")
    sessions = repo.neighbors("Incident", body.incident_id, "INVESTIGATES", "AgentSession", outgoing=False,
                              order_by="started_at_ms", descending=True, limit=20)
    active = [s for s in sessions if s.get("status") in ACTIVE]
    if active:
        if active[0]["mode"] != body.mode:
            raise Conflict(f"investigation {active[0]['id']} is already active in mode {active[0]['mode']}",
                           code="investigation_in_progress")
        return get(repo, active[0]["id"]), False

    ses_id = new_id(repo.scope.tenant_id, "AgentSession", now_ms)
    repo.merge_node("AgentSession", ses_id, {
        "thread_id": f"inv-{ses_id.rsplit('.', 1)[1]}", "run_id": ses_id.rsplit(".", 1)[1], "mode": body.mode,
        "status": "queued", "started_at_ms": now_ms, "revision_count": 0, "requested_by": principal.user_id,
        "source": "human",
        "branch_status_json": canonical_json({b: {"status": "pending"} for b in BRANCHES}),
    }, at_ms=now_ms)
    repo.merge_edge("AgentSession", ses_id, "INVESTIGATES", "Incident", body.incident_id, at_ms=now_ms)
    add_timeline(repo, body.incident_id, "investigation_requested", principal.user_id,
                 f"{body.mode} investigation requested", now_ms, ref_id=ses_id)
    if inc["status"] == "open":
        repo.update_node("Incident", body.incident_id, {"status": "investigating"}, at_ms=now_ms)
        add_timeline(repo, body.incident_id, "status_change", principal.user_id, "status open -> investigating", now_ms)
    return get(repo, ses_id), True


def get(repo: GraphRepository, investigation_id: str, now_ms: int | None = None) -> m.InvestigationOut:
    s = repo.get_node("AgentSession", investigation_id)
    if s is None:
        raise NotFound(f"investigation {investigation_id} not found")
    now_ms = now_ms or wall_clock_ms()
    incidents = repo.neighbors("AgentSession", investigation_id, "INVESTIGATES", "Incident", outgoing=True, limit=1)
    warnings: list[str] = []

    findings_raw: list[StoredFinding] = []
    if s.get("findings_json"):
        try:
            findings_raw = [StoredFinding.model_validate(f) for f in json.loads(s["findings_json"])]
        except (ValueError, ValidationError):
            log.warning("unreadable findings_json", extra={"investigation_id": investigation_id})
            warnings.append("stored findings failed validation and were withheld")

    cited = {i for f in findings_raw for i in (*f.evidence_ids, *f.contradicting_evidence_ids)}
    evidence = {k: evidence_ref(v) for k, v in repo.get_nodes("Evidence", [i for i in cited if _safe_id(i)]).items()}
    findings = []
    for f in findings_raw:
        missing = [i for i in (*f.evidence_ids, *f.contradicting_evidence_ids) if i not in evidence]
        findings.append(m.FindingOut(
            claim_type=f.claim_type, statement=f.statement, evidence=[evidence[i] for i in f.evidence_ids if i in evidence],
            contradicting_evidence=[evidence[i] for i in f.contradicting_evidence_ids if i in evidence],
            confidence=f.confidence, uncertainty=f.uncertainty,
            integrity_warnings=[f"{len(missing)} cited evidence id(s) not found in the graph; omitted"] if missing else []))

    return m.InvestigationOut(
        id=s["id"], thread_id=s["thread_id"], incident_id=incidents[0]["id"] if incidents else None,
        incident_key=incidents[0]["key"] if incidents else None, mode=s["mode"], status=s["status"],
        requested_by=s.get("requested_by"), started_at=m.to_dt(s["started_at_ms"]), ended_at=m.to_dt(s.get("ended_at_ms")),
        revision_count=s.get("revision_count") or 0, branches=_branches(s, load_events(repo, investigation_id), warnings),
        findings=findings, evidence_refs=[evidence[i] for i in sorted(evidence)],
        summary=s.get("summary"), investigator=s.get("investigator"), overall_uncertainty=s.get("overall_uncertainty"),
        error=s.get("error"), gate=_gate(s, warnings), proposed_actions=_actions(repo, investigation_id, now_ms, warnings),
        integrity_warnings=warnings)


def list_for_incident(repo: GraphRepository, incident_id: str, limit: int) -> m.InvestigationList:
    require_incident(repo, incident_id)
    rows = repo.neighbors("Incident", incident_id, "INVESTIGATES", "AgentSession", outgoing=False,
                          order_by="started_at_ms", descending=True, limit=limit)
    return m.InvestigationList(incident_id=incident_id, items=[m.InvestigationSummary(
        id=r["id"], mode=r["mode"], status=r["status"], requested_by=r.get("requested_by"),
        started_at=m.to_dt(r["started_at_ms"]), ended_at=m.to_dt(r.get("ended_at_ms")),
        revision_count=r.get("revision_count") or 0, investigator=r.get("investigator"),
        summary=r.get("summary"), error=r.get("error")) for r in rows])


def events(repo: GraphRepository, investigation_id: str) -> m.InvestigationEvents:
    s = repo.get_node("AgentSession", investigation_id)
    if s is None:
        raise NotFound(f"investigation {investigation_id} not found")
    return m.InvestigationEvents(investigation_id=investigation_id, status=s["status"], events=[
        m.AgentEventOut(id=e["id"], kind=e["kind"], status=e["status"], at=m.to_dt(e["at_ms"]),
                        revision=e.get("revision") or 0, detail=e.get("detail"))
        for e in load_events(repo, investigation_id)])


def retrieval(repo: GraphRepository, investigation_id: str) -> RunRetrieval:
    """The context this run used, as stored when it finished. 404 while the run is live or if it kept none."""
    s = repo.get_node("AgentSession", investigation_id)
    if s is None:
        raise NotFound(f"investigation {investigation_id} not found")
    if not s.get("retrieval_json"):
        raise NotFound("this investigation has no stored retrieval context (still running, no branch completed, "
                       "or it predates snapshots)", code="no_snapshot")
    try:
        raw = json.loads(s["retrieval_json"])
        return RunRetrieval.model_validate({
            "investigation_id": investigation_id, "incident_id": raw["incident_id"],
            "as_of": m.to_dt(raw.get("as_of_ms")), "graph_context": raw.get("graph_context"),
            "memory_context": raw.get("memory_context"), "knowledge_context": raw.get("knowledge_context")})
    except (KeyError, ValueError, ValidationError):
        log.warning("unreadable retrieval_json", extra={"investigation_id": investigation_id})
        raise Conflict("the stored retrieval context failed validation", code="integrity_error") from None


def _gate(s: dict, warnings: list[str]) -> m.GateOut | None:
    if not s.get("gate_json"):
        return None
    try:
        return m.GateOut.model_validate(json.loads(s["gate_json"]))
    except (ValueError, ValidationError):
        warnings.append("stored gate result failed validation and was withheld")
        return None


def _actions(repo: GraphRepository, investigation_id: str, now_ms: int,
             warnings: list[str]) -> list[m.ProposedActionOut]:
    """AgentAction nodes PART_OF the session. Evidence comes from real SUPPORTED_BY edges only."""
    out = []
    for row in repo.session_actions(investigation_id):
        a = row["action"]
        try:
            out.append(action_service.action_out(repo, a, row["evidence"], now_ms))
        except (KeyError, ValueError, ValidationError):
            log.warning("unreadable AgentAction", extra={"investigation_id": investigation_id})
            warnings.append(f"action {a.get('id')} failed validation and was withheld")
    return out


def load_events(repo: GraphRepository, investigation_id: str) -> list[dict]:
    rows = repo.neighbors("AgentSession", investigation_id, "PART_OF", "AgentEvent", outgoing=False,
                          order_by="at_ms", limit=200)
    return sorted(rows, key=run_events.sort_key)


def _branches(s: dict, events: list[dict], warnings: list[str]) -> dict[str, m.BranchState]:
    default = "pending" if s["status"] == "queued" else "not_recorded"
    out = {b: m.BranchState(status=default) for b in BRANCHES}
    if s.get("branch_status_json"):
        try:
            raw = json.loads(s["branch_status_json"])
            for b in BRANCHES:
                if b in raw:
                    stored = StoredBranch.model_validate(raw[b])
                    out[b] = m.BranchState(status=stored.status, detail=stored.detail)
        except (ValueError, ValidationError):
            warnings.append("stored branch states failed validation")
    live = s["status"] == "running"
    for node, branch in run_events.BRANCH_OF.items():
        mine = [e for e in events if e["kind"] == node]
        if not mine:
            continue
        started = [e["at_ms"] for e in mine if e["status"] == "started"]
        closed = [e for e in mine if e["status"] != "started"]
        state = out[branch]
        update: dict = {"started_at": m.to_dt(min(started)) if started else None,
                        "ended_at": m.to_dt(max(e["at_ms"] for e in closed)) if closed else None}
        if live and state.status == "running" and closed:   # incremental view: the run has not persisted yet
            update |= {"status": closed[-1]["status"], "detail": closed[-1].get("detail")}
        out[branch] = state.model_copy(update=update)
    return out


def _safe_id(value: str) -> bool:
    from app.graph.schema import ID_PATTERN
    return isinstance(value, str) and bool(ID_PATTERN.match(value))
