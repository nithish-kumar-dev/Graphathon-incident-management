"""persist_outcome and notify_channel: the only graph writes an investigation run makes.

Idempotent by construction: every id is derived from the session id (or, for telemetry evidence, from
the observation's own stable id), every write is a MERGE, and existing AgentAction nodes are never
modified (a later review may have moved them on). Running persist twice creates no duplicates.
Memories are never touched here; verification goes only through app.services.memories.
"""

from __future__ import annotations

import logging

from app.agents.contracts import TelemetryContext
from app.domain.actions import canonical_json, spec_hash
from app.domain.redact import redact
from app.graph.repository import EndpointNotFound, GraphRepository
from app.graph.schema import SchemaViolation
from app.orchestrator.state import BRANCHES, TIMELINE_TYPE, InvestigationState

log = logging.getLogger("app.orchestrator")

ACTOR = "orchestrator"


def session_suffix(session_id: str) -> str:
    """`nova.ses.01k7…` -> `01k7…` (everything after `<tenant>.ses.`)."""
    return session_id.split(".", 2)[2]


def action_id(tenant_id: str, session_id: str, n: int) -> str:
    return f"{tenant_id}.act.{session_suffix(session_id)}.{n}.v1"


def proposal_id(tenant_id: str, session_id: str, n: int) -> str:
    return f"{tenant_id}.prop.{session_suffix(session_id)}.{n}"


def timeline_id(tenant_id: str, session_id: str) -> str:
    return f"{tenant_id}.tl.{session_suffix(session_id)}.outcome"


def action_spec(action: dict, tenant_id: str, env: str) -> dict:
    """The canonical spec an approval will be bound to (Phase 5). Order-independent via canonical_json."""
    return {"action_type": action["action_type"], "tenant_id": tenant_id, "env": env,
            "service_id": action["target_service_id"], "deployment_id": action.get("deployment_id"),
            "runbook_id": action["runbook_id"]}


def branch_status_json(state: InvestigationState) -> str:
    raw = state.get("retrieval_status") or {}
    required = state.get("required_branches")
    out = {}
    for b in BRANCHES:
        entry = raw.get(b)
        if entry is None:   # never recorded: the run stopped before or during retrieval
            if required is None:
                entry = {"status": "skipped", "detail": "run ended before retrieval"}
            elif b not in required:
                entry = {"status": "skipped", "detail": "not required for this incident"}
            else:
                entry = {"status": "failed", "detail": "run ended before this branch finished"}
        out[b] = {"status": entry["status"], **({"detail": entry["detail"][:500]} if entry.get("detail") else {})}
    return canonical_json(out)


def persist_outcome(repo: GraphRepository, state: InvestigationState, *, now_ms: int) -> list[str]:
    """Write evidence, the session outcome and accepted proposals. Returns the AgentAction ids."""
    session_id = state["session_id"]
    incident = state.get("incident") or None
    status = state["status"]
    gate = state.get("gate") or {}
    result = state.get("investigator_result") or {}
    output = result.get("output") or {}

    # 1. telemetry observations -> Evidence (kind metric, source agent), so findings can cite them.
    if incident and (state.get("retrieval_status") or {}).get("telemetry_context", {}).get("status") == "completed" \
            and state.get("telemetry_context"):
        _persist_telemetry(repo, incident["id"], TelemetryContext.model_validate(state["telemetry_context"]),
                           now_ms=now_ms)

    # 2. accepted proposals -> AgentAction (only on accept, and only for a terminal status that keeps them).
    action_ids: list[str] = []
    if gate.get("decision") == "accept" and status in {"completed", "awaiting_review"}:
        action_status = "pending_review" if state.get("mode") == "simulation" else "proposed"
        for n, action in enumerate(gate.get("proposed_actions") or [], start=1):
            action_ids.append(_persist_action(repo, session_id, n, action, mode=state["mode"],
                                              status=action_status, now_ms=now_ms))

    # 3. the session outcome
    findings = [{
        "claim_type": h["claim_type"], "statement": h["statement"],
        "evidence_ids": list(h.get("supporting_evidence_ids") or []),
        "contradicting_evidence_ids": list(h.get("contradicting_evidence_ids") or []),
        "confidence": h.get("confidence"), "uncertainty": h.get("uncertainty") or None,
    } for h in (gate.get("hypotheses") or [])]
    props = {
        "status": status,
        "ended_at_ms": now_ms,
        "revision_count": int(state.get("revision") or 0),
        "branch_status_json": branch_status_json(state),
        "findings_json": canonical_json(findings),
        "investigator": state.get("investigator_name"),
        "summary": output.get("summary") if gate.get("decision") not in (None, "inconclusive") else None,
        "overall_uncertainty": output.get("overall_uncertainty") or None,
        "gate_json": canonical_json({"decision": gate["decision"], "violations": gate.get("violations") or []})
        if gate else None,
        "error": (state.get("error") or "")[:500] or None,
    }
    if not repo.update_node("AgentSession", session_id, props, at_ms=now_ms):
        raise SchemaViolation(f"AgentSession {session_id} vanished before its outcome was persisted")
    return action_ids


