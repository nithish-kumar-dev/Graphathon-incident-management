"""The evidence path behind the INC-101 recommendation, and how single-edge changes alter it
(refactor-plan §4; Phase 1 'show the exact evidence path')."""

import pytest
from app.graph.repository import GraphRepository, Scope
from app.seeds.novacommerce import ms

from .conftest import NOW

pytestmark = pytest.mark.integration

EXPECTED = {
    "incident_id": "nova.inc.101",
    "affected_service_id": "nova.svc.checkout",
    "service_path": ["nova.svc.checkout", "nova.svc.payment"],
    "path_rels": ["DEPENDS_ON"],
    "target_service_id": "nova.svc.payment",
    "deployment_id": "nova.dep.payment.v2_4",
    "deployment_version": "v2.4",
    "evidence_ids": ["nova.ev.101.deploy"],
    "evidence_source_refs": ["synthetic://deploys/payment/v2.4"],
    "active_decision_ids": ["nova.dec.payment.rollback_v2"],
    "required_approver_roles": ["approver:payment"],
    "runbook_ids": ["nova.rb.payment.rollback"],
}


def test_baseline_path(nova):
    assert nova.rollback_candidates("nova.inc.101", at_ms=NOW) == [EXPECTED]


def test_every_returned_id_exists(nova):
    row = nova.rollback_candidates("nova.inc.101", at_ms=NOW)[0]
    checks = [("Service", i) for i in row["service_path"]] + [("Deployment", row["deployment_id"])]
    checks += [("Evidence", i) for i in row["evidence_ids"]] + [("Decision", i) for i in row["active_decision_ids"]]
    checks += [("Runbook", i) for i in row["runbook_ids"]]
    for label, node_id in checks:
        assert nova.get_node(label, node_id) is not None, (label, node_id)


def test_red_herring_deployment_not_a_candidate(nova):
    """inventory v1.9 is reachable via checkout DEPENDS_ON inventory, but no INC-101 evidence refers to it."""
    ids = [r["deployment_id"] for r in nova.rollback_candidates("nova.inc.101", at_ms=NOW)]
    assert "nova.dep.inventory.v1_9" not in ids


def test_depth_bound_respected(nova):
    assert nova.rollback_candidates("nova.inc.101", depth=0, at_ms=NOW) == []
    assert nova.rollback_candidates("nova.inc.101", depth=1, at_ms=NOW) == [EXPECTED]


def test_removing_dependency_edge_removes_recommendation(mutable_graph):
    repo = GraphRepository(mutable_graph, Scope("nova", "prod"))
    assert repo.rollback_candidates("nova.inc.101", at_ms=NOW) == [EXPECTED]
    assert repo.delete_edge("Service", "nova.svc.checkout", "DEPENDS_ON", "Service", "nova.svc.payment") == 1
    assert repo.rollback_candidates("nova.inc.101", at_ms=NOW) == []
    repo.merge_edge("Service", "nova.svc.checkout", "DEPENDS_ON", "Service", "nova.svc.payment")
    assert repo.rollback_candidates("nova.inc.101", at_ms=NOW) == [EXPECTED]


def test_removing_governing_decision_changes_approver(mutable_graph):
    repo = GraphRepository(mutable_graph, Scope("nova", "prod"))
    repo.delete_edge("Decision", "nova.dec.payment.rollback_v2", "GOVERNS", "Service", "nova.svc.payment")
    row = repo.rollback_candidates("nova.inc.101", at_ms=NOW)[0]
    # The superseded v1 policy must NOT silently come back into force.
    assert row["active_decision_ids"] == [] and row["required_approver_roles"] == []
    assert row["deployment_id"] == "nova.dep.payment.v2_4"


def test_policy_effective_dates_respected(nova):
    """Before ADR-031 took effect (2026-06-01) no *active* policy was in force for payment."""
    row = nova.rollback_candidates("nova.inc.101", at_ms=ms("2026-05-01T00:00:00"))[0]
    assert row["active_decision_ids"] == []
