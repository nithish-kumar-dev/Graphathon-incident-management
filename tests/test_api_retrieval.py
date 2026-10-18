"""GET /api/incidents/{id}/retrieval: the hybrid investigator context over HTTP (read-only)."""

import json

import pytest
from app.api import deps
from app.graph.repository import GraphRepository, Scope
from app.main import app
from app.rag.embeddings import HashingEmbedder, OllamaEmbedder

from .conftest import ACME, VIEWER

pytestmark = pytest.mark.integration
URL = "/api/incidents/{}/retrieval"


@pytest.fixture
def api(make_client, rag_graph):
    client = make_client(rag_graph.name, retrieval_allowed_classifications="public,internal")
    app.dependency_overrides[deps.get_embedder] = lambda: HashingEmbedder()
    return client


def test_golden_incident_bundle(api, rag_graph):
    r = api.get(URL.format("nova.inc.101"), headers=VIEWER)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["incident_id"] == "nova.inc.101" and b["data_classification"] == "synthetic"
    assert {k: v["status"] for k, v in b["steps"].items()} == {"graph": "completed", "keyword": "completed",
                                                               "vector": "completed"}
    assert b["embedding_model"] == "test-hashing"

    paths = b["graph_context"]["explanation_paths"]
    assert [p["deployment"]["id"] for p in paths] == ["nova.dep.payment.v2_4"]
    assert [p["claim_type"] for p in paths] == ["correlated"]

    mems = {m["id"]: m for m in b["memory_context"]["items"]}
    assert {k: m["precedent"] for k, m in mems.items()} == {"nova.mem.092.rollback_success": "supports",
                                                            "nova.mem.092.restart_failed": "warns_against"}
    assert all(m["verification_status"] == "verified" and m["grounded_in"] and m["rationale"]
               for m in mems.values())
    assert b["memory_context"]["excluded"] == {"draft": 1}

    chunks = b["knowledge_context"]["items"]
    assert {"nova.doc.adr_031", "nova.doc.pm_092"} <= {c["document_id"] for c in chunks}
    assert chunks and all(c["claim_type"] == "context" for c in chunks)
    dumped = json.dumps(b)
    assert "nova.doc.sec_handbook" not in dumped                     # restricted: never returned
    assert '"confirmed"' not in dumped and '"hypothesis"' not in dumped

    repo = GraphRepository(rag_graph, Scope("nova", "prod"))
    assert set(repo.get_nodes("AgentMemory", list(mems))) == set(mems)
    chunk_ids = [c["id"] for c in chunks]
    assert set(repo.get_nodes("DocumentChunk", chunk_ids)) == set(chunk_ids)
    ev_ids = {e["id"] for m in mems.values() for e in m["grounded_in"]}
    assert set(repo.get_nodes("Evidence", list(ev_ids))) == ev_ids


def test_missing_incident_404(api):
    r = api.get(URL.format("nova.inc.999"), headers=VIEWER)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_other_tenant_is_404(api):
    assert api.get(URL.format("nova.inc.101"), headers=ACME).status_code == 404


def test_bad_id_is_422(api):
    assert api.get(URL.format("nova.svc.payment"), headers=VIEWER).status_code == 422


def test_embedder_unavailable_still_200(api):
    app.dependency_overrides[deps.get_embedder] = lambda: OllamaEmbedder(
        "http://127.0.0.1:1", "nomic-embed-text", 768, timeout_s=0.5)
    r = api.get(URL.format("nova.inc.101"), headers=VIEWER)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["steps"]["vector"]["status"] == "failed" and b["steps"]["keyword"]["status"] == "completed"
    assert b["embedding_model"] is None
    assert b["graph_context"]["explanation_paths"] and b["memory_context"]["items"]


def test_embedding_disabled_is_skipped(api):
    app.dependency_overrides[deps.get_embedder] = lambda: None
    b = api.get(URL.format("nova.inc.101"), headers=VIEWER).json()
    assert b["steps"]["vector"]["status"] == "skipped" and b["knowledge_context"]["items"]


def test_requires_identity(api):
    assert api.get(URL.format("nova.inc.101")).status_code == 401
    assert api.get(URL.format("nova.inc.101"), headers={"X-Demo-User": "nobody"}).status_code == 401
