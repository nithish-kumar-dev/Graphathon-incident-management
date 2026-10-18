"""Hybrid retrieval: typed, traceable context; fallbacks; similar text never becomes a cause."""

import json

import httpx
import pytest
from app.graph import integrity, migrate
from app.graph.repository import GraphRepository, Scope
from app.graph.schema import SchemaViolation
from app.rag import indexer
from app.rag.embeddings import EmbeddingDimensionMismatch, HashingEmbedder, OllamaEmbedder, check_vectors
from app.rag.retrieval import retrieve
from app.seeds import decoy_acme, novacommerce
from app.seeds.loader import apply_seed
from app.services import memories

from .conftest import ALLOWED, NOW, rctx

pytestmark = pytest.mark.integration
EMB = HashingEmbedder()


def run(graph, embedder=EMB, **kw):
    return retrieve(rctx(graph, **kw), "nova.inc.101", embedder=embedder, allowed_classifications=ALLOWED)


# ------------------------------------------------------------------ gate: typed context with ids + rationale
def test_investigator_context_for_golden_incident(rag_graph):
    b = run(rag_graph)
    assert {k: v.status for k, v in b.steps.items()} == {"graph": "completed", "keyword": "completed",
                                                         "vector": "completed"}
    assert b.extracted.service_ids == ["nova.svc.checkout"] and "5xx" in b.extracted.error_terms
    gc = b.graph_context
    assert [p.deployment.id for p in gc.explanation_paths] == ["nova.dep.payment.v2_4"]
    assert [d.id for d in gc.decisions["nova.svc.payment"]] == ["nova.dec.payment.rollback_v2"]
    assert [t.id for t in gc.ownership["nova.svc.payment"]] == ["nova.team.payments"]
    assert [r.id for r in gc.runbooks["nova.svc.payment"]] == ["nova.rb.payment.rollback"]

    mems = {x.id: x for x in b.memory_context.items}
    assert {"nova.mem.092.rollback_success", "nova.mem.092.restart_failed"} <= set(mems)
    assert mems["nova.mem.092.rollback_success"].precedent == "supports"
    assert mems["nova.mem.092.restart_failed"].precedent == "warns_against"
    # Memories from neighbouring services may also be retrieved, but the precedent for this
    # incident's own prior outage must outrank them; the demo depends on INC-092 leading.
    top = [x.id for x in sorted(b.memory_context.items, key=lambda x: -x.score)[:2]]
    assert set(top) == {"nova.mem.092.rollback_success", "nova.mem.092.restart_failed"}
    assert all(x.rationale and x.components and x.grounded_in for x in mems.values())
    assert b.memory_context.excluded == {"draft": 1}

    chunks = {c.document_id: c for c in b.knowledge_context.items}
    assert {"nova.doc.adr_031", "nova.doc.pm_092"} <= set(chunks)
    assert chunks["nova.doc.adr_031"].graph_links == [
        "Decision nova.dec.payment.rollback_v2 -[DOCUMENTED_IN]-> Document nova.doc.adr_031",
        "Document nova.doc.adr_031 -[RELATES_TO]-> Service nova.svc.payment"]
    assert all(c.claim_type == "context" for c in b.knowledge_context.items)
    assert "nova.doc.sec_handbook" not in json.dumps(b.model_dump(mode="json"))


def test_every_id_is_traceable_to_the_graph(rag_graph):
    b = run(rag_graph)
    repo = GraphRepository(rag_graph, Scope("nova", "prod"))
    for x in b.memory_context.items:
        assert repo.get_node("AgentMemory", x.id)
        assert repo.get_node("Incident", x.about_incident_id)
        assert all(repo.get_node("Evidence", e.id)["source_ref"] == e.source_ref for e in x.grounded_in)
    for c in b.knowledge_context.items:
        doc = repo.get_node("Document", c.document_id)
        assert repo.get_node("DocumentChunk", c.id)["document_id"] == doc["id"]
        assert c.source_ref.startswith(doc["uri"] + "#chunk-")
        parents = repo.neighbors("DocumentChunk", c.id, "HAS_CHUNK", "Document", outgoing=False)
        assert [p["id"] for p in parents] == [doc["id"]]


def test_restricted_document_is_never_indexed(rag_graph):
    repo = GraphRepository(rag_graph, Scope("nova", "prod"))
    assert repo.neighbors("Document", "nova.doc.sec_handbook", "HAS_CHUNK", "DocumentChunk", outgoing=True) == []


def test_reclassified_document_is_excluded_at_read_time(rag_mutable):
    repo = GraphRepository(rag_mutable, Scope("nova", "prod"))
    repo.update_node("Document", "nova.doc.adr_031", {"classification": "restricted"})
    b = run(rag_mutable)
    assert "nova.doc.adr_031" not in {c.document_id for c in b.knowledge_context.items}
    assert b.knowledge_context.excluded.get("unauthorised", 0) >= 1
    rep = indexer.index_all(repo, EMB, allowed_classifications=ALLOWED, now_ms=NOW)
    assert "nova.doc.adr_031" in rep.documents_skipped_unauthorised and rep.chunks_deleted >= 1


