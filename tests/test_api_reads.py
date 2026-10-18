"""Phase 2 read endpoints against the shared seeded graph (no writes)."""

import pytest
from app.graph.repository import GraphRepository, Scope

from .conftest import ACME, VIEWER

pytestmark = pytest.mark.integration

GOLDEN_HOPS = [
    ("Incident", "nova.inc.101", "AFFECTS", "Service", "nova.svc.checkout"),
    ("Service", "nova.svc.checkout", "DEPENDS_ON", "Service", "nova.svc.payment"),
    ("Deployment", "nova.dep.payment.v2_4", "DEPLOYED_TO", "Service", "nova.svc.payment"),
    ("Incident", "nova.inc.101", "HAS_EVIDENCE", "Evidence", "nova.ev.101.deploy"),
    ("Evidence", "nova.ev.101.deploy", "REFERS_TO", "Deployment", "nova.dep.payment.v2_4"),
]


@pytest.fixture
def api(make_client, seeded_graph):
    return make_client(seeded_graph.name)


def _hops(path):
    return [(h["from_label"], h["from_id"], h["rel"], h["to_label"], h["to_id"]) for h in path["hops"]]


# ------------------------------------------------------------------ golden case
def test_golden_incident_is_source_backed(api):
    r = api.get("/api/incidents/nova.inc.101", headers=VIEWER)
    assert r.status_code == 200
    d = r.json()
    assert (d["key"], d["status"], d["data_classification"]) == ("INC-101", "open", "synthetic")
    assert [p["claim_type"] for p in d["explanation_paths"]] == ["correlated"]
    path = d["explanation_paths"][0]
    assert _hops(path) == GOLDEN_HOPS
    assert path["deployment"]["id"] == "nova.dep.payment.v2_4"
    assert [(e["id"], e["source_ref"]) for e in path["evidence"]] == [
        ("nova.ev.101.deploy", "synthetic://deploys/payment/v2.4")]
    assert [(g["id"], g["required_approver_role"], [doc["id"] for doc in g["documented_in"]])
            for g in path["governing_decisions"]] == [("nova.dec.payment.rollback_v2", "approver:payment",
                                                       ["nova.doc.adr_031"])]
    assert [rb["id"] for rb in path["runbooks"]] == ["nova.rb.payment.rollback"]
    assert path["approval_policy"] == "policy_in_force"
    assert {a["id"] for a in d["alerts"]} == {"nova.alr.101.checkout_5xx", "nova.alr.101.payment_latency"}
    assert all(e["source_ref"].startswith("synthetic://") for e in d["evidence"])


def test_every_id_in_responses_exists(api, seeded_graph):
    repo = GraphRepository(seeded_graph, Scope("nova", "prod"))
    detail = api.get("/api/incidents/nova.inc.101", headers=VIEWER).json()
    mems = api.get("/api/incidents/nova.inc.101/memories?include_unverified=true", headers=VIEWER).json()
    inv = api.get("/api/investigations/nova.ses.092", headers=VIEWER).json()
    evidence_ids = {e["id"] for e in detail["evidence"]}
    evidence_ids |= {e["id"] for p in detail["explanation_paths"] for e in p["evidence"]}
    evidence_ids |= {e["id"] for m in mems["memories"] for e in m["grounded_in"]}
    evidence_ids |= {e["id"] for f in inv["findings"] for e in f["evidence"]} | {e["id"] for e in inv["evidence_refs"]}
    assert evidence_ids and set(repo.get_nodes("Evidence", list(evidence_ids))) == evidence_ids
    label_of = {"Incident": "Incident", "Service": "Service", "Deployment": "Deployment", "Evidence": "Evidence"}
    for p in detail["explanation_paths"]:
        for h in p["hops"]:
            assert repo.get_node(label_of[h["from_label"]], h["from_id"]) is not None
            assert repo.get_node(label_of[h["to_label"]], h["to_id"]) is not None


# ---------------------------------------------------------------- not found / scoping
def test_missing_incident_404_envelope(api):
    r = api.get("/api/incidents/nova.inc.999", headers=VIEWER)
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "not_found" and err["request_id"] == r.headers["x-request-id"]


