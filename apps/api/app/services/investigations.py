"""Investigation records (AgentSession). The API creates them `queued`; the Phase 4 orchestrator worker
(app/orchestrator) claims and runs them, and writes the outcome read back here."""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api import models as m
from app.api.errors import Conflict, NotFound
from app.auth import Principal
from app.domain.actions import canonical_json, spec_hash
from app.graph.repository import GraphRepository
from app.ids import new_id
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


def get(repo: GraphRepository, investigation_id: str) -> m.InvestigationOut:
    s = repo.get_node("AgentSession", investigation_id)
    if s is None:
        raise NotFound(f"investigation {investigation_id} not found")
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
        revision_count=s.get("revision_count") or 0, branches=_branches(s, warnings),
        findings=findings, evidence_refs=[evidence[i] for i in sorted(evidence)],
        summary=s.get("summary"), investigator=s.get("investigator"), overall_uncertainty=s.get("overall_uncertainty"),
        error=s.get("error"), gate=_gate(s, warnings), proposed_actions=_actions(repo, investigation_id, warnings),
        integrity_warnings=warnings)


def _gate(s: dict, warnings: list[str]) -> m.GateOut | None:
    if not s.get("gate_json"):
        return None
    try:
        return m.GateOut.model_validate(json.loads(s["gate_json"]))
    except (ValueError, ValidationError):
        warnings.append("stored gate result failed validation and was withheld")
        return None


def _actions(repo: GraphRepository, investigation_id: str, warnings: list[str]) -> list[m.ProposedActionOut]:
    """AgentAction nodes PART_OF the session. Evidence comes from real SUPPORTED_BY edges only."""
    out = []
    for row in repo.session_actions(investigation_id):
        a = row["action"]
        try:
            spec = json.loads(a["spec_json"])
            out.append(m.ProposedActionOut(
                id=a["id"], proposal_id=a["proposal_id"], version=a["version"], action_type=a["action_type"],
                status=a["status"], mode=a["mode"], target_service_id=a["target_service_id"],
                deployment_id=a.get("deployment_id") or spec.get("deployment_id"),
                runbook_id=a.get("runbook_id") or spec.get("runbook_id"), risk=a.get("risk"),
                rationale=a.get("rationale"), spec=spec, spec_hash=a["spec_hash"],
                evidence=[evidence_ref(e) for e in sorted(row["evidence"], key=lambda e: e["id"])],
                integrity_warnings=[] if spec_hash(a["spec_json"]) == a["spec_hash"] else
                ["spec_hash does not match spec_json"]))
        except (KeyError, ValueError, ValidationError):
            log.warning("unreadable AgentAction", extra={"investigation_id": investigation_id})
            warnings.append(f"action {a.get('id')} failed validation and was withheld")
    return out


def _branches(s: dict, warnings: list[str]) -> dict[str, m.BranchState]:
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
    return out


def _safe_id(value: str) -> bool:
    from app.graph.schema import ID_PATTERN
    return isinstance(value, str) and bool(ID_PATTERN.match(value))
