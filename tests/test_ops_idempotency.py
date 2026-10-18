"""ops.idempotency_records: the migration runner and the idempotency store (in-memory and Postgres)."""

from __future__ import annotations

import uuid

import pytest
from app.db import idempotency as idem
from app.db import ops

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def pool(settings):
    from app.orchestrator.checkpoint import open_pool
    try:
        p = open_pool(settings.postgres_dsn.get_secret_value(), max_size=4)
    except Exception:  # noqa: BLE001 - any connection failure means "not reachable"
        pytest.skip("project Postgres not reachable; run `docker compose up -d postgres`")
    ops.apply_migrations(p)
    yield p
    with p.connection() as conn:
        conn.execute("DELETE FROM ops.idempotency_records WHERE key LIKE 'test.act.%' OR key LIKE 'nova.act.%'")
    p.close()


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    if request.param == "memory":
        return idem.MemoryIdempotencyStore()
    return idem.PostgresIdempotencyStore(request.getfixturevalue("pool"))


@pytest.fixture
def key():
    return f"test.act.{uuid.uuid4().hex}:hash"


T0 = 1_000_000


def test_first_begin_is_new_and_a_second_is_busy_until_the_lease_expires(store, key):
    assert store.begin(key, "h", now_ms=T0) == idem.Begin("new", attempts=1)
    assert store.begin(key, "h", now_ms=T0 + 1).decision == "busy"
    stale = store.begin(key, "h", now_ms=T0 + idem.LEASE_MS)          # the runner died: take over
    assert stale == idem.Begin("new", attempts=2)


def test_a_completed_record_replays_its_response(store, key):
    store.begin(key, "h", now_ms=T0)
    store.complete(key, status="succeeded", response={"ticket": "SIM-1"}, now_ms=T0 + 1)
    again = store.begin(key, "h", now_ms=T0 + 10 * idem.LEASE_MS)
    assert again.decision == "done" and again.response == {"ticket": "SIM-1"}


def test_the_same_key_with_a_different_request_conflicts(store, key):
    store.begin(key, "h", now_ms=T0)
    assert store.begin(key, "other", now_ms=T0 + 1).decision == "conflict"
    store.complete(key, status="succeeded", response={}, now_ms=T0 + 2)
    assert store.begin(key, "other", now_ms=T0 + 3).decision == "conflict"


def test_a_failed_record_retries_then_exhausts(store, key):
    now = T0
    for attempt in range(1, idem.MAX_ATTEMPTS + 1):
        assert store.begin(key, "h", now_ms=now) == idem.Begin("new", attempts=attempt)
        store.complete(key, status="failed", response={"result": "failed", "note": "boom"}, now_ms=now + 1)
        now += 10
    last = store.begin(key, "h", now_ms=now)
    assert last.decision == "exhausted" and last.response["note"] == "boom"
    assert store.begin(key, "h", now_ms=now + 1).decision == "exhausted"


def test_an_abandoned_record_exhausts_after_the_attempt_cap(store, key):
    now = T0
    for _ in range(idem.MAX_ATTEMPTS):
        assert store.begin(key, "h", now_ms=now).decision == "new"
        now += idem.LEASE_MS                                          # never completed
    assert store.begin(key, "h", now_ms=now).decision == "exhausted"


def test_concurrent_begins_have_exactly_one_winner(pool, key):
    import threading
    store, results = idem.PostgresIdempotencyStore(pool), []
    barrier = threading.Barrier(4)

    def go():
        barrier.wait()
        results.append(store.begin(key, "h", now_ms=T0).decision)

    threads = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["busy", "busy", "busy", "new"]


def test_migrations_are_numbered_recorded_and_idempotent(pool):
    assert ops.migration_files()[0][0] == 1
    assert ops.apply_migrations(pool) == []
    with pool.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM ops.schema_migrations WHERE version = 1").fetchone()["n"] == 1
        cols = {r["column_name"] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'ops' "
            "AND table_name = 'idempotency_records'")}
    assert {"key", "status", "request_hash", "response", "attempts", "expires_at_ms"} <= cols