def test_request_id_is_echoed_when_valid(api):
    r = api.get("/api/incidents/nova.inc.999", headers={**VIEWER, "X-Request-ID": "test-req-12345"})
    assert r.headers["x-request-id"] == "test-req-12345" == r.json()["error"]["request_id"]
    r = api.get("/healthz", headers={"X-Request-ID": "bad id with spaces"})
    assert r.headers["x-request-id"] != "bad id with spaces"


def test_other_tenant_resources_are_404(api):
    assert api.get("/api/incidents/nova.inc.101", headers=ACME).status_code == 404
    assert api.get("/api/incidents/acme.inc.7", headers=VIEWER).status_code == 404
    assert api.get("/api/services/acme.svc.payment/context", headers=VIEWER).status_code == 404
    assert api.get("/api/investigations/nova.ses.092", headers=ACME).status_code == 404


def test_list_is_tenant_scoped(api):
    nova = {i["id"] for i in api.get("/api/incidents", headers=VIEWER).json()["items"]}
    acme = {i["id"] for i in api.get("/api/incidents", headers=ACME).json()["items"]}
    assert nova == {"nova.inc.101", "nova.inc.092", "nova.inc.103", "nova.inc.104", "nova.inc.096", "nova.inc.087"}
    assert acme == {"acme.inc.7"}


def test_list_filters_and_pages(api):
    j = api.get("/api/incidents?status=resolved", headers=VIEWER).json()
    assert [i["key"] for i in j["items"]] == ["INC-096", "INC-092", "INC-087"]
    assert [i["key"] for i in api.get("/api/incidents?limit=1", headers=VIEWER).json()["items"]] == ["INC-104"]
    assert [i["key"] for i in api.get("/api/incidents?limit=1&offset=1", headers=VIEWER).json()["items"]] == ["INC-101"]


def test_other_tenant_paths_never_leak(api):
    d = api.get("/api/incidents/acme.inc.7", headers=ACME).json()
    ids = {h[k] for p in d["explanation_paths"] for h in p["hops"] for k in ("from_id", "to_id")}
    assert ids and all(i.startswith("acme.") for i in ids)


# ---------------------------------------------------------------- memories
def test_memories_verified_by_default_with_precedent(api):
    j = api.get("/api/incidents/nova.inc.101/memories", headers=VIEWER).json()
    got = {m["id"]: (m["precedent"], m["relation"], m["shared_service_ids"]) for m in j["memories"]}
    assert got == {
        "nova.mem.092.rollback_success": ("supports", "shared_service", ["nova.svc.checkout"]),
        "nova.mem.092.restart_failed": ("warns_against", "shared_service", ["nova.svc.checkout"]),
    }
    success = next(m for m in j["memories"] if m["id"] == "nova.mem.092.rollback_success")
    assert [v["id"] for v in success["validated_by"]] == ["nova.rsp.payments_lead"]
    assert {e["id"] for e in success["grounded_in"]} == {"nova.ev.092.deploy", "nova.ev.092.recovery"}
    assert success["derived_from_action_ids"] == ["nova.act.092.rollback.v1"]


def test_memories_include_unverified_only_on_request(api):
    j = api.get("/api/incidents/nova.inc.101/memories?include_unverified=true", headers=VIEWER).json()
    draft = next(m for m in j["memories"] if m["verification_status"] == "draft")
    assert draft["id"] == "nova.mem.092.cache_ttl_idea" and draft["precedent"] == "none"
    assert j["memories"][-1]["id"] == draft["id"]  # unverified sorts last


def test_memories_for_own_incident(api):
    j = api.get("/api/incidents/nova.inc.092/memories", headers=VIEWER).json()
    assert {m["relation"] for m in j["memories"]} == {"same_incident"}


