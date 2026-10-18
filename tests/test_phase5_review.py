"""Phase 5: run events, run-scoped retrieval, run list, action review, simulated execution, memory write-back."""

# ruff: noqa: F811  (the `saver` and `pool` fixtures are imported from sibling test modules)
from __future__ import annotations

import dataclasses

import pytest
from app.graph.repository import GraphRepository
from app.orchestrator import events as run_events
from app.orchestrator.runner import Orchestrator, Worker
from app.services import actions as action_service
from app.services import investigations
from langgraph.checkpoint.memory import MemorySaver

from .conftest import NOW, RESPONDER, VIEWER
from .test_ops_idempotency import pool  # noqa: F401
from .test_phase4_orchestrator import (
    INC,
    SCOPE,
    Calls,
    make_deps,
    make_orch,
    run_actions,
    run_golden,
    saver,  # noqa: F401  (fixture: memory and Postgres checkpointers)
    start,
)

pytestmark = pytest.mark.integration

LEAD = {"X-Demo-User": "payments-lead"}
ACME = {"X-Demo-User": "acme-viewer"}
POLICY = "nova.dec.payment.rollback_v2"


_ORCH: dict[str, Orchestrator] = {}


@pytest.fixture
def make_client(make_client):
    """Shadows the conftest fixture: a graph with a paused simulation run gets an in-process worker, so the
    review API resumes that run exactly as it does in production."""
    def _make(graph_name, **kw):
        orch = _ORCH.get(graph_name)
        return make_client(graph_name, orchestrator=Worker(orch.settings, orchestrator=orch) if orch else None, **kw)
    return _make


def simulate(graph, settings):
    """A simulation run paused at human review with one pending_review action."""
    orch, _, sid, status = run_golden(graph, settings, mode="simulation")
    assert status == "awaiting_review"
    _ORCH[graph.name] = orch
    [action] = investigations.get(GraphRepository(graph, SCOPE), sid).proposed_actions
    return sid, action.id


def review(http, action_id, decision="APPROVE", headers=LEAD, **extra):
    return http.post(f"/api/actions/{action_id}/review", json={"decision": decision, **extra}, headers=headers)


def timeline_types(http):
    return [e["type"] for e in http.get(f"/api/incidents/{INC}/timeline", headers=VIEWER).json()["events"]]


# ============================================================================ events and snapshot
def test_events_are_written_per_node_and_served_in_order(mutable_graph, settings, make_client):
    _, _, sid, _ = run_golden(mutable_graph, settings, mode="simulation")
    http = make_client(mutable_graph.name)
    body = http.get(f"/api/investigations/{sid}/events", headers=VIEWER).json()
    assert body["status"] == "awaiting_review"
    seen = {(e["kind"], e["status"]) for e in body["events"]}
    for kind in ("intake_and_deduplicate", "coordinator", "graph_context_retrieval", "memory_retrieval",
                 "live_evidence_retrieval", "fan_in", "investigator", "evidence_safety_gate"):
        assert (kind, "started") in seen and (kind, "completed") in seen, kind
    assert ("human_review", "waiting") in seen
    kinds = [e["kind"] for e in body["events"]]
    assert kinds.index("coordinator") < kinds.index("fan_in") < kinds.index("investigator")
    assert len({e["id"] for e in body["events"]}) == len(body["events"])


def test_recommendation_only_run_has_no_review_events(mutable_graph, settings, make_client):
    _, _, sid, _ = run_golden(mutable_graph, settings)
    http = make_client(mutable_graph.name)
    kinds = {e["kind"] for e in http.get(f"/api/investigations/{sid}/events", headers=VIEWER).json()["events"]}
    assert "human_review" not in kinds and "restricted_executor" not in kinds


def test_branch_timestamps_come_from_events(mutable_graph, settings, make_client):
    _, _, sid, _ = run_golden(mutable_graph, settings)
    http = make_client(mutable_graph.name)
    branches = http.get(f"/api/investigations/{sid}", headers=VIEWER).json()["branches"]
    for name in ("graph_context", "memory_context", "telemetry_context"):
        assert branches[name]["started_at"] and branches[name]["ended_at"], name