def notify_channel(repo: GraphRepository, state: InvestigationState, *, now_ms: int) -> str | None:
    """One TimelineEvent on the incident (deterministic id) plus one JSON log line. No network."""
    status, session_id = state["status"], state["session_id"]
    incident = state.get("incident") or None
    event_type = TIMELINE_TYPE.get(status, "investigation_failed")
    gate = state.get("gate") or {}
    summary = _summary(state, gate)
    log.info("investigation %s: %s", status, summary, extra={
        "investigation_id": session_id, "incident_id": incident["id"] if incident else None, "outcome": status})
    if not incident:
        return None
    tl_id = timeline_id(repo.scope.tenant_id, session_id)
    repo.merge_node("TimelineEvent", tl_id, {"at_ms": now_ms, "type": event_type, "actor": ACTOR,
                                             "summary": summary[:300], "ref_id": session_id, "source": "agent"},
                    at_ms=now_ms)
    repo.merge_edge("Incident", incident["id"], "HAS_EVENT", "TimelineEvent", tl_id, at_ms=now_ms)
    return tl_id


# ---------------------------------------------------------------------------------------------
def _persist_telemetry(repo: GraphRepository, incident_id: str, tel: TelemetryContext, *, now_ms: int) -> None:
    prefix = f"{repo.scope.tenant_id}.ev."
    for obs in tel.observations:
        if not obs.id.startswith(prefix) or not obs.service_id.startswith(f"{repo.scope.tenant_id}."):
            log.warning("telemetry observation outside tenant scope skipped", extra={"incident_id": incident_id})
            continue
        try:
            repo.merge_node("Evidence", obs.id, {
                "kind": "metric", "source": "agent", "source_ref": obs.source_ref, "observed_at_ms": obs.observed_at_ms,
                "excerpt_redacted": redact(obs.summary)}, at_ms=now_ms)
            repo.merge_edge("Incident", incident_id, "HAS_EVIDENCE", "Evidence", obs.id, at_ms=now_ms)
            repo.merge_edge("Evidence", obs.id, "OBSERVED_ON", "Service", obs.service_id, at_ms=now_ms)
        except (EndpointNotFound, SchemaViolation) as exc:
            log.warning("telemetry evidence not linked: %s", exc, extra={"incident_id": incident_id})


def _persist_action(repo: GraphRepository, session_id: str, n: int, action: dict, *, mode: str, status: str,
                    now_ms: int) -> str:
    tenant, env = repo.scope.tenant_id, repo.scope.env
    act_id = action_id(tenant, session_id, n)
    if repo.get_node("AgentAction", act_id) is None:   # create-only: never reset a reviewed action
        spec = canonical_json(action_spec(action, tenant, env))
        repo.merge_node("AgentAction", act_id, {
            "proposal_id": proposal_id(tenant, session_id, n), "version": 1, "action_type": action["action_type"],
            "spec_json": spec, "spec_hash": spec_hash(spec), "target_service_id": action["target_service_id"],
            "deployment_id": action.get("deployment_id"), "runbook_id": action["runbook_id"],
            "rationale": action["rationale"], "risk": action.get("risk") or "medium", "mode": mode, "status": status,
            "source": "agent"}, at_ms=now_ms)
    repo.merge_edge("AgentAction", act_id, "PART_OF", "AgentSession", session_id, at_ms=now_ms)
    for label, rel, target in [("Service", "TARGETS", action["target_service_id"])] + \
            [("Evidence", "SUPPORTED_BY", e) for e in action.get("evidence_ids") or []]:
        try:
            repo.merge_edge("AgentAction", act_id, rel, label, target, at_ms=now_ms)
        except (EndpointNotFound, SchemaViolation) as exc:
            log.warning("action edge not written: %s", exc, extra={"investigation_id": session_id})
    return act_id


def _summary(state: InvestigationState, gate: dict) -> str:
    status = state["status"]
    if status in {"failed", "timed_out"}:
        return f"investigation {status}: {state.get('error') or 'unknown error'}"
    n_h, n_a = len(gate.get("hypotheses") or []), len(gate.get("proposed_actions") or [])
    parts = [f"gate {gate.get('decision', 'n/a')}", f"{n_h} hypothesis(es)"]
    if status in {"completed", "awaiting_review"} and gate.get("decision") == "accept":
        parts.append(f"{n_a} proposed action(s)")
    if gate.get("violations"):
        parts.append(f"{len(gate['violations'])} violation(s)")
    return f"investigation {status} ({', '.join(parts)}; revisions {state.get('revision') or 0})"