# ------------------------------------------------------------------ embeddings: missing / wrong / unavailable
def test_missing_embeddings_fall_back_to_keyword(db):
    from .conftest import TEST_GRAPH, _fresh
    g = _fresh(db, f"{TEST_GRAPH}_noemb")
    try:
        repo = GraphRepository(g, Scope("nova", "prod"))
        rep = indexer.index_all(repo, None, allowed_classifications=ALLOWED, now_ms=NOW)
        assert rep.embedded == 0 and rep.embeddings_missing == rep.chunks_written > 0
        b = run(g)
        assert b.steps["vector"].status == "completed" and b.steps["vector"].candidates == 0
        assert "no vectors" in b.steps["vector"].detail
        assert b.steps["keyword"].status == "completed"
        assert {c.document_id for c in b.knowledge_context.items} >= {"nova.doc.pm_092", "nova.doc.adr_031"}
    finally:
        g.delete()


def test_embedding_model_version_mismatch_counts_as_missing(rag_graph):
    b = run(rag_graph, embedder=HashingEmbedder(version="v2"))
    assert b.steps["vector"].candidates == 0
    assert all("vector" not in c.matched_by for c in b.knowledge_context.items)


def test_provider_unavailable_degrades_gracefully(rag_graph):
    dead = OllamaEmbedder("http://127.0.0.1:1", "nomic-embed-text", 768, timeout_s=0.5)
    b = run(rag_graph, embedder=dead)
    assert b.steps["vector"].status == "failed" and "graph + keyword" in b.steps["vector"].detail
    assert b.graph_context.explanation_paths and b.memory_context.items


def test_embedder_dimension_differs_from_vector_index(rag_graph):
    """A 384-d model against the 768-d index (FalkorDB would not complain) fails the vector step only."""
    b = run(rag_graph, embedder=HashingEmbedder(dim=384))
    assert b.steps["vector"].status == "failed" and "dimension 768" in b.steps["vector"].detail
    assert b.steps["keyword"].status == "completed" and b.memory_context.items


def test_embedding_disabled_is_skipped(rag_graph):
    b = run(rag_graph, embedder=None)
    assert b.steps["vector"].status == "skipped"
    assert b.memory_context.items and b.knowledge_context.items


def test_wrong_dimensions_rejected_everywhere(rag_mutable):
    with pytest.raises(EmbeddingDimensionMismatch):
        check_vectors([[0.1] * 384], 768, 1)
    repo = GraphRepository(rag_mutable, Scope("nova", "prod"))
    with pytest.raises(SchemaViolation, match="384"):
        repo.set_embedding("DocumentChunk", "nova.chunk.pm_092.0", [0.1] * 384, model="m", version="v",
                           dim=768, content_hash="h")
    with pytest.raises(SchemaViolation, match="non-finite"):
        repo.set_embedding("DocumentChunk", "nova.chunk.pm_092.0", [float("nan")] * 768, model="m", version="v",
                           dim=768, content_hash="h")
    # A raw write that bypasses the repository is accepted by FalkorDB; retrieval and integrity must cope.
    rag_mutable.query("MATCH (c:DocumentChunk {id:'nova.chunk.adr_017.0'}) "
                      "SET c.embedding = vecf32($v), c.embedding_dim = 384", {"v": [0.1] * 384})
    b = run(rag_mutable)
    assert b.steps["vector"].status == "completed"
    assert "vector" not in next((c.matched_by for c in b.knowledge_context.items
                                 if c.id == "nova.chunk.adr_017.0"), [])
    assert integrity.run(rag_mutable, embedding_dim=768).bad_embeddings == [("DocumentChunk", "nova.chunk.adr_017.0")]


def test_absent_indexes_fall_back_to_graph(db):
    """A graph without migration 0002 (no full-text / vector indexes) still yields graph context."""
    from .conftest import TEST_GRAPH
    name = f"{TEST_GRAPH}_noidx"
    g = db.select_graph(name)
    try:
        apply_seed(g, novacommerce)
        apply_seed(g, decoy_acme)
        b = run(g)
        assert b.steps["keyword"].status == "failed" and b.steps["vector"].status == "failed"
        assert "migration 0002" in b.steps["keyword"].detail and "index missing" in b.steps["vector"].detail
        assert b.graph_context.explanation_paths and b.memory_context.items
    finally:
        g.delete()                       # no constraints on this graph, so deleting it is safe anywhere


def test_indexing_is_idempotent(rag_mutable):
    repo = GraphRepository(rag_mutable, Scope("nova", "prod"))
    rep = indexer.index_all(repo, EMB, allowed_classifications=ALLOWED, now_ms=NOW)
    assert (rep.embedded, rep.memories_embedded, rep.chunks_deleted) == (0, 0, 0)


