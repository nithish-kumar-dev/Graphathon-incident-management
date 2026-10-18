"""Incident reads/updates, timeline, memories and graph explanation paths (no LLM involved)."""

from __future__ import annotations

import itertools

from app.api import models as m
from app.api.errors import Conflict, NotFound
from app.auth import Principal
from app.graph.repository import GraphRepository
from app.ids import new_id

TRANSITIONS: dict[str, set[str]] = {
    "open": {"investigating", "mitigated", "resolved"},
    "investigating": {"mitigated", "resolved"},
    "mitigated": {"investigating", "resolved"},
    "resolved": set(),
}


def require_incident(repo: GraphRepository, incident_id: str) -> dict:
    inc = repo.get_node("Incident", incident_id)
    if inc is None:
        raise NotFound(f"incident {incident_id} not found")
    return inc


def summary_from(inc: dict, service_ids: list[str], alert_count: int) -> m.IncidentSummary:
    return m.IncidentSummary(
        id=inc["id"], key=inc["key"], title=inc["title"], severity=inc["severity"], status=inc["status"],
        started_at=m.to_dt(inc["started_at_ms"]), resolved_at=m.to_dt(inc.get("resolved_at_ms")),
        affected_service_ids=sorted(service_ids), alert_count=alert_count)


def list_incidents(repo: GraphRepository, *, status: str | None, limit: int, offset: int) -> m.IncidentList:
    rows = repo.list_incidents(status=status, limit=limit, offset=offset)
    return m.IncidentList(items=[summary_from(r["incident"], r["service_ids"], r["alert_count"]) for r in rows],
                          limit=limit, offset=offset)


def evidence_ref(props: dict) -> m.EvidenceRef:
    return m.EvidenceRef(id=props["id"], kind=props["kind"], source_ref=props["source_ref"],
                         observed_at=m.to_dt(props.get("observed_at_ms")), excerpt=props.get("excerpt_redacted"))


def get_detail(repo: GraphRepository, incident_id: str, now_ms: int) -> m.IncidentDetail:
    inc = require_incident(repo, incident_id)
    services = repo.neighbors("Incident", incident_id, "AFFECTS", "Service", outgoing=True)
    alerts = repo.neighbors("Incident", incident_id, "HAS_ALERT", "Alert", outgoing=True, order_by="fired_at_ms")
    evidence = [
        m.EvidenceOut(**evidence_ref(r["evidence"]).model_dump(), observed_on_service_ids=sorted(r["observed_on"]),
                      refers_to_deployment_ids=sorted(r["refers_to"]))
        for r in repo.incident_evidence(incident_id)
    ]
    base = summary_from(inc, [s["id"] for s in services], len(alerts))
    return m.IncidentDetail(
        **base.model_dump(),
        affected_services=[m.ServiceRef(id=s["id"], name=s.get("name"), tier=s.get("tier")) for s in services],
        alerts=[m.AlertOut(id=a["id"], fingerprint=a["fingerprint"], severity=a["severity"],
                           fired_at=m.to_dt(a["fired_at_ms"]), last_fired_at=m.to_dt(a.get("last_fired_at_ms")),
                           dedup_count=a.get("dedup_count") or 0, summary=a.get("summary_redacted"),
                           source_ref=a.get("source_ref")) for a in alerts],
        evidence=evidence,
        explanation_paths=explanation_paths(repo, incident_id, {e.id: e for e in evidence}, now_ms),
        as_of=m.to_dt(now_ms),
    )


