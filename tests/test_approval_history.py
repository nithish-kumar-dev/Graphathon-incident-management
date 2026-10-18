"""Approval and version history: an approval is bound to one action version and its spec hash."""

import pytest
from app.domain.actions import canonical_json, spec_hash
from app.graph.repository import GraphRepository, Scope
from app.seeds.novacommerce import ms

pytestmark = pytest.mark.integration

V1 = "nova.act.092.rollback.v1"
DURING = ms("2026-08-12T10:00:00")   # inside the approval window
AFTER = ms("2026-08-12T11:00:00")    # approval expired at 10:22Z


def test_seeded_approval_valid_only_inside_window(nova):
    assert [a["approval_id"] for a in nova.valid_approvals(V1, at_ms=DURING)] == ["nova.apr.092.rollback"]
    assert nova.valid_approvals(V1, at_ms=AFTER) == []


def test_approval_links_to_authenticated_responder(nova):
    a = nova.valid_approvals(V1, at_ms=DURING)[0]
    assert a["approver_id"] == a["responder_id"] == "nova.rsp.payments_lead"


def test_revision_invalidates_prior_approval(mutable_graph):
    repo = GraphRepository(mutable_graph, Scope("nova", "prod"))
    v1 = repo.get_node("AgentAction", V1)
    spec2 = canonical_json({**__import__("json").loads(v1["spec_json"]), "to_version": "v2.1"})
    repo.merge_node("AgentAction", "nova.act.092.rollback.v2", {
        "proposal_id": v1["proposal_id"], "version": 2, "action_type": v1["action_type"], "spec_json": spec2,
        "spec_hash": spec_hash(spec2), "target_service_id": v1["target_service_id"], "risk": "medium",
        "mode": "simulation", "status": "pending_review"})
    # Even if someone links the old approval record to the new version, it must not authorize it.
    repo.merge_edge("AgentAction", "nova.act.092.rollback.v2", "HAS_REVIEW", "ApprovalRecord", "nova.apr.092.rollback")
    assert repo.valid_approvals("nova.act.092.rollback.v2", at_ms=DURING) == []
    assert len(repo.valid_approvals(V1, at_ms=DURING)) == 1

    history = repo.action_versions(v1["proposal_id"])
    assert [(h["version"], h["status"]) for h in history] == [(1, "executed_simulated"), (2, "pending_review")]
    assert history[0]["spec_hash"] != history[1]["spec_hash"]
    assert all(r["spec_hash"] == history[0]["spec_hash"] for r in history[1]["reviews"])  # stale hash visible


def test_reject_is_never_a_valid_approval(mutable_graph):
    repo = GraphRepository(mutable_graph, Scope("nova", "prod"))
    v1 = repo.get_node("AgentAction", V1)
    repo.merge_node("ApprovalRecord", "nova.apr.092.reject", {
        "decision": "REJECT", "spec_hash": v1["spec_hash"], "action_version": 1,
        "approver_id": "nova.rsp.ledger_lead", "decided_at_ms": DURING, "expires_at_ms": AFTER})
    repo.merge_edge("AgentAction", V1, "HAS_REVIEW", "ApprovalRecord", "nova.apr.092.reject")
    ids = [a["approval_id"] for a in repo.valid_approvals(V1, at_ms=DURING)]
    assert ids == ["nova.apr.092.rollback"]