# ---------------------------------------------------------------- service context
def test_service_context_payment(api):
    j = api.get("/api/services/nova.svc.payment/context", headers=VIEWER).json()
    assert [t["id"] for t in j["owners"]] == ["nova.team.payments"]
    assert {m["id"] for m in j["owners"][0]["members"]} == {"nova.rsp.payments_lead", "nova.rsp.payments_oncall"}
    assert {(d["service"]["id"], d["depth"]) for d in j["dependencies"]} == {("nova.svc.auth", 1), ("nova.svc.ledger", 1)}
    assert {(d["service"]["id"], tuple(d["path"])) for d in j["dependents"]} == {
        ("nova.svc.checkout", ("nova.svc.checkout", "nova.svc.payment")),
        ("nova.svc.gateway", ("nova.svc.gateway", "nova.svc.checkout", "nova.svc.payment")),
        ("nova.svc.notifications", ("nova.svc.notifications", "nova.svc.checkout", "nova.svc.payment")),
    }
    assert [(d["id"], d["supersedes"]) for d in j["active_decisions"]] == [
        ("nova.dec.payment.rollback_v2", ["nova.dec.payment.rollback_v1"])]
    assert [d["id"] for d in j["recent_deployments"]] == ["nova.dep.payment.v2_4"]   # v2.3 is outside 30 days
    assert [r["id"] for r in j["runbooks"]] == ["nova.rb.payment.rollback"]


def test_service_context_depth_bounds_and_shortest_paths(api):
    j = api.get("/api/services/nova.svc.checkout/context?depth=1", headers=VIEWER).json()
    assert {d["service"]["id"] for d in j["dependencies"]} == {"nova.svc.payment", "nova.svc.inventory", "nova.svc.auth"}
    j = api.get("/api/services/nova.svc.checkout/context?depth=3", headers=VIEWER).json()
    deps = {d["service"]["id"]: d["depth"] for d in j["dependencies"]}
    assert deps == {"nova.svc.payment": 1, "nova.svc.inventory": 1, "nova.svc.auth": 1, "nova.svc.ledger": 2}


def test_service_with_no_neighbours_returns_empty_lists(api):
    j = api.get("/api/services/nova.svc.ledger/context", headers=VIEWER).json()
    assert j["dependencies"] == [] and j["active_decisions"] == [] and j["recent_deployments"] == []
    assert [d["service"]["id"] for d in j["dependents"]] == ["nova.svc.payment", "nova.svc.checkout"]


def test_unknown_service_404(api):
    assert api.get("/api/services/nova.svc.nope/context", headers=VIEWER).status_code == 404


# ---------------------------------------------------------------- investigations / timeline
def test_seeded_investigation_findings(api):
    j = api.get("/api/investigations/nova.ses.092", headers=VIEWER).json()
    assert (j["incident_id"], j["status"], j["mode"]) == ("nova.inc.092", "completed", "simulation")
    assert [f["claim_type"] for f in j["findings"]] == ["confirmed"]
    assert {e["id"] for e in j["findings"][0]["evidence"]} == {
        "nova.ev.092.deploy", "nova.ev.092.checkout_errors", "nova.ev.092.recovery"}
    assert j["integrity_warnings"] == [] and j["findings"][0]["integrity_warnings"] == []
    assert set(j["branches"]) == {"graph_context", "memory_context", "telemetry_context"}


def test_timeline_ordered(api):
    events = api.get("/api/incidents/nova.inc.092/timeline", headers=VIEWER).json()["events"]
    assert [e["id"] for e in events] == ["nova.tl.092.1", "nova.tl.092.2", "nova.tl.092.3", "nova.tl.092.4"]
    assert events[2]["ref_id"] == "nova.apr.092.rollback"


# ---------------------------------------------------------------- auth + docs
def test_auth_required_and_unknown_user(api):
    assert api.get("/api/incidents").json()["error"]["code"] == "unauthenticated"
    assert api.get("/api/incidents", headers={"X-Demo-User": "mallory"}).status_code == 401


def test_tenant_not_enabled_is_403(make_client, seeded_graph):
    api = make_client(seeded_graph.name, tenant_allowlist="nova")
    assert api.get("/api/incidents", headers=ACME).status_code == 403


def test_openapi_and_swagger(api):
    spec = api.get("/openapi.json").json()
    assert set(spec["paths"]) >= {
        "/api/alerts", "/api/incidents", "/api/incidents/{incident_id}", "/api/incidents/{incident_id}/timeline",
        "/api/incidents/{incident_id}/memories", "/api/investigations", "/api/investigations/{investigation_id}",
        "/api/services/{service_id}/context"}
    assert "DemoUser" in spec["components"]["securitySchemes"]
    assert api.get("/docs").status_code == 200
