"""Migration idempotency, unique constraints, and repeated-seed stability."""

import pytest
from app.graph import integrity, migrate, schema
from app.graph.migrations import v0001_schema_v1
from app.seeds import decoy_acme, novacommerce
from app.seeds.loader import apply_seed
from redis.exceptions import ResponseError

pytestmark = pytest.mark.integration


def _edge_count(g) -> int:
    return g.ro_query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]


def test_migration_rerun_is_noop(db, seeded_graph):
    r = migrate.migrate(db, seeded_graph.name)
    assert r.applied == [] and r.skipped == [1, 2, 3] and r.created == []


def test_all_unique_constraints_operational(seeded_graph):
    cons = migrate.existing_constraints(seeded_graph)
    for label in schema.LABELS | {schema.MIGRATION_LABEL}:
        assert cons.get(("UNIQUE", label, ("id",))) == "OPERATIONAL", label


def test_hot_lookup_indexes_exist(seeded_graph):
    have = migrate.existing_indexes(seeded_graph)
    for label, prop in v0001_schema_v1.RANGE_INDEXES:
        assert (label, prop, "RANGE") in have
    for label, prop in v0001_schema_v1.FULLTEXT_INDEXES:
        assert (label, prop, "FULLTEXT") in have


def test_checksum_mismatch_aborts(db, seeded_graph, monkeypatch):
    monkeypatch.setattr(v0001_schema_v1, "RANGE_INDEXES", [*v0001_schema_v1.RANGE_INDEXES, ("Team", "name")])
    with pytest.raises(migrate.MigrationError, match="different spec"):
        migrate.migrate(db, seeded_graph.name)


def test_concurrent_migration_blocked(db, seeded_graph):
    key = f"graphathon:migration_lock:{seeded_graph.name}"
    db.connection.set(key, "someone-else", ex=30)
    try:
        with pytest.raises(migrate.MigrationError, match="another migration"):
            migrate.migrate(db, seeded_graph.name)
    finally:
        db.connection.delete(key)


def test_unique_constraint_blocks_raw_duplicate(seeded_graph):
    with pytest.raises(ResponseError, match="unique constraint"):
        seeded_graph.query("CREATE (:Service {id: 'nova.svc.checkout', tenant_id: 'nova', env: 'prod'})")


def test_second_seed_creates_no_duplicates(seeded_graph):
    before = integrity.run(seeded_graph)
    edges_before = _edge_count(seeded_graph)
    apply_seed(seeded_graph, novacommerce)
    apply_seed(seeded_graph, decoy_acme)
    after = integrity.run(seeded_graph)
    assert after.label_counts == before.label_counts
    assert _edge_count(seeded_graph) == edges_before
    assert after.ok, after.problems


def test_seed_shape(seeded_graph):
    counts = integrity.run(seeded_graph).label_counts
    nova = seeded_graph.ro_query("MATCH (n {tenant_id:'nova'}) RETURN count(n)").result_set[0][0]
    assert nova == len(novacommerce.NODES)
    assert counts["Service"] == 8 + 2          # nova + decoy
    assert counts["Incident"] == 6 + 1
    assert counts[schema.MIGRATION_LABEL] == len(migrate.MIGRATIONS) == 3


def test_seed_is_value_stable(seeded_graph):
    """Re-seeding must not churn timestamps (fixed SEED_AT_MS)."""
    q = "MATCH (n:Incident {id:'nova.inc.101'}) RETURN n.created_at_ms, n.updated_at_ms"
    before = seeded_graph.ro_query(q).result_set
    apply_seed(seeded_graph, novacommerce)
    assert seeded_graph.ro_query(q).result_set == before == [[novacommerce.SEED_AT_MS] * 2]


def test_integrity_report_is_clean(seeded_graph):
    rep = integrity.run(seeded_graph)
    assert rep.ok, rep.problems
    assert {t[:3] for t in rep.edge_triples} <= schema.ALLOWED_EDGES
