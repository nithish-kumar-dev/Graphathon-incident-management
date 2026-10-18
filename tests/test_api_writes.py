"""Phase 2 write paths (alert ingest, investigations, incident updates) on throwaway graphs."""

import pytest
from app.graph.repository import GraphRepository, Scope
from app.seeds.novacommerce import ms

from .conftest import RESPONDER, VIEWER

pytestmark = pytest.mark.integration


@pytest.fixture
def env(make_client, mutable_graph):
    return make_client(mutable_graph.name), GraphRepository(mutable_graph, Scope("nova", "prod")), mutable_graph


def alert(**over):
    body = {"fingerprint": "checkout:http_5xx_rate", "service_id": "nova.svc.checkout", "severity": "critical",
            "fired_at": "2026-10-17T14:10:00Z", "summary": "checkout 5xx 9%", "source_ref": "synthetic://alerts/t-1"}
    return {**body, **over}


def count(g, label):
    return g.ro_query(f"MATCH (n:{label}) RETURN count(n)").result_set[0][0]


# ------------------------------------------------------------------ alert ingest
def test_duplicate_within_window_dedups_onto_seeded_alert(env):
    api, repo, g = env
    before = count(g, "Alert")
    r = api.post("/api/alerts", json=alert(), headers=RESPONDER)
    assert r.status_code == 200
    assert r.json() | {} == {"outcome": "deduplicated", "alert_id": "nova.alr.101.checkout_5xx",
                             "incident_id": "nova.inc.101", "incident_key": "INC-101", "dedup_count": 1,
                             "dedup_window_seconds": 900}
    r2 = api.post("/api/alerts", json=alert(), headers=RESPONDER)      # exact replay
    assert (r2.status_code, r2.json()["outcome"], r2.json()["dedup_count"]) == (200, "replayed", 1)
    r3 = api.post("/api/alerts", json=alert(source_ref="synthetic://alerts/t-2"), headers=RESPONDER)
    assert (r3.json()["outcome"], r3.json()["dedup_count"]) == ("deduplicated", 2)
    assert count(g, "Alert") == before
    a = repo.get_node("Alert", "nova.alr.101.checkout_5xx")
    assert a["last_fired_at_ms"] == ms("2026-10-17T14:10:00") and a["dedup_count"] == 2


def test_outside_window_attaches_to_open_incident(env):
    api, repo, _g = env
    r = api.post("/api/alerts", json=alert(fired_at="2026-10-17T14:40:00Z"), headers=RESPONDER)
    assert r.status_code == 201
    j = r.json()
    assert (j["outcome"], j["incident_id"]) == ("attached_to_incident", "nova.inc.101")
    assert j["alert_id"].startswith("nova.alr.") and repo.get_node("Alert", j["alert_id"])["summary_redacted"]
    detail = api.get("/api/incidents/nova.inc.101", headers=VIEWER).json()
    assert j["alert_id"] in {a["id"] for a in detail["alerts"]}
    types = [e["type"] for e in api.get("/api/incidents/nova.inc.101/timeline", headers=VIEWER).json()["events"]]
    assert types.count("alert_fired") == 3


def test_new_service_opens_incident_idempotently(env):
    api, repo, g = env
    body = alert(fingerprint="auth:error_rate", service_id="nova.svc.auth", severity="warning",
                 source_ref="synthetic://alerts/auth-1", summary="auth errors from 10.0.0.12 for ops@nova.example")
    r = api.post("/api/alerts", json=body, headers=RESPONDER)
    assert r.status_code == 201
    j = r.json()
    assert (j["outcome"], j["incident_key"]) == ("created_incident", "INC-102")
    inc = api.get(f"/api/incidents/{j['incident_id']}", headers=VIEWER).json()
    assert (inc["severity"], inc["status"], inc["affected_service_ids"]) == ("sev3", "open", ["nova.svc.auth"])
    assert inc["explanation_paths"] == []              # no evidence refers to any deployment: no path, not an error
    stored = repo.get_node("Alert", j["alert_id"])["summary_redacted"]
    assert "10.0.0.12" not in stored and "ops@nova.example" not in stored
    assert "10.0.0.12" not in inc["title"]
    events = api.get(f"/api/incidents/{j['incident_id']}/timeline", headers=VIEWER).json()["events"]
    assert {e["type"] for e in events} == {"incident_opened", "alert_fired"}

    incidents_before = count(g, "Incident")
    r2 = api.post("/api/alerts", json=body, headers=RESPONDER)
    assert (r2.status_code, r2.json()["outcome"], r2.json()["incident_id"]) == (200, "replayed", j["incident_id"])
    assert count(g, "Incident") == incidents_before

    # A different service with no open incident gets the next key.
    r3 = api.post("/api/alerts", json=alert(fingerprint="ledger:lag", service_id="nova.svc.ledger",
                                            source_ref="synthetic://alerts/ledger-1"), headers=RESPONDER)
    assert r3.json()["incident_key"] == "INC-103"


