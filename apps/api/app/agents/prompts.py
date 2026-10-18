"""Prompt construction for the LLM investigator. Compact, id-first, and bounded in size.

The model sees only what is in InvestigatorInput, reduced to ids, source refs, short excerpts and
numbers. Long text is truncated. Telemetry is reduced to anomalous readings plus the latest normal
reading per service/metric, so the prompt stays small for a local 7B model.
"""

from __future__ import annotations

import json

from app.agents.contracts import ALLOWED_ACTION_TYPES, InvestigatorInput
from app.telemetry.synthetic import is_anomalous

SYSTEM_PROMPT = """You are an incident investigator for a synthetic demo company. You write a JSON object only.

Rules (a safety gate rejects anything that breaks them):
1. Cite only evidence ids listed in "citable_evidence_ids". Never invent ids. Every hypothesis needs at least
   one id in supporting_evidence_ids.
2. claim_type is "observed" (a reading you can see), "correlated" (timing or graph path links two things)
   or "hypothesis" (a possible explanation). Never use "confirmed": only humans confirm causes.
3. Explanation paths are correlations, not proof. Memories are precedent, not proof. Knowledge chunks are
   context only and are never evidence.
4. Propose actions only from an explanation path: action_type must be in "allowed_action_types" and in that
   path's runbook allowed_action_types; target_service_id is the path target; deployment_id is the path
   deployment id (always set it); runbook_id is the path runbook; evidence_ids come from the path evidence.
   Never repeat an
   action that a memory with precedent "warns_against" says failed. If no path exists, propose no actions.
5. Use recommendation language ("recommend", "consider"). Actions are proposals for human approval only.
6. Add an "observed" hypothesis for each anomalous telemetry signal (service + metric), citing its ids.
   Normal readings on the target or affected services are contradicting evidence for a correlation.
7. State uncertainty plainly. Keep confidence below 0.9. Keep statements short.
8. If "feedback" lists violations from a previous attempt, fix every one of them (drop the offending item
   if it cannot be fixed)."""

EXCERPT = 160
SUMMARY = 220


def _cut(text: str | None, n: int) -> str | None:
    if text is None:
        return None
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def build_user_content(inp: InvestigatorInput) -> str:
    gc, mc, kc, tc = inp.graph_context, inp.memory_context, inp.knowledge_context, inp.telemetry_context
    allowed = [a for a in inp.allowed_action_types if a in ALLOWED_ACTION_TYPES]
    doc: dict = {
        "incident": {"id": inp.incident_id, "key": inp.incident_key, "title": _cut(inp.incident_title, SUMMARY),
                     "tenant": inp.tenant_id, "env": inp.env, "mode": inp.mode},
        "branch_status": inp.branch_status,
        "allowed_action_types": allowed,
    }
    shown_tel = _compact_telemetry(inp) if tc else []
    hidden_tel = {o.id for o in tc.observations} - {o.id for o in shown_tel} if tc else set()
    doc["citable_evidence_ids"] = sorted(inp.known_evidence_ids() - hidden_tel)
    if gc:
        doc["incident"]["affected_service_ids"] = gc.incident.affected_service_ids
        doc["incident"]["started_at"] = gc.incident.started_at.isoformat()
        doc["evidence"] = [{"id": e.id, "kind": e.kind, "source_ref": e.source_ref,
                            "observed_at": e.observed_at.isoformat() if e.observed_at else None,
                            "services": e.observed_on_service_ids, "deployments": e.refers_to_deployment_ids,
                            "excerpt": _cut(e.excerpt, EXCERPT)} for e in gc.evidence[:20]]
        doc["alerts"] = [{"id": a.id, "fingerprint": a.fingerprint, "summary": _cut(a.summary, EXCERPT)}
                         for a in gc.alerts[:10]]
        doc["explanation_paths"] = [{
            "claim_type": "correlated", "target_service_id": p.target_service_id,
            "deployment": {"id": p.deployment.id, "version": p.deployment.version,
                           "deployed_at": p.deployment.deployed_at.isoformat()},
            "evidence": [{"id": e.id, "source_ref": e.source_ref, "excerpt": _cut(e.excerpt, EXCERPT)}
                         for e in p.evidence[:10]],
            "runbooks": [{"id": r.id, "allowed_action_types": r.allowed_action_types} for r in p.runbooks[:5]],
            "approval_policy": p.approval_policy, "summary": _cut(p.summary, SUMMARY)}
            for p in gc.explanation_paths[:5]]
        doc["dependencies"] = {sid: [d.service.id for d in deps[:10]] for sid, deps in gc.dependencies.items()}
        doc["recent_deployments"] = [{"id": d.id, "service_id": d.service_id, "version": d.version,
                                      "deployed_at": d.deployed_at.isoformat()} for d in gc.recent_deployments[:10]]
    if mc:
        doc["memories"] = [{"id": x.id, "summary": _cut(x.summary, SUMMARY), "outcome": x.outcome,
                            "precedent": x.precedent, "applicability": x.applicability,
                            "about": x.about_incident_key, "grounded_in": [e.id for e in x.grounded_in]}
                           for x in mc.items[:6]]
    if kc:
        doc["knowledge_context_only"] = [{"id": c.id, "source_ref": c.source_ref,
                                          "excerpt": _cut(c.text_excerpt, SUMMARY)} for c in kc.items[:4]]
    if tc:
        doc["telemetry"] = [{"id": o.id, "service_id": o.service_id, "metric": o.metric, "value": o.value,
                             "baseline": o.baseline, "unit": o.unit, "anomalous": is_anomalous(o),
                             "at": o.source_ref.rsplit("t=", 1)[-1]} for o in shown_tel]
    if inp.feedback:
        doc["feedback"] = [_cut(f, 300) for f in inp.feedback[:20]]
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False, default=str)


def _compact_telemetry(inp: InvestigatorInput) -> list:
    """Latest anomalous readings (up to 3 per service/metric) and the latest normal one per service/metric."""
    obs = sorted(inp.telemetry_context.observations, key=lambda o: -o.observed_at_ms)
    anomalous: dict[tuple[str, str], list] = {}
    normal: dict[tuple[str, str], object] = {}
    for o in obs:
        key = (o.service_id, o.metric)
        if is_anomalous(o):
            if len(anomalous.setdefault(key, [])) < 3:
                anomalous[key].append(o)
        else:
            normal.setdefault(key, o)
    out = [o for v in anomalous.values() for o in v] + list(normal.values())
    return sorted(out, key=lambda o: (o.service_id, o.metric, o.observed_at_ms))[:40]


def messages(inp: InvestigatorInput) -> list[dict]:
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": build_user_content(inp)}]
