"""Tenant scoping, invalid relationships, and graceful outage handling."""

import pytest
from app.graph import client, integrity
from app.graph.client import GraphUnavailable
from app.graph.repository import EndpointNotFound, GraphRepository, Scope, TenantConflict
from app.graph.schema import SchemaViolation

from .conftest import NOW

pytestmark = pytest.mark.integration


def test_other_tenant_node_invisible(nova, acme):
    assert nova.get_node("Service", "nova.svc.checkout")["name"] == "checkout"
    assert nova.get_node("Service", "acme.svc.checkout") is None
    assert acme.get_node("Service", "nova.svc.checkout") is None


def test_other_tenant_incident_returns_no_paths(nova, acme):
    assert acme.rollback_candidates("nova.inc.101", at_ms=NOW) == []
    assert nova.rollback_candidates("acme.inc.7", at_ms=NOW) == []
    acme_rows = acme.rollback_candidates("acme.inc.7", at_ms=NOW)
    assert [r["deployment_id"] for r in acme_rows] == ["acme.dep.payment.v9"]


def test_scoped_results_contain_only_own_tenant_ids(nova):
    for row in nova.rollback_candidates("nova.inc.101", at_ms=NOW):
        ids = [*row["service_path"], row["deployment_id"], *row["evidence_ids"], *row["active_decision_ids"],
               *row["runbook_ids"]]
        assert all(i.startswith("nova.") for i in ids), ids


def test_wrong_env_sees_nothing(seeded_graph):
    staging = GraphRepository(seeded_graph, Scope("nova", "staging"))
    assert staging.get_node("Service", "nova.svc.checkout") is None


def test_cannot_overwrite_other_tenant_node(seeded_graph):
    nova_repo = GraphRepository(seeded_graph, Scope("nova", "prod"))
    with pytest.raises(TenantConflict):
        nova_repo.merge_node("Service", "acme.svc.checkout", {"name": "hijacked"})
    row = seeded_graph.ro_query("MATCH (s:Service {id:'acme.svc.checkout'}) RETURN s.name, s.tenant_id").result_set
    assert row == [["checkout", "acme"]]


def test_cross_tenant_edge_rejected(nova):
    with pytest.raises(EndpointNotFound):
        nova.merge_edge("Service", "nova.svc.checkout", "DEPENDS_ON", "Service", "acme.svc.payment")


def test_edge_to_missing_node_rejected(nova):
    with pytest.raises(EndpointNotFound):
        nova.merge_edge("Incident", "nova.inc.101", "AFFECTS", "Service", "nova.svc.does_not_exist")


def test_reversed_edge_rejected_before_query(nova):
    with pytest.raises(SchemaViolation):
        nova.merge_edge("Service", "nova.svc.checkout", "OWNS", "Team", "nova.team.storefront")


def test_invalid_scope_rejected(seeded_graph):
    for tenant, env in [("Nova", "prod"), ("nova", "production"), ("nova' OR 1=1", "prod")]:
        with pytest.raises(SchemaViolation):
            GraphRepository(seeded_graph, Scope(tenant, env))


def test_integrity_detects_raw_invalid_edge(mutable_graph):
    mutable_graph.query("MATCH (a:Alert {id:'nova.alr.101.checkout_5xx'}), (i:Incident {id:'nova.inc.101'}) "
                        "CREATE (a)-[:GROUPED_INTO {tenant_id:'nova'}]->(i)")
    mutable_graph.query("CREATE (:Service {id:'nova.svc.orphan', tenant_id:'nova', env:'prod', name:'orphan'})")
    rep = integrity.run(mutable_graph)
    assert ("Alert", "GROUPED_INTO", "Incident", 1) in rep.invalid_triples
    assert ("Service", "nova.svc.orphan") in rep.orphans
    assert not rep.ok


def test_integrity_detects_unvalidated_verified_memory(mutable_graph):
    # The repository refuses to write this, so simulate a raw write that bypassed it.
    mutable_graph.query(
        "MATCH (i:Incident {id:'nova.inc.101'}) CREATE (m:AgentMemory {id:'nova.mem.bad', tenant_id:'nova', env:'prod', "
        "memory_type:'episodic', verification_status:'verified', outcome:'successful', summary:'self-verified'})"
        "-[:ABOUT {tenant_id:'nova'}]->(i)")
    assert integrity.run(mutable_graph).unvalidated_verified_memory == ["nova.mem.bad"]


def test_graph_outage_raises_clean_error():
    with pytest.raises(GraphUnavailable) as exc:
        client.connect("redis://127.0.0.1:1", socket_timeout=1.0)
    assert "127.0.0.1" not in str(exc.value)
    assert client.ping_url("redis://127.0.0.1:1") is False


def test_outage_after_connect_raises_clean_error():
    """Server gone mid-session: the repository maps the driver error to GraphUnavailable."""
    from falkordb import Graph
    from redis import Redis

    dead = Graph(Redis(host="127.0.0.1", port=1, socket_connect_timeout=1.0), "graphathon")
    repo = GraphRepository(dead, Scope("nova", "prod"))
    for call in (lambda: repo.get_node("Service", "nova.svc.checkout"),
                 lambda: repo.merge_node("Team", "nova.team.x", {"name": "x"})):
        with pytest.raises(GraphUnavailable) as exc:
            call()
        assert "127.0.0.1" not in str(exc.value)


def test_wait_until_ready_times_out():
    with pytest.raises(GraphUnavailable):
        client.wait_until_ready("redis://127.0.0.1:1", timeout_s=0.5, interval_s=0.1)
