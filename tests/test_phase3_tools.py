"""Phase 3 graph tools: named, read-only, bounded, tenant-scoped; outputs change with the graph."""

import pytest
from app.api.errors import NotFound
from app.graph.repository import GraphRepository, Scope
from app.seeds.novacommerce import ms
from app.tools import graph_tools as t
from app.tools.graph_tools import ReadOnlyGraph, ToolArgumentError, run_tool

from .conftest import rctx

pytestmark = pytest.mark.integration


def test_registry_has_the_eight_named_tools():
    assert set(t.TOOLS) == {"expand_dependencies", "get_recent_deployments", "get_incident_evidence",
                            "get_service_ownership", "get_current_decisions", "get_applicable_runbooks",
                            "get_verified_memories", "get_explanation_path"}


def test_tools_happy_path(seeded_graph):
    ctx = rctx(seeded_graph)
    deps = run_tool(ctx, "expand_dependencies", {"service_id": "nova.svc.checkout", "max_depth": 3})
    assert {(d.service.id, d.depth) for d in deps.items} == {
        ("nova.svc.payment", 1), ("nova.svc.inventory", 1), ("nova.svc.auth", 1), ("nova.svc.ledger", 2)}
    up = run_tool(ctx, "expand_dependencies", {"service_id": "nova.svc.ledger", "direction": "upstream"})
    assert [d.service.id for d in up.items] == ["nova.svc.payment", "nova.svc.checkout"]
    dep = run_tool(ctx, "get_recent_deployments", {"service_ids": ["nova.svc.payment", "nova.svc.inventory"]})
    assert [d.id for d in dep.items] == ["nova.dep.payment.v2_4", "nova.dep.inventory.v1_9"]
    ev = run_tool(ctx, "get_incident_evidence", {"incident_id": "nova.inc.101"})
    assert {e.id for e in ev.items} == {"nova.ev.101.deploy", "nova.ev.101.checkout_errors", "nova.ev.101.payment_latency"}
    own = run_tool(ctx, "get_service_ownership", {"service_id": "nova.svc.payment"})
    assert [team.id for team in own.teams] == ["nova.team.payments"]
    dec = run_tool(ctx, "get_current_decisions", {"service_id": "nova.svc.payment"})
    assert [(d.id, d.required_approver_role) for d in dec.items] == [("nova.dec.payment.rollback_v2", "approver:payment")]
    rb = run_tool(ctx, "get_applicable_runbooks", {"service_id": "nova.svc.payment",
                                                   "action_type": "rollback_deployment_simulated"})
    assert [r.id for r in rb.items] == ["nova.rb.payment.rollback"]
    assert run_tool(ctx, "get_applicable_runbooks", {"service_id": "nova.svc.payment",
                                                     "action_type": "restart_pods"}).items == []
    mem = run_tool(ctx, "get_verified_memories", {"incident_id": "nova.inc.101"})
    assert {x.id for x in mem.items} == {"nova.mem.092.rollback_success", "nova.mem.092.restart_failed"}
    assert mem.excluded_unverified == 1                       # the draft idea is counted, never returned
    no_failed = run_tool(ctx, "get_verified_memories", {"incident_id": "nova.inc.101", "include_failed": False})
    assert [x.id for x in no_failed.items] == ["nova.mem.092.rollback_success"]
    path = run_tool(ctx, "get_explanation_path", {"incident_id": "nova.inc.101"})
    assert [(p.deployment.id, p.claim_type) for p in path.paths] == [("nova.dep.payment.v2_4", "correlated")]


def test_time_windows(seeded_graph):
    ctx = rctx(seeded_graph)
    one_hour = run_tool(ctx, "get_recent_deployments", {"service_ids": ["nova.svc.payment"], "window_hours": 1})
    assert one_hour.items == []                                # v2.4 was 68 min before NOW
    before_adr031 = rctx(seeded_graph, now=ms("2026-05-01T00:00:00"))
    assert run_tool(before_adr031, "get_current_decisions", {"service_id": "nova.svc.payment"}).items == []