def test_running_session_shows_branch_progress_before_it_is_persisted(mutable_graph):
    sid = start(mutable_graph)
    repo = GraphRepository(mutable_graph, SCOPE)
    state = {"session_id": sid}
    repo.update_node("AgentSession", sid, {
        "branch_status_json": '{"graph_context":{"status":"running"},"memory_context":{"status":"running"},'
                              '"telemetry_context":{"status":"running"}}'}, at_ms=NOW)
    run_events.record(repo, state, "graph_context_retrieval", "started", now_ms=NOW)
    run_events.record(repo, state, "graph_context_retrieval", "completed", now_ms=NOW + 5, detail="3 evidence")
    run_events.record(repo, state, "memory_retrieval", "started", now_ms=NOW)
    out = investigations.get(repo, sid)
    assert out.status == "running"
    assert out.branches["graph_context"].status == "completed" and out.branches["graph_context"].detail == "3 evidence"
    assert out.branches["memory_context"].status == "running"   # started but not closed


def test_event_write_failure_never_fails_the_run(mutable_graph, settings, monkeypatch):
    real = GraphRepository.merge_node

    def flaky(self, label, node_id, props, **kw):
        if label == "AgentEvent":
            raise RuntimeError("boom")
        return real(self, label, node_id, props, **kw)

    monkeypatch.setattr(GraphRepository, "merge_node", flaky)
    _, _, _, status = run_golden(mutable_graph, settings)
    assert status == "completed"


