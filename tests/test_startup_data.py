"""STARTUP_DATA: graph data prepared when the API starts (app/seeds/startup.py)."""

import itertools
import uuid

import pytest
from app.config import Settings
from app.graph import integrity
from app.seeds.startup import prepare

pytestmark = pytest.mark.integration
_PREFIX = f"graphathon_test_startup_{uuid.uuid4().hex[:8]}"
_seq = itertools.count(1)


def _counts(g) -> tuple[int, int]:
    nodes = g.ro_query("MATCH (n) RETURN count(n)").result_set[0][0]
    edges = g.ro_query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]
    return nodes, edges


@pytest.fixture
def startup_settings(db, settings):
    name = f"{_PREFIX}_{next(_seq)}"
    s = settings.model_copy(update={"graph_name": name, "tenant_allowlist": "nova", "embedding_provider": "none"})
    yield s
    if name in db.list_graphs():
        db.select_graph(name).delete()


def test_none_leaves_the_graph_alone(db, startup_settings):
    prepare(startup_settings)
    assert startup_settings.graph_name not in db.list_graphs()


def test_seed_on_a_fresh_server_is_complete_and_idempotent(db, startup_settings):
    s = startup_settings.model_copy(update={"startup_data": "seed"})
    prepare(s)
    g = db.select_graph(s.graph_name)
    assert integrity.run(g).ok
    first = _counts(g)
    assert first[0] > 0
    assert g.ro_query("MATCH (n {tenant_id: 'acme'}) RETURN count(n)").result_set[0][0] == 0  # not allowlisted
    assert g.ro_query("MATCH (c:DocumentChunk) RETURN count(c)").result_set[0][0] > 0       # indexed
    prepare(s)
    assert _counts(g) == first


def test_reset_drops_data_created_since_and_reseeds(db, startup_settings):
    prepare(startup_settings.model_copy(update={"startup_data": "seed"}))
    g = db.select_graph(startup_settings.graph_name)
    seeded = _counts(g)
    g.query("MATCH (i:Incident {tenant_id: 'nova'}) WITH i LIMIT 1 "
            "CREATE (i)-[:HAS_EVIDENCE]->(:Evidence {id: 'nova.ev.after_start', tenant_id: 'nova', env: 'prod'})")
    assert _counts(g) == (seeded[0] + 1, seeded[1] + 1)
    prepare(startup_settings.model_copy(update={"startup_data": "reset"}))
    assert _counts(g) == seeded
    assert integrity.run(g).ok


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="startup_data"):
        Settings(_env_file=None, postgres_dsn="postgresql://u@h/graphathon", startup_data="wipe")


def test_seed_works_when_the_server_forbids_plain_redis_commands(db, startup_settings, monkeypatch):
    """FalkorDB Cloud users may only run GRAPH.* commands, so the migration lock's SET is refused."""
    from redis.exceptions import NoPermissionError

    def refuse(*_a, **_k):
        raise NoPermissionError("User falkordb has no permissions to run the 'set' command")

    monkeypatch.setattr(type(db.connection), "set", refuse)
    s = startup_settings.model_copy(update={"startup_data": "seed"})
    prepare(s)
    assert integrity.run(db.select_graph(s.graph_name)).ok


def test_seed_skips_a_tenant_that_is_already_seeded(db, startup_settings):
    s = startup_settings.model_copy(update={"startup_data": "seed"})
    prepare(s)
    g = db.select_graph(s.graph_name)
    g.query("MATCH (i:Incident {id: 'nova.inc.101'}) SET i.title = 'edited since start'")
    prepare(s)
    assert g.ro_query("MATCH (i:Incident {id: 'nova.inc.101'}) RETURN i.title").result_set[0][0] == "edited since start"


def test_api_serves_while_startup_data_runs_and_readyz_reports_it(make_client, startup_settings):
    import time

    api = make_client(startup_settings.graph_name, startup_data="reset", tenant_allowlist="nova",
                      embedding_provider="none")
    with api:  # runs the lifespan; the data is prepared on a background thread
        deadline = time.monotonic() + 60
        while not (r := api.get("/readyz")).json()["checks"]["data"]:
            assert time.monotonic() < deadline, r.json()
            time.sleep(0.2)
        assert r.status_code == 200
        r = api.get("/api/incidents", params={"limit": 50}, headers={"X-Demo-User": "demo-viewer"})
        assert r.status_code == 200 and len(r.json()["items"]) > 0
    assert "data" not in api.get("/readyz").json()["checks"]