def test_replay_heals_alert_left_without_incident(env):
    """Simulates a crash after the alert was written but before it was correlated."""
    api, repo, g = env
    from app.services.alerts import _bucket_id
    at = ms("2026-10-17T14:30:00")
    alert_id = _bucket_id(repo, "inventory:stock_errors", at, 900_000)
    repo.merge_alert(alert_id, {"fingerprint": "inventory:stock_errors", "severity": "warning", "fired_at_ms": at,
                                "source_ref": "synthetic://alerts/inv-1", "service_id": "nova.svc.inventory"}, at_ms=at)
    r = api.post("/api/alerts", json=alert(fingerprint="inventory:stock_errors", service_id="nova.svc.inventory",
                                           severity="warning", fired_at="2026-10-17T14:30:00Z",
                                           source_ref="synthetic://alerts/inv-1"), headers=RESPONDER)
    assert (r.status_code, r.json()["outcome"]) == (200, "replayed")
    assert r.json()["incident_id"] is not None
    assert integrity_ok(g)


def integrity_ok(g):
    from app.graph import integrity
    rep = integrity.run(g)
    return rep.ok or rep.problems


@pytest.mark.parametrize("over,code", [
    ({"fired_at": "2026-10-17T15:10:00Z"}, "fired_at_out_of_range"),      # 10 min in the future
    ({"fired_at": "2026-10-01T00:00:00Z"}, "fired_at_out_of_range"),      # older than 7 days
    ({"service_id": "nova.svc.nope"}, "unknown_reference"),
    ({"service_id": "acme.svc.checkout"}, "unknown_reference"),            # other tenant's service
])
def test_ingest_rejects_bad_references(env, over, code):
    api, _, _ = env
    r = api.post("/api/alerts", json=alert(**over, source_ref="synthetic://alerts/bad"), headers=RESPONDER)
    assert (r.status_code, r.json()["error"]["code"]) == (422, code)


def test_viewer_cannot_ingest(env):
    api, _, _ = env
    assert api.post("/api/alerts", json=alert(), headers=VIEWER).status_code == 403


# ------------------------------------------------------------------ investigations
def test_create_investigation_flow(env):
    api, repo, _ = env
    r = api.post("/api/investigations", json={"incident_id": "nova.inc.101", "mode": "recommendation_only"},
                 headers=RESPONDER)
    assert r.status_code == 201
    j = r.json()
    assert (j["status"], j["mode"], j["incident_id"], j["requested_by"]) == (
        "queued", "recommendation_only", "nova.inc.101", "demo-responder")
    assert {b: s["status"] for b, s in j["branches"].items()} == dict.fromkeys(
        ("graph_context", "memory_context", "telemetry_context"), "pending")
    assert j["findings"] == [] and j["thread_id"].startswith("inv-")
    assert api.get(f"/api/investigations/{j['id']}", headers=VIEWER).json()["id"] == j["id"]
    assert repo.get_node("Incident", "nova.inc.101")["status"] == "investigating"
    types = [e["type"] for e in api.get("/api/incidents/nova.inc.101/timeline", headers=VIEWER).json()["events"]]
    assert "investigation_requested" in types and "status_change" in types

    again = api.post("/api/investigations", json={"incident_id": "nova.inc.101", "mode": "recommendation_only"},
                     headers=RESPONDER)
    assert (again.status_code, again.json()["id"]) == (200, j["id"])
    other = api.post("/api/investigations", json={"incident_id": "nova.inc.101", "mode": "simulation"},
                     headers=RESPONDER)
    assert (other.status_code, other.json()["error"]["code"]) == (409, "investigation_in_progress")


