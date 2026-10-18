"""The restricted executor: the only code that runs an approved action, and only ever as a SIMULATION.

Called from the graph's `restricted_executor` node after a human resumed the run. It never trusts the
checkpoint: it re-reads every action, its approval records and the graph state, and re-checks that

  - the action is still `approved`, is of an allowlisted type and belongs to a `simulation` run;
  - an APPROVE record is bound to the action's current spec hash and version, and has not expired;
  - the side effect has not already happened (`ops.idempotency_records`, key `<action id>:<spec hash>`).

Order of effects: idempotency `begin` -> graph transition (compare-and-set approved -> executed_simulated) ->
execution record, timeline event, DRAFT memory (all deterministic ids, so a replay rewrites rather than
duplicates) -> idempotency `complete`. With no idempotency store it fails closed and runs nothing.
No real system is ever changed. This module must not import `app.services.actions` (that module calls it).
"""

from __future__ import annotations

import json
import logging

from app.db.idempotency import IdempotencyStore
from app.domain.actions import approval_applies
from app.graph.repository import GraphRepository
from app.services import memories

log = logging.getLogger("app.orchestrator")

SIMULATED_EXECUTABLE = frozenset({"rollback_deployment_simulated"})


def memory_id_for(action_id: str) -> str:
    return action_id.replace(".act.", ".mem.", 1)


def review_ready(rows: list[dict]) -> bool:
    """Whether resuming the paused run makes progress: something is approved and runnable, or nothing is
    left waiting for a human (so the run can finish)."""
    statuses = [(r["action"]["status"], r["action"]["action_type"]) for r in rows]
    return any(s == "approved" and t in SIMULATED_EXECUTABLE for s, t in statuses) \
        or not any(s == "pending_review" for s, _ in statuses)


def pending_action_ids(rows: list[dict]) -> list[str]:
    return [r["action"]["id"] for r in rows if r["action"]["status"] == "pending_review"]


def execute_approved(repo: GraphRepository, store: IdempotencyStore | None, session_id: str, *,
                     now_ms: int) -> list[dict]:
    """Run every approved, allowlisted action of the session. Returns one result per action it looked at:
    {action_id, result: succeeded|failed|expired|busy|skipped, ticket, memory_id, note, replayed}."""
    session = repo.get_node("AgentSession", session_id)
    incident = (repo.neighbors("AgentSession", session_id, "INVESTIGATES", "Incident", outgoing=True, limit=1)
                or [None])[0]
    results = []
    for row in repo.session_actions(session_id):
        a = row["action"]
        if a["status"] == "approved" and a["action_type"] in SIMULATED_EXECUTABLE:
            results.append(_run_one(repo, store, a, session, incident, now_ms))
    return results


def _result(a: dict, result: str, note: str, **extra) -> dict:
    return {"action_id": a["id"], "result": result, "note": note, "ticket": extra.pop("ticket", None),
            "memory_id": extra.pop("memory_id", None), **extra}


def _close(repo: GraphRepository, a: dict, to_status: str, result: str, note: str, now_ms: int) -> dict:
    repo.transition_action(a["id"], from_status="approved", to_status=to_status, version=a["version"], now_ms=now_ms)
    return _result(a, result, note)


def _run_one(repo: GraphRepository, store: IdempotencyStore | None, a: dict, session: dict | None,
             incident: dict | None, now_ms: int) -> dict:
    aid = a["id"]
    if a.get("mode") != "simulation":
        return _close(repo, a, "failed", "failed", "refused: only simulation runs are executed", now_ms)
    records = repo.neighbors("AgentAction", aid, "HAS_REVIEW", "ApprovalRecord", outgoing=True,
                             order_by="decided_at_ms")
    bound = [r for r in records if r["decision"] == "APPROVE" and r["spec_hash"] == a["spec_hash"]
             and r["action_version"] == a["version"]]
    if not bound:
        return _close(repo, a, "failed", "failed", "not executed: no approval matches the action's current spec",
                      now_ms)
    if not any(approval_applies(a, r, now_ms) for r in bound):
        return _close(repo, a, "expired", "expired", "not executed: the approval expired", now_ms)
    if store is None:
        return _result(a, "skipped", "not executed: no idempotency store is configured (fails closed)")

    key = f"{aid}:{a['spec_hash']}"
    begin = store.begin(key, a["spec_hash"], now_ms=now_ms)
    if begin.decision == "done":   # it already ran: heal a lost status write, never run it again
        repo.transition_action(aid, from_status="approved", to_status="executed_simulated", version=a["version"],
                               now_ms=now_ms)
        r = _finish(repo, a, session, incident, now_ms)
        return _result(a, "succeeded", r["note"], ticket=r["ticket"], memory_id=r.get("memory_id"), replayed=True)
    if begin.decision == "busy":
        return _result(a, "busy", "another runner is executing this action; it will be retried")
    if begin.decision in ("conflict", "exhausted"):
        note = ("not executed: the idempotency key was reused for a different request"
                if begin.decision == "conflict" else "not executed: the attempt limit was reached")
        return _close(repo, a, "failed", "failed", note, now_ms)

    try:
        if not repo.transition_action(aid, from_status="approved", to_status="executed_simulated",
                                      version=a["version"], now_ms=now_ms):
            cur = repo.get_node("AgentAction", aid)
            if cur is None or cur["status"] != "executed_simulated":   # else: a crashed run finished the CAS
                store.complete(key, status="failed", response={"result": "failed", "note": "action changed state"},
                               now_ms=now_ms)
                return _result(a, "skipped", "not executed: the action changed state")
        response = _finish(repo, a, session, incident, now_ms)
    except Exception:
        log.exception("simulated execution failed", extra={"action_id": aid})
        repo.transition_action(aid, from_status="executed_simulated", to_status="failed", version=a["version"],
                               now_ms=now_ms)
        _complete_quietly(store, key, "failed", {"result": "failed", "note": "execution failed"}, now_ms)
        return _result(a, "failed", "the simulated execution failed; see the server log")
    store.complete(key, status="succeeded", response=response, now_ms=now_ms)
    return _result(a, "succeeded", response["note"], ticket=response["ticket"], memory_id=response.get("memory_id"))