def explanation_paths(repo: GraphRepository, incident_id: str, evidence_by_id: dict[str, m.EvidenceRef],
                      now_ms: int) -> list[m.ExplanationPath]:
    rows = repo.rollback_candidates(incident_id, at_ms=now_ms)
    if not rows:
        return []
    deployments = repo.get_nodes("Deployment", [r["deployment_id"] for r in rows])
    runbooks = repo.get_nodes("Runbook", [i for r in rows for i in r["runbook_ids"]])
    missing_ev = {i for r in rows for i in r["evidence_ids"]} - set(evidence_by_id)
    evidence_by_id = {**evidence_by_id, **{k: evidence_ref(v) for k, v in repo.get_nodes("Evidence", missing_ev).items()}}
    decisions: dict[str, m.DecisionRef] = {}
    for target in {r["target_service_id"] for r in rows}:
        for d in repo.service_decisions(target):
            p = d["decision"]
            decisions[p["id"]] = m.DecisionRef(
                id=p["id"], title=p["title"], status=p["status"], required_approver_role=p.get("required_approver_role"),
                documented_in=[m.DocumentRef(**doc) for doc in d["documents"]])

    paths = []
    for r in rows:
        dep = deployments.get(r["deployment_id"])
        if dep is None:  # vanished between queries; never return an id we cannot show
            continue
        sp = r["service_path"]
        hops = [m.PathHop(from_label="Incident", from_id=incident_id, rel="AFFECTS", to_label="Service", to_id=sp[0])]
        hops += [m.PathHop(from_label="Service", from_id=a, rel="DEPENDS_ON", to_label="Service", to_id=b)
                 for a, b in itertools.pairwise(sp)]
        hops.append(m.PathHop(from_label="Deployment", from_id=dep["id"], rel="DEPLOYED_TO", to_label="Service",
                              to_id=r["target_service_id"]))
        ev_refs = [evidence_by_id[i] for i in r["evidence_ids"] if i in evidence_by_id]
        for ev in ev_refs:
            hops.append(m.PathHop(from_label="Incident", from_id=incident_id, rel="HAS_EVIDENCE", to_label="Evidence",
                                  to_id=ev.id))
            hops.append(m.PathHop(from_label="Evidence", from_id=ev.id, rel="REFERS_TO", to_label="Deployment",
                                  to_id=dep["id"]))
        if not ev_refs:
            continue
        decs = [decisions[i] for i in r["active_decision_ids"] if i in decisions]
        via = "is itself affected" if len(sp) == 1 else f"is reached from {sp[0]} via {len(sp) - 1} DEPENDS_ON hop(s)"
        paths.append(m.ExplanationPath(
            summary=(f"Deployment {dep['version']} of {r['target_service_id']} at "
                     f"{m.to_dt(dep['deployed_at_ms']).isoformat()} is referenced by incident evidence "
                     f"{', '.join(e.id for e in ev_refs)}; {r['target_service_id']} {via}. Correlation only."),
            hops=hops,
            target_service_id=r["target_service_id"],
            deployment=m.DeploymentRef(id=dep["id"], version=dep["version"], deployed_at=m.to_dt(dep["deployed_at_ms"]),
                                       status=dep.get("status"), source_ref=dep.get("source_ref")),
            evidence=ev_refs,
            governing_decisions=decs,
            runbooks=[m.RunbookRef(id=rb["id"], title=rb["title"], version=rb["version"], uri=rb.get("uri"),
                                   allowed_action_types=rb.get("allowed_action_types") or [])
                      for i in r["runbook_ids"] if (rb := runbooks.get(i))],
            approval_policy="policy_in_force" if decs else "no_active_policy_escalate",
        ))
    return paths


def update_incident(repo: GraphRepository, incident_id: str, upd: m.IncidentUpdate, principal: Principal,
                    now_ms: int) -> m.IncidentSummary:
    inc = require_incident(repo, incident_id)
    props: dict = {}
    events: list[tuple[str, str]] = []
    if upd.status and upd.status != inc["status"]:
        if upd.status not in TRANSITIONS[inc["status"]]:
            raise Conflict(f"cannot move incident from {inc['status']} to {upd.status}", code="invalid_transition")
        props["status"] = upd.status
        if upd.status == "resolved":
            props["resolved_at_ms"] = now_ms
        events.append(("status_change", f"status {inc['status']} -> {upd.status}"))
    if upd.severity and upd.severity != inc["severity"]:
        props["severity"] = upd.severity
        events.append(("severity_change", f"severity {inc['severity']} -> {upd.severity}"))
    if props:
        repo.update_node("Incident", incident_id, props, at_ms=now_ms)
        for type_, text in events:
            add_timeline(repo, incident_id, type_, principal.user_id, text, now_ms)
    inc = require_incident(repo, incident_id)
    services = repo.neighbors("Incident", incident_id, "AFFECTS", "Service", outgoing=True)
    alerts = repo.neighbors("Incident", incident_id, "HAS_ALERT", "Alert", outgoing=True)
    return summary_from(inc, [s["id"] for s in services], len(alerts))