# ------------------------------------------------------------------ similar text is not a cause
def test_similar_text_never_becomes_confirmed_cause(rag_mutable):
    repo = GraphRepository(rag_mutable, Scope("nova", "prod"))
    repo.merge_node("Service", "nova.svc.search", {"name": "search", "tier": "tier3"})
    repo.merge_node("Team", "nova.team.discovery", {"name": "Discovery"})
    repo.merge_edge("Team", "nova.team.discovery", "OWNS", "Service", "nova.svc.search")
    repo.merge_node("Incident", "nova.inc.077", {"key": "INC-077", "title": "search 5xx", "severity": "sev3",
                                                 "status": "resolved", "started_at_ms": NOW - 30 * 86_400_000})
    repo.merge_edge("Incident", "nova.inc.077", "AFFECTS", "Service", "nova.svc.search")
    repo.merge_node("Evidence", "nova.ev.077.recovery", {"kind": "metric", "source_ref": "synthetic://m/077",
                                                         "observed_at_ms": NOW - 29 * 86_400_000})
    repo.merge_edge("Incident", "nova.inc.077", "HAS_EVIDENCE", "Evidence", "nova.ev.077.recovery")
    lookalike = memories.create_draft(
        repo, about_incident_id="nova.inc.077", memory_type="episodic", grounded_in=["nova.ev.077.recovery"],
        model_version="human", now_ms=NOW,
        summary="Rolling back a payment deployment resolved checkout 5xx caused by payment DB connection pool "
                "exhaustion timeouts latency")
    memories.validate_by_human(repo, lookalike, responder_id="nova.rsp.payments_lead", outcome="successful",
                               now_ms=NOW)
    indexer.index_all(repo, EMB, allowed_classifications=ALLOWED, now_ms=NOW)

    b = run(rag_mutable)
    items = {x.id: x for x in b.memory_context.items}
    assert lookalike in items, "text match should surface it as context"
    x = items[lookalike]
    assert (x.applicability, x.precedent) == ("text_similarity_only", "none")
    assert "graph" not in x.matched_by and "cannot support or warn" in x.rationale[0]
    assert x.score < items["nova.mem.092.rollback_success"].score
    dumped = json.dumps(b.model_dump(mode="json"))
    assert '"confirmed"' not in dumped and '"hypothesis"' not in dumped


# ------------------------------------------------------------------ graph mutation changes the context
def test_retrieval_changes_after_edge_mutation(rag_mutable):
    before = run(rag_mutable)
    assert before.graph_context.explanation_paths
    linked_before = {c.document_id for c in before.knowledge_context.items if c.graph_links}
    assert {"nova.doc.adr_031", "nova.doc.pm_092"} <= linked_before
    GraphRepository(rag_mutable, Scope("nova", "prod")).delete_edge(
        "Service", "nova.svc.checkout", "DEPENDS_ON", "Service", "nova.svc.payment")
    after = run(rag_mutable)
    assert after.graph_context.explanation_paths == []
    assert "nova.svc.payment" not in after.graph_context.decisions
    assert not any(c.graph_links for c in after.knowledge_context.items)


def test_retrieval_is_tenant_scoped(rag_graph):
    from app.api.errors import NotFound
    with pytest.raises(NotFound):
        retrieve(rctx(rag_graph, tenant="acme"), "nova.inc.101", embedder=EMB, allowed_classifications=ALLOWED)


def test_migration_0002_objects(rag_graph):
    vec = migrate.existing_vector_options(rag_graph)
    assert vec[("DocumentChunk", "embedding")]["dimension"] == 768
    assert vec[("AgentMemory", "embedding")]["similarityFunction"] == "cosine"
    assert migrate.existing_constraints(rag_graph)[("UNIQUE", "DocumentChunk", ("id",))] == "OPERATIONAL"


# ------------------------------------------------------------------ live Ollama (skipped when unavailable)
def _ollama_up() -> bool:
    try:
        return httpx.get("http://127.0.0.1:11434/api/tags", timeout=1).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(not _ollama_up(), reason="local Ollama not running")
def test_live_ollama_embeddings(rag_mutable):
    emb = OllamaEmbedder("http://127.0.0.1:11434", "nomic-embed-text", 768, timeout_s=30)
    v = emb.embed(["payment rollback approval"], "query")[0]
    assert len(v) == 768 and abs(sum(x * x for x in v) - 1.0) < 1e-3 and emb.version
    repo = GraphRepository(rag_mutable, Scope("nova", "prod"))
    rep = indexer.index_all(repo, emb, allowed_classifications=ALLOWED, now_ms=NOW)
    assert rep.embedding_error is None and rep.embedded > 0
    b = run(rag_mutable, embedder=emb)
    assert b.steps["vector"].status == "completed" and b.steps["vector"].candidates > 0
    assert b.embedding_model == "nomic-embed-text"