def test_investigation_conflicts_and_missing(env):
    api, _, _ = env
    r = api.post("/api/investigations", json={"incident_id": "nova.inc.092"}, headers=RESPONDER)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "incident_resolved")
    assert api.post("/api/investigations", json={"incident_id": "nova.inc.404"}, headers=RESPONDER).status_code == 404
    assert api.post("/api/investigations", json={"incident_id": "nova.inc.101"}, headers=VIEWER).status_code == 403


def test_nonexistent_cited_evidence_is_never_returned(env):
    api, repo, _ = env
    repo.update_node("AgentSession", "nova.ses.092", {"findings_json": (
        '[{"claim_type":"hypothesis","statement":"s","evidence_ids":["nova.ev.092.deploy","nova.ev.ghost"]}]')})
    j = api.get("/api/investigations/nova.ses.092", headers=VIEWER).json()
    assert [e["id"] for e in j["findings"][0]["evidence"]] == ["nova.ev.092.deploy"]
    assert "nova.ev.ghost" not in str(j)
    assert j["findings"][0]["integrity_warnings"] == ["1 cited evidence id(s) not found in the graph; omitted"]

    repo.update_node("AgentSession", "nova.ses.092", {"findings_json": '[{"claim_type":"proven","statement":"x"}]'})
    j = api.get("/api/investigations/nova.ses.092", headers=VIEWER).json()
    assert j["findings"] == [] and j["integrity_warnings"] == ["stored findings failed validation and were withheld"]


# ------------------------------------------------------------------ incident updates
def test_incident_status_transitions(env):
    api, _repo, _ = env
    r = api.patch("/api/incidents/nova.inc.101", json={"status": "mitigated", "severity": "sev1"}, headers=RESPONDER)
    assert (r.status_code, r.json()["status"], r.json()["severity"]) == (200, "mitigated", "sev1")
    r = api.patch("/api/incidents/nova.inc.101", json={"status": "resolved"}, headers=RESPONDER)
    assert r.json()["resolved_at"] == "2026-10-17T15:00:00Z"
    r = api.patch("/api/incidents/nova.inc.101", json={"status": "open"}, headers=RESPONDER)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "invalid_transition")
    events = api.get("/api/incidents/nova.inc.101/timeline", headers=VIEWER).json()["events"]
    mine = [e["type"] for e in events if e["actor"] == "demo-responder"]
    assert mine.count("status_change") == 2 and mine.count("severity_change") == 1

    # After resolution a new alert for checkout opens a fresh incident instead of reopening.
    r = api.post("/api/alerts", json=alert(fired_at="2026-10-17T14:50:00Z", source_ref="synthetic://alerts/t-9"),
                 headers=RESPONDER)
    assert r.json()["outcome"] == "created_incident"


def test_incident_update_permissions_and_validation(env):
    api, _, _ = env
    assert api.patch("/api/incidents/nova.inc.101", json={"status": "mitigated"}, headers=VIEWER).status_code == 403
    assert api.patch("/api/incidents/nova.inc.101", json={}, headers=RESPONDER).status_code == 422
    assert api.patch("/api/incidents/nova.inc.404", json={"severity": "sev1"}, headers=RESPONDER).status_code == 404


def test_concurrent_duplicates_collapse_to_one_alert(env):
    from concurrent.futures import ThreadPoolExecutor

    api, repo, g = env
    body = {"fingerprint": "inventory:latency", "service_id": "nova.svc.inventory", "severity": "warning",
            "fired_at": "2026-10-17T14:20:00Z", "summary": "inventory slow"}
    before = count(g, "Alert")
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(
            lambda i: api.post("/api/alerts", json={**body, "source_ref": f"synthetic://alerts/c-{i}"},
                               headers=RESPONDER).json(), range(20)))
    outcomes = sorted(r["outcome"] for r in results)
    # Exactly one request created the alert; which request opened the incident is an implementation detail.
    assert outcomes.count("deduplicated") == 19
    assert len([o for o in outcomes if o in ("created_incident", "attached_to_incident")]) == 1
    assert len({r["alert_id"] for r in results}) == 1 and len({r["incident_id"] for r in results}) == 1
    assert count(g, "Alert") == before + 1
    assert repo.get_node("Alert", results[0]["alert_id"])["dedup_count"] == 19
    events = api.get(f"/api/incidents/{results[0]['incident_id']}/timeline", headers=VIEWER).json()["events"]
    assert sorted(e["type"] for e in events) == ["alert_fired", "incident_opened"]
