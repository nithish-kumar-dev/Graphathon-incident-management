"""Shared fixtures. Integration tests run against the docker compose services and use their
own graphs (graphathon_test_<run>*), so they never touch the dev graph `graphathon`.

Every test graph gets a name that is never reused. Deleting and re-creating a graph under the
same name crashes FalkorDB 4.22.x when it replays its AOF on the next restart
(docs/schema/falkordb.md, "Known server issue").
"""

from __future__ import annotations

import itertools
import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.config import Settings
from app.graph import client, migrate
from app.graph.repository import GraphRepository, Scope
from app.seeds import decoy_acme, novacommerce
from app.seeds.loader import apply_seed

# The ephemeral `falkordb-test` compose service; never the persistent dev server.
TEST_FALKORDB_URL = os.environ.get("TEST_FALKORDB_URL", "redis://127.0.0.1:56390")
TEST_GRAPH = f"graphathon_test_{uuid.uuid4().hex[:8]}"
_mut_seq = itertools.count(1)
NOW = novacommerce.SEED_AT_MS  # deterministic "now" for time-dependent queries


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(_env_file=ROOT / ".env", falkordb_url=TEST_FALKORDB_URL, graph_name=TEST_GRAPH,
                    tenant_allowlist="nova,acme", orchestrator_enabled=False, startup_data="none")


@pytest.fixture(scope="session")
def dev_settings() -> Settings:
    """The persistent dev server from .env. Only for read-only checks and constraint-free graphs."""
    return Settings(_env_file=ROOT / ".env")


@pytest.fixture(scope="session")
def db(settings):
    try:
        conn = client.connect(settings.falkordb_url)
    except client.GraphUnavailable:
        pytest.skip("test FalkorDB not reachable; run `docker compose up -d falkordb-test`")
    persistence = conn.connection.config_get("appendonly")["appendonly"], conn.connection.config_get("save")["save"]
    if persistence != ("no", ""):
        pytest.exit(f"refusing to run: {settings.falkordb_url} has persistence {persistence}; tests delete "
                    "constrained graphs, which poisons an AOF. Point TEST_FALKORDB_URL at falkordb-test.", 2)
    return conn


def _fresh(db, name: str):
    assert name not in db.list_graphs(), f"test graph name reused: {name}"
    migrate.migrate(db, name)
    g = db.select_graph(name)
    apply_seed(g, novacommerce)
    apply_seed(g, decoy_acme)
    return g


@pytest.fixture(scope="session")
def seeded_graph(db):
    """Shared and read-mostly. Tests that mutate it must use `mutable_graph` instead."""
    g = _fresh(db, TEST_GRAPH)
    yield g
    g.delete()


@pytest.fixture
def mutable_graph(db):
    g = _fresh(db, f"{TEST_GRAPH}_mut{next(_mut_seq)}")
    yield g
    g.delete()


@pytest.fixture
def nova(seeded_graph) -> GraphRepository:
    return GraphRepository(seeded_graph, Scope("nova", "prod"))


@pytest.fixture
def acme(seeded_graph) -> GraphRepository:
    return GraphRepository(seeded_graph, Scope("acme", "prod"))


@pytest.fixture
def make_client(settings):
    """TestClient bound to a given graph, with a fixed clock (NOW) unless overridden."""
    from app.api import deps
    from app.config import get_settings
    from app.main import app
    from fastapi.testclient import TestClient

    def _make(graph_name: str, *, now: int = NOW, orchestrator=None, **overrides) -> TestClient:
        """`orchestrator`: the in-process worker the review API resumes paused runs through (None: no worker)."""
        s = settings.model_copy(update={"graph_name": graph_name, **overrides})
        app.dependency_overrides[get_settings] = lambda: s
        app.dependency_overrides[deps.get_now_ms] = lambda: now
        app.state.orchestrator = orchestrator
        return TestClient(app, raise_server_exceptions=False)

    yield _make
    app.dependency_overrides.clear()
    app.state.orchestrator = None


VIEWER = {"X-Demo-User": "demo-viewer"}
RESPONDER = {"X-Demo-User": "demo-responder"}
ACME = {"X-Demo-User": "acme-viewer"}


# ----------------------------------------------------------------- Phase 3 (hybrid retrieval)
ALLOWED = frozenset({"public", "internal"})


def _indexed(db, name: str):
    from app.rag.embeddings import HashingEmbedder
    from app.rag.indexer import index_all

    g = _fresh(db, name)
    index_all(GraphRepository(g, Scope("nova", "prod")), HashingEmbedder(), allowed_classifications=ALLOWED,
              now_ms=NOW)
    return g


@pytest.fixture(scope="session")
def rag_graph(db):
    """Seeded + indexed with the offline HashingEmbedder. Read-only for tests."""
    g = _indexed(db, f"{TEST_GRAPH}_rag")
    yield g
    g.delete()


@pytest.fixture
def rag_mutable(db):
    g = _indexed(db, f"{TEST_GRAPH}_ragmut{next(_mut_seq)}")
    yield g
    g.delete()


def rctx(graph, tenant: str = "nova", now: int = NOW):
    from app.tools.graph_tools import ToolContext
    return ToolContext.read_only(graph, Scope(tenant, "prod"), now_ms=now)
