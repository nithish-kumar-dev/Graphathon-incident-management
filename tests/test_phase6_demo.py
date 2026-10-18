"""Phase 6 demo controls: gated, permissioned, idempotent edge toggles that change the recommendation."""

import pytest
from app.graph.repository import GraphRepository, Scope

from .conftest import RESPONDER, VIEWER

pytestmark = pytest.mark.integration

LEAD = {"X-Demo-User": "payments-lead"}
INC = "nova.inc.101"
DEP, GOV = "checkout_depends_on_payment", "rollback_policy_governs_payment"


@pytest.fixture
def env(make_client, mutable_graph):
    api = make_client(mutable_graph.name, demo_controls_enabled=True)
    return api, GraphRepository(mutable_graph, Scope("nova", "prod"))


def edge_count(graph, tenant):
    q = (f"MATCH (:Service {{id:'{tenant}.svc.checkout'}})-[r:DEPENDS_ON]->(:Service {{id:'{tenant}.svc.payment'}}) "
         "RETURN count(r)")
    return graph.ro_query(q).result_set[0][0]


def controls(api, headers=VIEWER, incident=INC):
    r = api.get("/api/demo/controls", params={"incident_id": incident}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def put(api, toggle, present, headers=RESPONDER, incident=INC):
    return api.put(f"/api/demo/controls/{toggle}", params={"incident_id": incident}, json={"present": present},
                   headers=headers)


def present(body):
    return {t["id"]: t["present"] for t in body["toggles"]}


def test_disabled_by_default_hides_the_panel_and_rejects_writes(make_client, mutable_graph):
    api = make_client(mutable_graph.name)
    assert api.get("/api/demo/controls", headers=VIEWER).json() == {"enabled": False, "toggles": [], "effect": None}
    r = api.put(f"/api/demo/controls/{DEP}", json={"present": False}, headers=RESPONDER)
    assert r.status_code == 404 and r.json()["error"]["code"] == "demo_controls_disabled"
    assert api.put("/api/demo/controls/reset", headers=RESPONDER).status_code == 404


def test_seeded_state_shows_both_edges_and_the_golden_recommendation(env):
    api, _ = env
    body = controls(api)
    assert body["enabled"] and present(body) == {DEP: True, GOV: True}
    assert {t["edge"] for t in body["toggles"]} == {
        "nova.svc.checkout -[DEPENDS_ON]-> nova.svc.payment",
        "nova.dec.payment.rollback_v2 -[GOVERNS]-> nova.svc.payment"}
    effect = body["effect"]
    assert effect["approval_policy"] == "policy_in_force" and effect["rollback_paths"] >= 1
    assert "nova.svc.payment" in effect["target_service_ids"] and effect["deployment_ids"]


def test_removing_the_dependency_removes_the_rollback_path_and_restoring_brings_it_back(env):
    api, repo = env
    r = put(api, DEP, False)
    assert r.status_code == 200
    assert present(r.json()) == {DEP: False, GOV: True}
    assert r.json()["effect"]["approval_policy"] == "no_rollback_path" and r.json()["effect"]["rollback_paths"] == 0
    assert edge_count(repo.graph, "nova") == 0
    again = put(api, DEP, False)                                           # idempotent
    assert again.status_code == 200 and present(again.json())[DEP] is False
    back = put(api, DEP, True)
    assert present(back.json()) == {DEP: True, GOV: True} and back.json()["effect"]["approval_policy"] == "policy_in_force"
    assert put(api, DEP, True).status_code == 200                          # merging twice does not duplicate
    assert edge_count(repo.graph, "nova") == 1


def test_removing_the_governing_decision_forces_escalation(env):
    api, _ = env
    r = put(api, GOV, False, headers=LEAD)
    assert present(r.json()) == {DEP: True, GOV: False}
    effect = r.json()["effect"]
    assert effect["approval_policy"] == "no_active_policy_escalate" and effect["rollback_paths"] >= 1
    assert "escalate" in effect["summary"]
    detail = api.get(f"/api/incidents/{INC}", headers=VIEWER).json()      # the incident page agrees
    assert all(p["approval_policy"] == "no_active_policy_escalate" for p in detail["explanation_paths"])


def test_reset_restores_both_edges(env):
    api, _ = env
    put(api, DEP, False)
    put(api, GOV, False)
    r = api.put("/api/demo/controls/reset", params={"incident_id": INC}, headers=LEAD)
    assert r.status_code == 200 and present(r.json()) == {DEP: True, GOV: True}
    assert r.json()["effect"]["approval_policy"] == "policy_in_force"


def test_viewer_cannot_toggle_and_unknown_toggle_is_404(env):
    api, _ = env
    r = put(api, DEP, False, headers=VIEWER)
    assert r.status_code == 403 and present(controls(api)) == {DEP: True, GOV: True}
    r = put(api, "no_such_toggle", False)
    assert r.status_code == 404 and r.json()["error"]["code"] == "unknown_toggle"
    assert api.put(f"/api/demo/controls/{DEP}", json={"present": False}).status_code == 401


def test_bad_input_is_rejected_before_any_write(env):
    api, _ = env
    assert api.put(f"/api/demo/controls/{DEP}", json={"present": "maybe"}, headers=RESPONDER).status_code == 422
    assert api.put(f"/api/demo/controls/{DEP}", json={"present": False, "extra": 1}, headers=RESPONDER).status_code == 422
    assert api.get("/api/demo/controls", params={"incident_id": "not an id"}, headers=VIEWER).status_code == 422
    assert api.get("/api/demo/controls", params={"incident_id": "nova.inc.missing"}, headers=VIEWER).status_code == 404
    assert present(controls(api)) == {DEP: True, GOV: True}


def test_toggles_are_tenant_scoped_and_never_touch_nodes(env):
    api, repo = env
    before = repo.graph.ro_query("MATCH (n) RETURN count(n)").result_set[0][0]
    put(api, DEP, False)
    put(api, GOV, False)
    assert repo.graph.ro_query("MATCH (n) RETURN count(n)").result_set[0][0] == before
    assert edge_count(repo.graph, "acme") == 1                             # the decoy tenant is untouched