def add_timeline(repo: GraphRepository, incident_id: str, type_: str, actor: str, summary: str, now_ms: int,
                 ref_id: str | None = None, source: str = "human") -> str:
    tl_id = new_id(repo.scope.tenant_id, "TimelineEvent", now_ms)
    repo.merge_node("TimelineEvent", tl_id, {"at_ms": now_ms, "type": type_, "actor": actor, "summary": summary,
                                             "ref_id": ref_id, "source": source}, at_ms=now_ms)
    repo.merge_edge("Incident", incident_id, "HAS_EVENT", "TimelineEvent", tl_id, at_ms=now_ms)
    return tl_id


def timeline(repo: GraphRepository, incident_id: str, limit: int) -> m.IncidentTimeline:
    require_incident(repo, incident_id)
    events = repo.neighbors("Incident", incident_id, "HAS_EVENT", "TimelineEvent", outgoing=True,
                            order_by="at_ms", limit=limit)
    return m.IncidentTimeline(incident_id=incident_id, events=[
        m.TimelineEventOut(id=e["id"], at=m.to_dt(e["at_ms"]), type=e["type"], actor=e.get("actor"),
                           summary=e.get("summary"), ref_id=e.get("ref_id")) for e in events])


def memories(repo: GraphRepository, incident_id: str, *, include_unverified: bool, limit: int) -> m.IncidentMemories:
    require_incident(repo, incident_id)
    own_services = {s["id"] for s in repo.neighbors("Incident", incident_id, "AFFECTS", "Service", outgoing=True)}
    rows = repo.incident_memories(incident_id, include_unverified=include_unverified, limit=limit)
    evidence = repo.get_nodes("Evidence", [i for r in rows for i in r["evidence_ids"]])
    responders = repo.get_nodes("Responder", [i for r in rows for i in r["validator_ids"]])

    out = []
    for r in rows:
        mem = r["memory"]
        verified = mem["verification_status"] == "verified"
        precedent = ("supports" if verified and mem["outcome"] == "successful"
                     else "warns_against" if verified and mem["outcome"] == "failed" else "none")
        out.append(m.MemoryOut(
            id=mem["id"], memory_type=mem["memory_type"], verification_status=mem["verification_status"],
            outcome=mem["outcome"], precedent=precedent, summary=mem["summary"],
            about_incident_id=r["incident_id"], about_incident_key=r["incident_key"],
            relation="same_incident" if r["incident_id"] == incident_id else "shared_service",
            shared_service_ids=sorted(own_services & set(r["incident_service_ids"])),
            grounded_in=[evidence_ref(evidence[i]) for i in sorted(r["evidence_ids"]) if i in evidence],
            validated_by=[m.ResponderRef(id=p["id"], handle=p["handle"], roles=p.get("roles") or [])
                          for i in sorted(r["validator_ids"]) if (p := responders.get(i))],
            derived_from_action_ids=sorted(r["action_ids"]),
            provenance_refs=mem.get("provenance_refs") or [],
            validated_at=m.to_dt(mem.get("validated_at_ms")), validation_method=mem.get("validation_method"),
            model_version=mem.get("model_version"),
        ))
    out.sort(key=lambda x: (x.verification_status != "verified", x.relation != "same_incident",
                            -(x.validated_at.timestamp() if x.validated_at else 0), x.id))
    return m.IncidentMemories(incident_id=incident_id, include_unverified=include_unverified, memories=out)
