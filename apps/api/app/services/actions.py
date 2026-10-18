"""Human review of proposed actions (Phase 5).

An investigation in simulation mode PAUSES at `human_review` (a LangGraph `interrupt()`, checkpointed in
Postgres). The review is a separate, authenticated request: this module records the human decision, then asks
the orchestrator to resume the paused run, whose `restricted_executor` node (app/orchestrator/executor.py)
performs the simulated execution. No worker thread is held while a human decides.

Guarantees, in order:
1. Only `pending_review` actions of `simulation` runs can be reviewed (`recommendation_only` proposals are `proposed`).
2. APPROVE needs the role the active, in-effect Decision governing the target service requires; with no such
   policy the request fails closed.
3. The decision is claimed with one atomic compare-and-set, so concurrent reviewers cannot both win.
4. An APPROVE is bound to the action's spec hash and version, and expires; the executor re-checks all of that
   before it runs, only allowlisted types run, only as a simulation, and at most once (idempotency record).
5. A simulated execution leaves a DRAFT memory. It stays out of retrieval until a human validates it.
If no orchestrator is attached to this process (or resuming fails) the approval stays durable and the worker's
poll resumes the run; the response then says execution is still pending.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from pydantic import ValidationError

from app.api import models as m
from app.api.errors import Conflict, Forbidden, NotFound
from app.auth import Principal
from app.domain.actions import spec_hash
from app.domain.redact import redact
from app.graph.repository import GraphRepository
from app.orchestrator.executor import SIMULATED_EXECUTABLE, memory_id_for, review_ready
from app.services.incidents import add_timeline, evidence_ref
from app.services.service_context import in_effect

log = logging.getLogger(__name__)

Resumer = Callable[[str], str]   # session id -> status; continues the run paused at human review
APPROVAL_TTL_MS = 15 * 60 * 1000
NEW_STATUS = {"APPROVE": "approved", "REJECT": "rejected", "REQUEST_REVISION": "revision_requested",
              "ESCALATE": "escalated"}
TIMELINE_TYPE = {"APPROVE": "action_approved", "REJECT": "action_rejected",
                 "REQUEST_REVISION": "action_revision_requested", "ESCALATE": "action_escalated"}
VERB = {"APPROVE": "approved", "REJECT": "rejected", "REQUEST_REVISION": "asked for a revision of",
        "ESCALATE": "escalated"}


# ------------------------------------------------------------------ reads
def required_policy(repo: GraphRepository, service_id: str, now_ms: int) -> dict | None:
    """The newest active, in-effect Decision governing the service that names an approver role, or None."""
    for row in repo.service_decisions(service_id):
        d = row["decision"]
        if in_effect(d, now_ms) and d.get("required_approver_role"):
            return d
    return None


def _review_out(rec: dict, handles: dict[str, dict]) -> m.ReviewOut:
    approver = rec.get("approver_id") or ""
    return m.ReviewOut(
        id=rec["id"], decision=rec["decision"], approver_id=approver,
        approver_handle=(handles.get(approver) or {}).get("handle"), decided_at=m.to_dt(rec["decided_at_ms"]),
        expires_at=m.to_dt(rec.get("expires_at_ms")), comment=rec.get("comment"), spec_hash=rec["spec_hash"],
        action_version=rec["action_version"], policy_decision_id=rec.get("policy_decision_id"))


def _execution_out(a: dict) -> m.ExecutionOut | None:
    if not a.get("execution_json"):
        return None
    try:
        raw = json.loads(a["execution_json"])
        return m.ExecutionOut(result=raw["result"], ticket=raw.get("ticket"), note=raw.get("note"),
                              executed_at=m.to_dt(raw["executed_at_ms"]))
    except (ValueError, KeyError, ValidationError):
        log.warning("unreadable execution_json", extra={"action_id": a.get("id")})
        return None


def action_out(repo: GraphRepository, a: dict, evidence: list[dict], now_ms: int) -> m.ProposedActionOut:
    """Raises KeyError/ValueError/ValidationError for a malformed stored action; callers withhold it."""
    spec = json.loads(a["spec_json"])
    records = repo.neighbors("AgentAction", a["id"], "HAS_REVIEW", "ApprovalRecord", outgoing=True,
                             order_by="decided_at_ms")
    handles = repo.get_nodes("Responder", [r["approver_id"] for r in records if r.get("approver_id")])
    policy = required_policy(repo, a["target_service_id"], now_ms)
    warnings = [] if spec_hash(a["spec_json"]) == a["spec_hash"] else ["spec_hash does not match spec_json"]
    if a["status"] in ("approved", "executed_simulated") and not any(
            r["decision"] == "APPROVE" and r["spec_hash"] == a["spec_hash"] and r["action_version"] == a["version"]
            for r in records):
        warnings.append(f"action is {a['status']} but has no APPROVE record bound to its current spec")
    return m.ProposedActionOut(
        id=a["id"], proposal_id=a["proposal_id"], version=a["version"], action_type=a["action_type"],
        status=a["status"], mode=a["mode"], target_service_id=a["target_service_id"],
        deployment_id=a.get("deployment_id") or spec.get("deployment_id"),
        runbook_id=a.get("runbook_id") or spec.get("runbook_id"), risk=a.get("risk"), rationale=a.get("rationale"),
        spec=spec, spec_hash=a["spec_hash"], evidence=[evidence_ref(e) for e in sorted(evidence, key=lambda e: e["id"])],
        required_approver_role=policy["required_approver_role"] if policy else None,
        approval_policy_id=policy["id"] if policy else None,
        reviews=[_review_out(r, handles) for r in records], execution=_execution_out(a), integrity_warnings=warnings)


def get_action(repo: GraphRepository, action_id: str, now_ms: int) -> m.ProposedActionOut:
    a = repo.get_node("AgentAction", action_id)
    if a is None:
        raise NotFound(f"action {action_id} not found")
    evidence = repo.neighbors("AgentAction", action_id, "SUPPORTED_BY", "Evidence", outgoing=True, limit=50)
    try:
        return action_out(repo, a, evidence, now_ms)
    except (KeyError, ValueError, ValidationError):
        raise Conflict("stored action failed validation", code="integrity_error") from None


# ------------------------------------------------------------------ review
def review(repo: GraphRepository, action_id: str, body: m.ReviewIn, principal: Principal,
           now_ms: int, resume: Resumer | None = None) -> m.ReviewResult:
    a = repo.get_node("AgentAction", action_id)
    if a is None:
        raise NotFound(f"action {action_id} not found")
    if a["status"] != "pending_review":
        if a["status"] == "proposed" and a.get("mode") == "recommendation_only":
            raise Conflict("this proposal came from a recommendation_only run; it can be neither approved nor "
                           "executed. Start a simulation investigation to review actions.",
                           code="recommendation_only")
        raise Conflict(f"action is {a['status']}; only pending_review actions can be reviewed",
                       code="action_not_reviewable")
    if spec_hash(a["spec_json"]) != a["spec_hash"]:
        raise Conflict("the stored action spec does not match its hash; refusing to act on it",
                       code="spec_hash_mismatch")
    me = repo.get_node("Responder", principal.responder_id) if principal.responder_id else None
    if me is None:
        raise Forbidden("the reviewer has no responder identity in this tenant", code="no_responder_identity")

    policy = required_policy(repo, a["target_service_id"], now_ms)
    if body.decision == "APPROVE":
        if policy is None:
            raise Conflict(f"no active approval policy governs {a['target_service_id']}; approval fails closed",
                           code="no_active_policy")
        role = policy["required_approver_role"]
        if role not in (me.get("roles") or []):
            raise Forbidden(f"approving this action requires the {role} role (policy {policy['id']})",
                            code="missing_approver_role")

    sessions = repo.neighbors("AgentAction", action_id, "PART_OF", "AgentSession", outgoing=True, limit=1)
    session = sessions[0] if sessions else None
    incident = (repo.neighbors("AgentSession", session["id"], "INVESTIGATES", "Incident", outgoing=True, limit=1)
                or [None])[0] if session else None

    if not repo.transition_action(action_id, from_status="pending_review", to_status=NEW_STATUS[body.decision],
                                  version=a["version"], now_ms=now_ms):
        raise Conflict("the action was reviewed by someone else; reload it", code="action_not_reviewable")

    record_id = action_id.replace(".act.", ".apr.", 1)
    comment = redact(body.comment).strip() if body.comment else ""
    repo.merge_node("ApprovalRecord", record_id, {
        "decision": body.decision, "spec_hash": a["spec_hash"], "action_version": a["version"],
        "approver_id": me["id"], "decided_at_ms": now_ms,
        "expires_at_ms": now_ms + APPROVAL_TTL_MS if body.decision == "APPROVE" else None,
        "scope": a["mode"], "policy_decision_id": policy["id"] if policy else None, "comment": comment or None,
        "source": "human"}, at_ms=now_ms)
    repo.merge_edge("AgentAction", action_id, "HAS_REVIEW", "ApprovalRecord", record_id, at_ms=now_ms)
    repo.merge_edge("ApprovalRecord", record_id, "DECIDED_BY", "Responder", me["id"], at_ms=now_ms)
    if incident:
        add_timeline(repo, incident["id"], TIMELINE_TYPE[body.decision], principal.user_id,
                     f"{me['handle']} {VERB[body.decision]} {a['action_type']} on {a['target_service_id']}"
                     + (f": {comment[:200]}" if comment else ""), now_ms, ref_id=action_id)

    memory_id, note = None, None
    status, resumed = (session or {}).get("status", "completed"), False
    if session is not None and resume is not None:
        try:
            if review_ready(repo.session_actions(session["id"])):
                resume(session["id"])
                resumed = True
        except Exception:   # the decision is already recorded; the worker's poll resumes the run
            log.exception("could not resume the paused run", extra={"action_id": action_id})
    if session is not None:
        status = (repo.get_node("AgentSession", session["id"]) or session)["status"]

    fresh = get_action(repo, action_id, now_ms)
    review_out = next(r for r in fresh.reviews if r.id == record_id)
    if body.decision == "APPROVE":
        note = _approve_message(fresh, resumed)
        if fresh.status == "executed_simulated" and repo.get_node("AgentMemory", memory_id_for(action_id)):
            memory_id = memory_id_for(action_id)
    message = {"APPROVE": note or "Approved.", "REJECT": "Rejected; nothing was executed.",
               "REQUEST_REVISION": "Revision requested. Start a new investigation to produce a revised proposal; "
                                   "nothing was executed.",
               "ESCALATE": "Escalated; nothing was executed."}[body.decision]
    return m.ReviewResult(action=fresh, review=review_out, investigation_status=status, memory_id=memory_id,
                          message=message)


def _approve_message(a: m.ProposedActionOut, resumed: bool) -> str:
    if a.status == "executed_simulated":
        ticket = a.execution.ticket if a.execution else None
        return (f"Approved and executed in simulation (ticket {ticket}). "
                "A draft memory awaits human validation.")
    if a.status == "expired":
        return "Approved, but not executed: the approval expired before the executor ran."
    if a.status == "failed":
        return "Approved, but the simulated execution did not complete; see the server log."
    if a.action_type not in SIMULATED_EXECUTABLE:
        return f"Approved. {a.action_type} has no simulated executor, so nothing was run."
    return ("Approved, but not executed yet: the executor did not run it. The worker retries." if resumed else
            "Approved. The paused run has not been resumed yet; the worker will execute it in simulation.")
