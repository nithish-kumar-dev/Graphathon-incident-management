"""Input validation (422), payload limits (413), outages (503), hidden internals (500), JSON logs."""

import json
import logging

import pytest
from app.api import deps
from app.api.logging import JsonFormatter, request_id_var
from app.main import app
from falkordb import Graph
from redis import Redis

from .conftest import RESPONDER, VIEWER

pytestmark = pytest.mark.integration


@pytest.fixture
def api(make_client, seeded_graph):
    return make_client(seeded_graph.name)


GOOD = {"fingerprint": "checkout:http_5xx_rate", "service_id": "nova.svc.checkout", "severity": "critical",
        "fired_at": "2026-10-17T14:10:00Z", "summary": "x", "source_ref": "synthetic://alerts/v"}


@pytest.mark.parametrize("path", [
    "/api/incidents/not-an-id",
    "/api/incidents/nova.svc.checkout",                  # right shape, wrong kind
    "/api/incidents/nova.inc.101%27%20OR%201=1",
    "/api/services/nova.inc.101/context",
    "/api/investigations/nova.inc.101",
    "/api/incidents?limit=0",
    "/api/incidents?limit=1000",
    "/api/incidents?status=closed",
    "/api/services/nova.svc.payment/context?depth=4",
    "/api/services/nova.svc.payment/context?depth=0",
])
def test_malformed_reads_422(api, path):
    r = api.get(path, headers=VIEWER)
    assert r.status_code == 422, path
    assert r.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("over", [
    {"extra": "field"},
    {"severity": "sev1"},
    {"fired_at": "2026-10-17T14:10:00"},                 # naive datetime
    {"summary": "x" * 501},
    {"summary": ""},
    {"fingerprint": "Bad Fingerprint"},
    {"source_ref": "not a uri"},
    {"service_id": "nova.inc.101"},
])
def test_malformed_alert_422_never_echoes_input(api, over):
    body = {**GOOD, **over}
    r = api.post("/api/alerts", json=body, headers=RESPONDER)
    assert r.status_code == 422
    text = r.text
    for v in over.values():
        if isinstance(v, str) and len(v) > 3:
            assert v not in text


def test_malformed_json_and_investigation_mode(api):
    r = api.post("/api/alerts", content=b"{not json", headers={**RESPONDER, "content-type": "application/json"})
    assert r.status_code == 422
    r = api.post("/api/investigations", json={"incident_id": "nova.inc.101", "mode": "autopilot"}, headers=RESPONDER)
    assert r.status_code == 422


def test_body_too_large_413(api):
    r = api.post("/api/alerts", content=b"x" * 70_000, headers={**RESPONDER, "content-type": "application/json"})
    assert (r.status_code, r.json()["error"]["code"]) == (413, "payload_too_large")

    def chunks():
        for _ in range(80):
            yield b"x" * 1000

    r = api.post("/api/alerts", content=chunks(), headers={**RESPONDER, "content-type": "application/json"})
    assert r.status_code == 413


def test_graph_outage_503(make_client, seeded_graph):
    api = make_client(seeded_graph.name, falkordb_url="redis://127.0.0.1:1")
    r = api.get("/api/incidents", headers=VIEWER)
    assert r.status_code == 503 and r.headers["retry-after"] == "5"
    assert r.json()["error"]["code"] == "dependency_unavailable"
    assert "127.0.0.1" not in r.text and "redis" not in r.text.lower()


def test_graph_drops_mid_session_503(api):
    app.dependency_overrides[deps.get_graph] = lambda: Graph(Redis(host="127.0.0.1", port=1,
                                                                   socket_connect_timeout=1), "x")
    try:
        r = api.get("/api/incidents/nova.inc.101", headers=VIEWER)
        assert (r.status_code, r.json()["error"]["code"]) == (503, "dependency_unavailable")
    finally:
        app.dependency_overrides.pop(deps.get_graph)


def test_internal_errors_are_opaque(api):
    def boom():
        raise RuntimeError("secret-internal-detail /etc/passwd")

    app.dependency_overrides[deps.get_repo] = boom
    try:
        r = api.get("/api/incidents", headers=VIEWER)
        assert (r.status_code, r.json()["error"]["code"]) == (500, "internal_error")
        assert "secret" not in r.text and "Traceback" not in r.text
    finally:
        app.dependency_overrides.pop(deps.get_repo)


def test_readyz_503_when_graph_down(make_client, seeded_graph):
    api = make_client(seeded_graph.name, falkordb_url="redis://127.0.0.1:1")
    r = api.get("/readyz")
    assert r.status_code == 503 and r.json()["checks"]["falkordb"] is False


def test_json_log_lines_carry_request_id():
    token = request_id_var.set("req-abc-12345")
    try:
        rec = logging.LogRecord("app.test", logging.INFO, __file__, 1, "hello %s", ("world",), None)
        rec.status = 200
        line = json.loads(JsonFormatter().format(rec))
    finally:
        request_id_var.reset(token)
    assert line["msg"] == "hello world" and line["request_id"] == "req-abc-12345" and line["status"] == 200