def _complete_quietly(store: IdempotencyStore, key: str, status: str, response: dict, now_ms: int) -> None:
    try:
        store.complete(key, status=status, response=response, now_ms=now_ms)
    except Exception:
        log.warning("could not record the idempotency outcome", exc_info=True)


def _finish(repo: GraphRepository, a: dict, session: dict | None, incident: dict | None, now_ms: int) -> dict:
    """Everything after the status change. Idempotent: deterministic ids, create-only memory."""
    aid = a["id"]
    cur = repo.get_node("AgentAction", aid) or a
    execution = None
    if cur.get("execution_json"):
        try:
            execution = json.loads(cur["execution_json"])
        except ValueError:
            execution = None
    if execution is None:
        spec = json.loads(a["spec_json"])
        execution = {"result": "succeeded", "ticket": "SIM-" + aid.split(".", 2)[2].replace(".", "-").upper()[:48],
                     "executed_at_ms": now_ms,
                     "note": f"Simulated rollback of {spec.get('deployment_id')} on {a['target_service_id']}. "
                             "No real system was changed."}
        repo.update_node("AgentAction", aid, {"execution_json": json.dumps(execution, sort_keys=True)}, at_ms=now_ms)
    memory_id = None
    if incident:
        _timeline(repo, incident["id"], aid, execution, now_ms)
        memory_id = _write_back_memory(repo, a, session, incident, execution["note"], now_ms)
    return {**execution, "memory_id": memory_id}


def _timeline(repo: GraphRepository, incident_id: str, action_id: str, execution: dict, now_ms: int) -> None:
    try:
        tl_id = action_id.replace(".act.", ".tl.", 1) + ".exec"
        repo.merge_node("TimelineEvent", tl_id, {
            "at_ms": execution["executed_at_ms"], "type": "action_executed_simulated", "actor": "restricted_executor",
            "summary": f"{execution['note']} Ticket {execution['ticket']}.", "ref_id": action_id,
            "source": "agent"}, at_ms=now_ms)
        repo.merge_edge("Incident", incident_id, "HAS_EVENT", "TimelineEvent", tl_id, at_ms=now_ms)
    except Exception:
        log.warning("could not write the execution timeline event", exc_info=True, extra={"action_id": action_id})


def _write_back_memory(repo: GraphRepository, a: dict, session: dict | None, incident: dict, note: str,
                       now_ms: int) -> str | None:
    """Draft only: grounded in the action's own evidence, out of retrieval until a human validates it. The id is
    deterministic and the node is create-only, so a replay can never reset a memory a human already verified."""
    mid = memory_id_for(a["id"])
    try:
        if repo.get_node("AgentMemory", mid) is not None:
            return mid
        evidence_ids = [e["id"] for e in repo.neighbors("AgentAction", a["id"], "SUPPORTED_BY", "Evidence",
                                                        outgoing=True, limit=50)]
        if not evidence_ids:
            return None
        approval = (repo.neighbors("AgentAction", a["id"], "HAS_REVIEW", "ApprovalRecord", outgoing=True,
                                   order_by="decided_at_ms") or [{}])[-1].get("id")
        return memories.create_draft(
            repo, about_incident_id=incident["id"], memory_type="episodic", grounded_in=evidence_ids,
            derived_from_action_ids=[a["id"]], now_ms=now_ms, memory_id=mid,
            summary=f"{note} Whether it resolved {incident['key']} is not yet verified.",
            model_version=(session or {}).get("investigator") or "restricted_executor",
            provenance_refs=[x for x in (session["id"] if session else None, approval) if x])
    except Exception:
        log.warning("could not write the draft memory", exc_info=True, extra={"action_id": a["id"]})
        return None