@pytest.mark.parametrize("name,args", [
    ("expand_dependencies", {"service_id": "nova.svc.checkout", "max_depth": 4}),
    ("expand_dependencies", {"service_id": "nova.svc.checkout", "max_depth": 0}),
    ("expand_dependencies", {"service_id": "nova.svc.checkout", "limit": 500}),
    ("expand_dependencies", {"service_id": "nova.inc.101"}),               # wrong id kind
    ("expand_dependencies", {"service_id": "nova.svc.checkout", "direction": "sideways"}),
    ("get_recent_deployments", {"service_ids": []}),
    ("get_recent_deployments", {"service_ids": [f"nova.svc.s{i}" for i in range(11)]}),
    ("get_recent_deployments", {"service_ids": ["nova.svc.payment"], "window_hours": 10_000}),
    ("get_incident_evidence", {"incident_id": "nova.inc.101", "cypher": "MATCH (n) DETACH DELETE n"}),
    ("get_applicable_runbooks", {"service_id": "nova.svc.payment", "action_type": "rm -rf /"}),
    ("no_such_tool", {}),
])
def test_invalid_tool_arguments_rejected(seeded_graph, name, args):
    with pytest.raises(ToolArgumentError):
        run_tool(rctx(seeded_graph), name, args)


def test_tool_argument_errors_do_not_echo_values(seeded_graph):
    with pytest.raises(ToolArgumentError) as exc:
        run_tool(rctx(seeded_graph), "get_incident_evidence", {"incident_id": "x'; DROP"})
    assert "DROP" not in str(exc.value)


def test_tools_are_read_only(seeded_graph):
    ro = ReadOnlyGraph(seeded_graph)
    with pytest.raises(PermissionError):
        ro.query("CREATE (:X)")
    ctx = rctx(seeded_graph)
    for name, args in [("expand_dependencies", {"service_id": "nova.svc.checkout"}),
                       ("get_verified_memories", {"incident_id": "nova.inc.101"}),
                       ("get_explanation_path", {"incident_id": "nova.inc.101"})]:
        run_tool(ctx, name, args)                              # would raise PermissionError on any write
    with pytest.raises(PermissionError):
        ctx.repo.merge_node("Team", "nova.team.x", {"name": "x"})


def test_query_timeout_is_applied(seeded_graph, monkeypatch):
    seen = []
    original = seeded_graph.ro_query

    def spy(q, params=None, timeout=None):
        seen.append(timeout)
        return original(q, params, timeout=timeout)

    monkeypatch.setattr(seeded_graph, "ro_query", spy)
    from app.tools.graph_tools import ToolContext
    ctx = ToolContext.read_only(seeded_graph, Scope("nova", "prod"), now_ms=0, timeout_ms=777)
    run_tool(ctx, "get_service_ownership", {"service_id": "nova.svc.payment"})
    assert seen and set(seen) == {777}


def test_tools_are_tenant_scoped(seeded_graph):
    acme = rctx(seeded_graph, tenant="acme")
    with pytest.raises(NotFound):
        run_tool(acme, "get_service_ownership", {"service_id": "nova.svc.payment"})
    with pytest.raises(NotFound):
        run_tool(acme, "get_explanation_path", {"incident_id": "nova.inc.101"})
    paths = run_tool(acme, "get_explanation_path", {"incident_id": "acme.inc.7"}).paths
    ids = {h[k] for p in paths for h in (x.model_dump() for x in p.hops) for k in ("from_id", "to_id")}
    assert ids and all(i.startswith("acme.") for i in ids)


def test_truncation_flag(seeded_graph):
    r = run_tool(rctx(seeded_graph), "expand_dependencies", {"service_id": "nova.svc.checkout", "max_depth": 3,
                                                             "limit": 2})
    assert len(r.items) == 2 and r.truncated


def test_outputs_change_after_edge_mutation(mutable_graph):
    ctx = rctx(mutable_graph)
    writer = GraphRepository(mutable_graph, Scope("nova", "prod"))
    before = {d.service.id for d in run_tool(ctx, "expand_dependencies",
                                             {"service_id": "nova.svc.checkout", "max_depth": 3}).items}
    assert {"nova.svc.payment", "nova.svc.ledger"} <= before
    assert run_tool(ctx, "get_explanation_path", {"incident_id": "nova.inc.101"}).paths
    writer.delete_edge("Service", "nova.svc.checkout", "DEPENDS_ON", "Service", "nova.svc.payment")
    after = {d.service.id for d in run_tool(ctx, "expand_dependencies",
                                            {"service_id": "nova.svc.checkout", "max_depth": 3}).items}
    assert after == {"nova.svc.inventory", "nova.svc.auth"}     # ledger was only reachable through payment
    assert run_tool(ctx, "get_explanation_path", {"incident_id": "nova.inc.101"}).paths == []