def test_run_retrieval_snapshot_is_persisted_and_served(mutable_graph, settings, make_client):
    _, _, sid, _ = run_golden(mutable_graph, settings)
    http = make_client(mutable_graph.name)
    r = http.get(f"/api/investigations/{sid}/retrieval", headers=VIEWER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["investigation_id"] == sid and body["incident_id"] == INC and body["as_of"]
    assert body["graph_context"]["incident"]["id"] == INC
    assert body["knowledge_context"] is not None and body["memory_context"] is not None


def test_retrieval_snapshot_404_before_the_run_finishes(mutable_graph, make_client):
    http = make_client(mutable_graph.name)
    sid = http.post("/api/investigations", json={"incident_id": INC, "mode": "recommendation_only"},
                    headers=RESPONDER).json()["id"]
    r = http.get(f"/api/investigations/{sid}/retrieval", headers=VIEWER)
    assert r.status_code == 404 and r.json()["error"]["code"] == "no_snapshot"


def test_events_and_retrieval_404_for_unknown_run(mutable_graph, make_client):
    http = make_client(mutable_graph.name)
    for tail in ("events", "retrieval"):
        assert http.get(f"/api/investigations/nova.ses.nope/{tail}", headers=VIEWER).status_code == 404


def test_list_investigations_for_incident_newest_first_and_tenant_scoped(mutable_graph, settings, make_client):
    run_golden(mutable_graph, settings)
    run_golden(mutable_graph, settings, mode="simulation")
    http = make_client(mutable_graph.name)
    body = http.get(f"/api/incidents/{INC}/investigations", headers=VIEWER).json()
    assert body["incident_id"] == INC and len(body["items"]) == 2
    assert {i["mode"] for i in body["items"]} == {"recommendation_only", "simulation"}
    assert body["items"][0]["started_at"] >= body["items"][1]["started_at"]
    assert http.get(f"/api/incidents/{INC}/investigations", headers=ACME).status_code == 404


# ============================================================================ review: refusals
def test_review_needs_the_review_permission(mutable_graph, settings, make_client):
    _, aid = simulate(mutable_graph, settings)
    http = make_client(mutable_graph.name)
    for headers in (VIEWER, RESPONDER):
        assert review(http, aid, headers=headers).status_code == 403
    assert GraphRepository(mutable_graph, SCOPE).get_node("AgentAction", aid)["status"] == "pending_review"


def test_unknown_action_404_and_other_tenant_cannot_see_it(mutable_graph, settings, make_client):
    _, aid = simulate(mutable_graph, settings)
    http = make_client(mutable_graph.name)
    assert review(http, "nova.act.nope.1.v1").status_code == 404
    assert http.get(f"/api/actions/{aid}", headers=ACME).status_code == 404
    assert http.get(f"/api/actions/{aid}", headers=VIEWER).status_code == 200


def test_recommendation_only_proposal_cannot_be_reviewed(mutable_graph, settings, make_client):
    _, _, sid, _ = run_golden(mutable_graph, settings)
    [action] = investigations.get(GraphRepository(mutable_graph, SCOPE), sid).proposed_actions
    assert action.status == "proposed"
    r = review(make_client(mutable_graph.name), action.id)
    assert r.status_code == 409 and r.json()["error"]["code"] == "recommendation_only"
    assert GraphRepository(mutable_graph, SCOPE).get_node("AgentAction", action.id)["status"] == "proposed"


def test_approve_without_the_policy_role_is_forbidden(mutable_graph, settings, make_client):
    _, aid = simulate(mutable_graph, settings)
    repo = GraphRepository(mutable_graph, SCOPE)
    repo.update_node("Responder", "nova.rsp.payments_lead", {"roles": ["oncall:payment"]}, at_ms=NOW)
    http = make_client(mutable_graph.name)
    r = review(http, aid)
    assert r.status_code == 403 and r.json()["error"]["code"] == "missing_approver_role"
    assert repo.get_node("AgentAction", aid)["status"] == "pending_review"
    # rejecting needs only the review permission
    assert review(http, aid, "REJECT").status_code == 200


def test_approve_fails_closed_without_an_active_policy(mutable_graph, settings, make_client):
    _, aid = simulate(mutable_graph, settings)
    repo = GraphRepository(mutable_graph, SCOPE)
    repo.update_node("Decision", POLICY, {"status": "superseded"}, at_ms=NOW)
    r = review(make_client(mutable_graph.name), aid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_active_policy"
    assert repo.get_node("AgentAction", aid)["status"] == "pending_review"


def test_tampered_spec_is_refused(mutable_graph, settings, make_client):
    _, aid = simulate(mutable_graph, settings)
    repo = GraphRepository(mutable_graph, SCOPE)
    spec = repo.get_node("AgentAction", aid)["spec_json"]
    repo.update_node("AgentAction", aid, {"spec_json": spec.replace("nova.svc.payment", "nova.svc.checkout")},
                     at_ms=NOW)
    r = review(make_client(mutable_graph.name), aid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "spec_hash_mismatch"
    assert repo.get_node("AgentAction", aid)["status"] == "pending_review"


def test_second_review_loses_with_409(mutable_graph, settings, make_client):
    _, aid = simulate(mutable_graph, settings)
    http = make_client(mutable_graph.name)
    assert review(http, aid, "REJECT").status_code == 200
    r = review(http, aid, "APPROVE")
    assert r.status_code == 409 and r.json()["error"]["code"] == "action_not_reviewable"
    repo = GraphRepository(mutable_graph, SCOPE)
    assert repo.get_node("AgentAction", aid)["status"] == "rejected"
    assert len(repo.neighbors("AgentAction", aid, "HAS_REVIEW", "ApprovalRecord", outgoing=True)) == 1


def test_claim_is_compare_and_set(mutable_graph, settings):
    _, aid = simulate(mutable_graph, settings)
    repo = GraphRepository(mutable_graph, SCOPE)
    assert repo.transition_action(aid, from_status="pending_review", to_status="approved", version=1, now_ms=NOW)
    assert not repo.transition_action(aid, from_status="pending_review", to_status="rejected", version=1, now_ms=NOW)
    assert not repo.transition_action(aid, from_status="approved", to_status="rejected", version=2, now_ms=NOW)
    assert repo.get_node("AgentAction", aid)["status"] == "approved"


# ============================================================================ review: decisions
@pytest.mark.parametrize("decision,action_status,session_status,timeline", [
    ("REJECT", "rejected", "completed", "action_rejected"),
    ("REQUEST_REVISION", "revision_requested", "completed", "action_revision_requested"),
    ("ESCALATE", "escalated", "escalated", "action_escalated"),
])
def test_non_approving_decisions_execute_nothing(mutable_graph, settings, make_client, decision, action_status,
                                                 session_status, timeline):
    sid, aid = simulate(mutable_graph, settings)
    http = make_client(mutable_graph.name)
    r = review(http, aid, decision, comment="reason, contact ops@example.com")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"]["status"] == action_status and body["action"]["execution"] is None
    assert body["investigation_status"] == session_status and body["memory_id"] is None
    assert body["review"]["decision"] == decision and body["review"]["expires_at"] is None
    assert "ops@example.com" not in body["review"]["comment"]          # redacted before storage
    assert body["review"]["approver_id"] == "nova.rsp.payments_lead"
    assert investigations.get(GraphRepository(mutable_graph, SCOPE), sid).status == session_status
    types = timeline_types(http)
    assert timeline in types and "action_executed_simulated" not in types


def test_approve_runs_the_simulated_rollback_and_drafts_a_memory(mutable_graph, settings, make_client):
    sid, aid = simulate(mutable_graph, settings)
    http = make_client(mutable_graph.name)
    r = review(http, aid, comment="go")
    assert r.status_code == 200, r.text
    body = r.json()
    action = body["action"]
    assert action["status"] == "executed_simulated" and action["required_approver_role"] == "approver:payment"
    assert action["execution"]["simulated"] is True and action["execution"]["result"] == "succeeded"
    assert action["execution"]["ticket"].startswith("SIM-")
    assert action["integrity_warnings"] == []
    rec = body["review"]
    assert rec["decision"] == "APPROVE" and rec["spec_hash"] == action["spec_hash"] and rec["action_version"] == 1
    assert rec["expires_at"] and rec["policy_decision_id"] == POLICY
    assert body["investigation_status"] == "completed"
    types = timeline_types(http)
    assert "action_approved" in types and "action_executed_simulated" in types

    repo = GraphRepository(mutable_graph, SCOPE)
    assert repo.valid_approvals(aid, at_ms=NOW) and repo.get_node("AgentSession", sid)["status"] == "completed"
    # the draft memory is invisible to retrieval until a human validates it
    mem_id = body["memory_id"]
    mem = repo.get_node("AgentMemory", mem_id)
    assert mem["verification_status"] == "draft" and mem["outcome"] == "unknown"
    verified = http.get(f"/api/incidents/{INC}/memories", headers=VIEWER).json()["memories"]
    assert mem_id not in [x["id"] for x in verified]
    # the run's own detail now carries the review and outcome
    [shown] = http.get(f"/api/investigations/{sid}", headers=VIEWER).json()["proposed_actions"]
    assert shown["status"] == "executed_simulated" and len(shown["reviews"]) == 1 and shown["execution"]


def test_memory_validation_closes_the_loop(mutable_graph, settings, make_client):
    _, aid = simulate(mutable_graph, settings)
    http = make_client(mutable_graph.name)
    mem_id = review(http, aid).json()["memory_id"]
    assert http.post(f"/api/memories/{mem_id}/validate", json={"outcome": "successful"},
                     headers=RESPONDER).status_code == 403
    r = http.post(f"/api/memories/{mem_id}/validate", json={"outcome": "successful"}, headers=LEAD)
    assert r.status_code == 200, r.text
    assert r.json() == {"id": mem_id, "verification_status": "verified", "outcome": "successful"}
    seen = {x["id"]: x for x in http.get(f"/api/incidents/{INC}/memories", headers=VIEWER).json()["memories"]}
    assert seen[mem_id]["precedent"] == "supports" and seen[mem_id]["validated_by"][0]["id"] == "nova.rsp.payments_lead"


def test_draft_memory_can_be_rejected(mutable_graph, settings, make_client):
    _, aid = simulate(mutable_graph, settings)
    http = make_client(mutable_graph.name)
    mem_id = review(http, aid).json()["memory_id"]
    r = http.post(f"/api/memories/{mem_id}/reject", headers=LEAD)
    assert r.status_code == 200 and r.json()["verification_status"] == "rejected"
    assert http.post(f"/api/memories/{mem_id}/validate", json={"outcome": "successful"},
                     headers=LEAD).status_code == 409


def test_an_expired_approval_does_not_execute(mutable_graph, settings, make_client, monkeypatch):
    _, aid = simulate(mutable_graph, settings)
    monkeypatch.setattr(action_service, "APPROVAL_TTL_MS", 0)
    r = review(make_client(mutable_graph.name), aid)
    assert r.status_code == 200 and r.json()["action"]["status"] == "expired"
    assert r.json()["action"]["execution"] is None and r.json()["memory_id"] is None
    assert "not executed" in r.json()["message"] and r.json()["investigation_status"] == "completed"


def test_approved_action_without_a_matching_record_is_flagged(mutable_graph, settings, make_client):
    sid, aid = simulate(mutable_graph, settings)
    GraphRepository(mutable_graph, SCOPE).update_node("AgentAction", aid, {"status": "approved"}, at_ms=NOW)
    body = make_client(mutable_graph.name).get(f"/api/investigations/{sid}", headers=VIEWER).json()
    assert any("no APPROVE record" in w for w in body["proposed_actions"][0]["integrity_warnings"])


def test_session_stays_open_until_every_action_is_decided(mutable_graph, settings, make_client):
    sid, aid = simulate(mutable_graph, settings)
    repo = GraphRepository(mutable_graph, SCOPE)
    other = aid.replace(".1.v1", ".2.v1")
    repo.merge_node("AgentAction", other, {k: v for k, v in repo.get_node("AgentAction", aid).items()
                                           if k in ("proposal_id", "version", "action_type", "spec_json", "spec_hash",
                                                    "target_service_id", "mode", "status", "runbook_id",
                                                    "deployment_id", "rationale", "risk")}
                    | {"proposal_id": aid.replace(".act.", ".prop.").rsplit(".", 2)[0] + ".2"}, at_ms=NOW)
    repo.merge_edge("AgentAction", other, "PART_OF", "AgentSession", sid, at_ms=NOW)
    http = make_client(mutable_graph.name)
    assert review(http, aid, "REJECT").json()["investigation_status"] == "awaiting_review"
    assert review(http, other, "REJECT").json()["investigation_status"] == "completed"


def test_events_are_idempotent_when_a_node_replays(mutable_graph):
    sid = start(mutable_graph)
    repo = GraphRepository(mutable_graph, SCOPE)
    for _ in range(2):
        run_events.record(repo, {"session_id": sid}, "coordinator", "started", now_ms=NOW)
    assert len(investigations.events(repo, sid).events) == 1


# ============================================================================ pause / resume / idempotent execution
def second_action(repo, sid, aid):
    """A second pending_review action in the same session (copy of the first, same spec, new ids)."""
    other = aid.replace(".1.v1", ".2.v1")
    keep = ("version", "action_type", "spec_json", "spec_hash", "target_service_id", "mode", "status", "runbook_id",
            "deployment_id", "rationale", "risk")
    repo.merge_node("AgentAction", other, {k: v for k, v in repo.get_node("AgentAction", aid).items() if k in keep}
                    | {"proposal_id": other.replace(".act.", ".prop.").rsplit(".", 2)[0] + ".2"}, at_ms=NOW)
    repo.merge_edge("AgentAction", other, "PART_OF", "AgentSession", sid, at_ms=NOW)
    return other


def paused(orch, sid):
    return orch.graph.get_state(orch.config(investigations.get(GraphRepository(orch.env.falkor, SCOPE), sid)
                                            .thread_id))


def test_approval_resumes_the_same_thread_and_finishes_the_run(mutable_graph, settings, make_client):
    sid, aid = simulate(mutable_graph, settings)
    orch = _ORCH[mutable_graph.name]
    assert paused(orch, sid).next == ("human_review",)
    r = review(make_client(mutable_graph.name), aid)
    assert r.status_code == 200 and r.json()["investigation_status"] == "completed"
    snap = paused(orch, sid)
    assert snap.next == () and snap.values["status"] == "completed"
    [result] = snap.values["execution"]["results"]
    assert result["action_id"] == aid and result["result"] == "succeeded" and result["memory_id"] == r.json()["memory_id"]
    states = {(e["kind"], e["status"]) for e in
              make_client(mutable_graph.name).get(f"/api/investigations/{sid}/events", headers=VIEWER).json()["events"]}
    assert {("human_review", "waiting"), ("human_review", "completed"), ("restricted_executor", "completed")} <= states


def paused_without_worker(graph, settings, saver=None, store=None):
    """A simulation run paused at human review on a shared checkpointer, with NO in-process worker for the API."""
    saver = saver or MemorySaver()
    deps = make_deps(Calls())
    orch = make_orch(graph, settings, dataclasses.replace(deps, idempotency=store) if store else deps, saver=saver)
    sid = start(graph, "simulation")
    assert orch.run(sid, SCOPE) == "awaiting_review"
    [aid] = [a["id"] for a in run_actions(graph, sid)]
    return saver, orch, sid, aid


def test_approval_without_a_worker_is_durable_and_a_fresh_orchestrator_finishes_it(mutable_graph, settings,
                                                                                   make_client, saver):
    saver, _, sid, aid = paused_without_worker(mutable_graph, settings, saver)
    r = review(make_client(mutable_graph.name), aid)
    assert r.status_code == 200 and r.json()["action"]["status"] == "approved"
    assert r.json()["investigation_status"] == "awaiting_review" and "worker" in r.json()["message"]
    # "restart": a new orchestrator on the same checkpoints; the worker's poll scan finds the session
    orch2 = make_orch(mutable_graph, settings, make_deps(Calls()), saver=saver)
    assert (sid, SCOPE) in Worker(settings, orchestrator=orch2).reviewable_sessions()
    assert orch2.resume_review(sid, SCOPE) == "completed"
    repo = GraphRepository(mutable_graph, SCOPE)
    assert repo.get_node("AgentAction", aid)["status"] == "executed_simulated"
    assert repo.get_node("AgentSession", sid)["status"] == "completed"
    assert orch2.resume_review(sid, SCOPE) == "completed"             # a repeated resume is harmless
    assert (sid, SCOPE) not in Worker(settings, orchestrator=orch2).reviewable_sessions()


def test_a_changed_spec_after_approval_is_not_executed(mutable_graph, settings, make_client):
    _saver, orch, sid, aid = paused_without_worker(mutable_graph, settings)
    assert review(make_client(mutable_graph.name), aid).status_code == 200
    repo = GraphRepository(mutable_graph, SCOPE)
    repo.update_node("AgentAction", aid, {"spec_hash": "0" * 64}, at_ms=NOW)          # the spec moved on
    assert orch.resume_review(sid, SCOPE) == "completed"
    a = repo.get_node("AgentAction", aid)
    assert a["status"] == "failed" and not a.get("execution_json")
    assert repo.neighbors("AgentAction", aid, "DERIVED_FROM", "AgentMemory", outgoing=False) == []
    [result] = paused(orch, sid).values["execution"]["results"]
    assert result["result"] == "failed" and "no approval matches" in result["note"]


def test_executor_fails_closed_without_an_idempotency_store(mutable_graph, settings, make_client):
    from app.orchestrator.executor import execute_approved
    _, _, sid, aid = paused_without_worker(mutable_graph, settings)
    assert review(make_client(mutable_graph.name), aid).status_code == 200
    repo = GraphRepository(mutable_graph, SCOPE)
    [result] = execute_approved(repo, None, sid, now_ms=NOW)
    assert result["result"] == "skipped" and "fails closed" in result["note"]
    assert repo.get_node("AgentAction", aid)["status"] == "approved"


def test_a_replayed_execution_never_runs_twice(mutable_graph, settings, make_client):
    from app.orchestrator.executor import execute_approved
    sid, aid = simulate(mutable_graph, settings)
    http = make_client(mutable_graph.name)
    assert review(http, aid).status_code == 200
    repo, orch = GraphRepository(mutable_graph, SCOPE), _ORCH[mutable_graph.name]
    first = repo.get_node("AgentAction", aid)["execution_json"]
    # a lost status write: the graph says approved again while the idempotency record says it already ran
    repo.update_node("AgentAction", aid, {"status": "approved"}, at_ms=NOW)
    [result] = execute_approved(repo, orch.env.deps.idempotency, sid, now_ms=NOW + 5_000)
    assert result["result"] == "succeeded" and result["replayed"] is True
    a = repo.get_node("AgentAction", aid)
    assert a["status"] == "executed_simulated" and a["execution_json"] == first
    assert timeline_types(http).count("action_executed_simulated") == 1
    assert len(repo.neighbors("AgentAction", aid, "DERIVED_FROM", "AgentMemory", outgoing=False)) == 1


def test_a_validated_memory_is_not_reset_by_a_replay(mutable_graph, settings, make_client):
    from app.orchestrator.executor import execute_approved
    sid, aid = simulate(mutable_graph, settings)
    http = make_client(mutable_graph.name)
    mem_id = review(http, aid).json()["memory_id"]
    assert http.post(f"/api/memories/{mem_id}/validate", json={"outcome": "successful"},
                     headers=LEAD).status_code == 200
    repo, orch = GraphRepository(mutable_graph, SCOPE), _ORCH[mutable_graph.name]
    repo.update_node("AgentAction", aid, {"status": "approved"}, at_ms=NOW)
    execute_approved(repo, orch.env.deps.idempotency, sid, now_ms=NOW + 5_000)
    assert repo.get_node("AgentMemory", mem_id)["verification_status"] == "verified"


def test_a_multi_action_session_loops_through_review_rounds(mutable_graph, settings, make_client):
    sid, aid = simulate(mutable_graph, settings)
    orch = _ORCH[mutable_graph.name]
    other = second_action(GraphRepository(mutable_graph, SCOPE), sid, aid)
    http = make_client(mutable_graph.name)
    first = review(http, aid)
    assert first.json()["action"]["status"] == "executed_simulated"
    assert first.json()["investigation_status"] == "awaiting_review"
    snap = paused(orch, sid)
    assert snap.next == ("human_review",) and snap.values["review"]["pending"] == [other]
    last = review(http, other, "REJECT")
    assert last.json()["investigation_status"] == "completed"
    assert paused(orch, sid).next == ()


def test_postgres_idempotency_record_backs_a_single_execution(mutable_graph, settings, make_client, pool):
    from app.db.idempotency import PostgresIdempotencyStore
    from app.orchestrator.executor import execute_approved
    store = PostgresIdempotencyStore(pool)
    _, orch, sid, aid = paused_without_worker(mutable_graph, settings, store=store)
    assert review(make_client(mutable_graph.name), aid).status_code == 200
    assert orch.resume_review(sid, SCOPE) == "completed"
    repo = GraphRepository(mutable_graph, SCOPE)
    assert repo.get_node("AgentAction", aid)["status"] == "executed_simulated"
    with pool.connection() as conn:
        row = conn.execute("SELECT status, request_hash, response FROM ops.idempotency_records WHERE key = %s",
                           (f"{aid}:{repo.get_node('AgentAction', aid)['spec_hash']}",)).fetchone()
    assert row["status"] == "succeeded" and row["response"]["ticket"].startswith("SIM-")
    repo.update_node("AgentAction", aid, {"status": "approved"}, at_ms=NOW)        # replay: must not execute again
    [result] = execute_approved(repo, store, sid, now_ms=NOW + 1)
    assert result["replayed"] is True


def test_worker_poll_dispatches_a_review_resume_only_when_decided(mutable_graph, settings, make_client):
    _, orch, sid, aid = paused_without_worker(mutable_graph, settings)
    worker = Worker(settings, orchestrator=orch)
    worker.poll_once()
    assert worker._queue.empty()                                       # nothing decided: stay paused
    assert review(make_client(mutable_graph.name), aid).status_code == 200
    worker.poll_once()
    assert worker._queue.get_nowait() == (sid, SCOPE, "review")
    assert worker._queue.empty()                                       # not dispatched twice while in flight
