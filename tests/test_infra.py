"""Persistence across restart, backup, checkpointer ownership, and readiness endpoints."""

import subprocess

import pytest
from app.db import postgres
from app.graph import client

from .conftest import ROOT, TEST_GRAPH

pytestmark = pytest.mark.integration


def _compose(*args: str) -> str:
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def test_graph_survives_container_restart(dev_settings):
    """Restart the persistent dev server (AOF). The marker graph has no constraints, so deleting
    it is safe there (only dropped unique constraints poison the AOF replay)."""
    dev = client.connect(dev_settings.falkordb_url)
    name = f"{TEST_GRAPH}_persist"
    dev.select_graph(name).query("MERGE (:Probe {id: 'persist-marker', v: 42})")
    app_graph = dev.select_graph(dev_settings.graph_name)
    count_q = "MATCH (n) RETURN count(n)"
    app_nodes = app_graph.ro_query(count_q).result_set if dev_settings.graph_name in dev.list_graphs() else None
    try:
        _compose("restart", "falkordb")
        ready = client.wait_until_ready(dev_settings.falkordb_url, timeout_s=60)
        rows = ready.select_graph(name).ro_query("MATCH (p:Probe {id:'persist-marker'}) RETURN p.v").result_set
        assert rows == [[42]]
        if app_nodes is not None:
            assert ready.select_graph(dev_settings.graph_name).ro_query(count_q).result_set == app_nodes
    finally:
        client.wait_until_ready(dev_settings.falkordb_url, timeout_s=60).select_graph(name).delete()


def test_backup_script_writes_snapshot():
    proc = subprocess.run([str(ROOT / "scripts" / "backup_falkordb.sh")], check=False, cwd=ROOT,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.strip()
    path = ROOT / out.split(" ")[0]
    try:
        assert path.exists() and path.stat().st_size > 0
        assert path.read_bytes()[:5] == b"REDIS"
    finally:
        path.unlink(missing_ok=True)


def test_checkpointer_setup_is_library_owned_and_idempotent(settings):
    dsn = settings.postgres_dsn.get_secret_value()
    if not postgres.ping(dsn):
        pytest.skip("Postgres not reachable; run `docker compose up -d`")
    first = postgres.init_checkpointer(dsn)
    second = postgres.init_checkpointer(dsn)
    assert first == second
    assert first["applied_versions"] == first["expected_versions"] > 0
    assert sorted(first["tables"]) == sorted(f"public.{t}" for t in postgres.CHECKPOINT_TABLES)


def test_postgres_outage_is_clean():
    assert postgres.ping("postgresql://x:y@127.0.0.1:1/graphathon", timeout_s=1) is False


def test_readyz_ok_and_503_when_graph_down(make_client, seeded_graph):
    api = make_client(seeded_graph.name)
    assert api.get("/healthz").json() == {"status": "ok"}
    r = api.get("/readyz")
    assert r.status_code == 200 and r.json()["checks"] == {"falkordb": True, "postgres": True}

    down = make_client(seeded_graph.name, falkordb_url="redis://127.0.0.1:1")
    r = down.get("/readyz")
    assert r.status_code == 503
    assert r.json() == {"status": "unavailable", "checks": {"falkordb": False, "postgres": True}}
    assert "127.0.0.1" not in r.text
