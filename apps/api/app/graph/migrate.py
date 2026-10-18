"""Graph migration runner.

- Idempotent. Applied migrations are recorded as (:SchemaMigration {id, version, name, checksum}),
  and a re-run is a no-op.
- A recorded migration whose spec has since changed aborts with a checksum mismatch. Edits
  go into a new migration.
- Introspective. It creates only the indexes and constraints the server does not already report.
- Unique constraints are created only after a duplicate check on that label returns zero.
- A Redis lock stops two runners from migrating the same graph at the same time.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from types import ModuleType

from falkordb import FalkorDB, Graph

from app.graph import schema
from app.graph.migrations import v0001_schema_v1, v0002_hybrid_retrieval
from app.graph.repository import load_query, now_ms

log = logging.getLogger(__name__)

MIGRATIONS: list[ModuleType] = [v0001_schema_v1, v0002_hybrid_retrieval]
CONSTRAINT_WAIT_S = 30.0


class MigrationError(RuntimeError):
    pass


@dataclass
class MigrationResult:
    applied: list[int] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)
    created: list[str] = field(default_factory=list)


def checksum(m: ModuleType) -> str:
    spec = {
        "version": m.VERSION,
        "name": m.NAME,
        "range": sorted(map(list, m.RANGE_INDEXES)),
        "unique": sorted(map(list, m.UNIQUE_CONSTRAINTS)),
        "fulltext": sorted(map(list, m.FULLTEXT_INDEXES)),
    }
    if getattr(m, "VECTOR_INDEXES", None):  # key only when present, so 0001's recorded checksum is unchanged
        spec["vector"] = sorted(map(list, m.VECTOR_INDEXES))
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


def migration_id(version: int) -> str:
    return f"schema_migration.{version:04d}"


# ---------------------------------------------------------------- introspection
def existing_indexes(g: Graph) -> set[tuple[str, str, str]]:
    """{(label, property, 'RANGE'|'FULLTEXT'|'VECTOR')} for node indexes."""
    rows = g.ro_query("CALL db.indexes() YIELD label, types, entitytype RETURN label, types, entitytype").result_set
    out: set[tuple[str, str, str]] = set()
    for label, types, entitytype in rows:
        if entitytype != "NODE":
            continue
        for prop, kinds in types.items():
            for kind in kinds:
                out.add((label, prop, kind))
    return out


def existing_vector_options(g: Graph) -> dict[tuple[str, str], dict]:
    rows = g.ro_query("CALL db.indexes() YIELD label, types, options, entitytype "
                      "RETURN label, types, options, entitytype").result_set
    out: dict[tuple[str, str], dict] = {}
    for label, types, options, entitytype in rows:
        if entitytype != "NODE":
            continue
        for prop, kinds in types.items():
            if "VECTOR" in kinds:
                out[(label, prop)] = dict(options.get(prop) or {})
    return out


def existing_constraints(g: Graph) -> dict[tuple[str, str, tuple[str, ...]], str]:
    """{(type, label, props): status}"""
    return {(c["type"], c["label"], tuple(c["properties"])): c["status"]
            for c in g.list_constraints() if c["entitytype"] == "NODE"}


def recorded(g: Graph) -> dict[int, str]:
    rows = g.ro_query(f"MATCH (m:{schema.MIGRATION_LABEL}) RETURN m.version, m.checksum").result_set
    return {v: c for v, c in rows}


# --------------------------------------------------------------------- apply
def migrate(db: FalkorDB, graph_name: str) -> MigrationResult:
    g = db.select_graph(graph_name)
    result = MigrationResult()
    with _lock(db, graph_name):
        g.query("RETURN 1")  # creates the graph key; read-only queries fail on a missing graph
        done = recorded(g)
        for m in MIGRATIONS:
            cs = checksum(m)
            if m.VERSION in done:
                if done[m.VERSION] != cs:
                    raise MigrationError(f"migration {m.VERSION:04d} was applied with a different spec "
                                         f"(recorded {done[m.VERSION][:12]}, code {cs[:12]}); add a new migration")
                result.skipped.append(m.VERSION)
                continue
            result.created += _apply(g, db, graph_name, m)
            g.query(
                f"MERGE (m:{schema.MIGRATION_LABEL} {{id: $id}}) "
                "SET m.version = $v, m.name = $n, m.checksum = $c, m.applied_at_ms = $t",
                {"id": migration_id(m.VERSION), "v": m.VERSION, "n": m.NAME, "c": cs, "t": now_ms()},
            )
            result.applied.append(m.VERSION)
            log.info("applied migration %04d_%s", m.VERSION, m.NAME)
    return result


def _apply(g: Graph, db: FalkorDB, graph_name: str, m: ModuleType) -> list[str]:
    created: list[str] = []
    have = existing_indexes(g)
    for label, prop in m.RANGE_INDEXES:
        if (label, prop, "RANGE") not in have:
            g.query(f"CREATE INDEX FOR (n:{_ident(label)}) ON (n.{_ident(prop)})")
            created.append(f"range {label}.{prop}")
    for label, prop in m.FULLTEXT_INDEXES:
        if (label, prop, "FULLTEXT") not in have:
            g.query("CALL db.idx.fulltext.createNodeIndex($label, $prop)", {"label": label, "prop": prop})
            created.append(f"fulltext {label}.{prop}")

    vectors = existing_vector_options(g)
    for label, prop, dim, sim in getattr(m, "VECTOR_INDEXES", []):
        opts = vectors.get((label, prop))
        if opts is None:
            g.query(f"CREATE VECTOR INDEX FOR (n:{_ident(label)}) ON (n.{_ident(prop)}) "
                    f"OPTIONS {{dimension: {int(dim)}, similarityFunction: '{_ident(sim)}'}}")
            created.append(f"vector {label}.{prop} dim={dim} {sim}")
        elif opts.get("dimension") != dim or str(opts.get("similarityFunction", "")).lower() != sim:
            raise MigrationError(f"vector index {label}.{prop} exists with {opts}; expected dimension={dim} {sim}. "
                                 "Re-embedding with a different model needs a new migration")

    constraints = existing_constraints(g)
    for label, prop in m.UNIQUE_CONSTRAINTS:
        key = ("UNIQUE", label, (prop,))
        if constraints.get(key) == "OPERATIONAL":
            continue
        if key in constraints and constraints[key] == "FAILED":
            raise MigrationError(f"unique constraint {label}.{prop} is FAILED on the server; dedupe, drop and rerun")
        dups = g.ro_query(load_query("integrity_duplicates").replace("__LABEL__", _ident(label))).result_set
        if dups:
            raise MigrationError(f"cannot add unique {label}.{prop}: duplicate ids {dups[:5]}")
        if key not in constraints:
            db.connection.execute_command("GRAPH.CONSTRAINT", "CREATE", graph_name, "UNIQUE", "NODE",
                                          label, "PROPERTIES", 1, prop)
            created.append(f"unique {label}.{prop}")
        _wait_operational(g, key)
    return created


def _wait_operational(g: Graph, key: tuple) -> None:
    deadline = time.monotonic() + CONSTRAINT_WAIT_S
    while time.monotonic() < deadline:
        status = existing_constraints(g).get(key)
        if status == "OPERATIONAL":
            return
        if status == "FAILED":
            raise MigrationError(f"constraint {key} failed to build")
        time.sleep(0.2)
    raise MigrationError(f"constraint {key} not operational after {CONSTRAINT_WAIT_S}s")


# ---------------------------------------------------------------------- down
def rollback(db: FalkorDB, graph_name: str, version: int) -> list[str]:
    """Drop exactly what `version` declares. Dev only; the CLI requires explicit confirmation."""
    m = next((x for x in MIGRATIONS if x.VERSION == version), None)
    if m is None:
        raise MigrationError(f"unknown migration {version}")
    g = db.select_graph(graph_name)
    dropped: list[str] = []
    with _lock(db, graph_name):
        constraints = existing_constraints(g)
        for label, prop in m.UNIQUE_CONSTRAINTS:
            if ("UNIQUE", label, (prop,)) in constraints:
                db.connection.execute_command("GRAPH.CONSTRAINT", "DROP", graph_name, "UNIQUE", "NODE",
                                              label, "PROPERTIES", 1, prop)
                dropped.append(f"unique {label}.{prop}")
        have = existing_indexes(g)
        for label, prop, _dim, _sim in getattr(m, "VECTOR_INDEXES", []):
            if (label, prop, "VECTOR") in have:
                g.query(f"DROP VECTOR INDEX FOR (n:{_ident(label)}) ON (n.{_ident(prop)})")
                dropped.append(f"vector {label}.{prop}")
        for label in sorted({label for label, _ in m.FULLTEXT_INDEXES}):
            if any(lbl == label and kind == "FULLTEXT" for lbl, _, kind in have):
                g.query("CALL db.idx.fulltext.drop($label)", {"label": label})
                dropped.append(f"fulltext {label}")
        for label, prop in m.RANGE_INDEXES:
            if (label, prop, "RANGE") in have:
                g.query(f"DROP INDEX FOR (n:{_ident(label)}) ON (n.{_ident(prop)})")
                dropped.append(f"range {label}.{prop}")
        g.query(f"MATCH (m:{schema.MIGRATION_LABEL} {{id: $id}}) DELETE m", {"id": migration_id(version)})
        if aof_enabled(db):
            # FalkorDB 4.22.x segfaults when it replays an AOF that holds a dropped unique constraint.
            # Compacting the AOF straight away removes those entries (verified; docs/schema/falkordb.md).
            rewrite_aof(db)
            dropped.append("aof rewritten")
    return dropped


def aof_enabled(db: FalkorDB) -> bool:
    return db.connection.config_get("appendonly").get("appendonly") == "yes"


def rewrite_aof(db: FalkorDB, timeout_s: float = 60.0) -> None:
    conn = db.connection
    conn.bgrewriteaof()
    deadline = time.monotonic() + timeout_s
    time.sleep(0.2)
    while time.monotonic() < deadline:
        info = conn.info("persistence")
        if not info.get("aof_rewrite_in_progress") and not info.get("aof_rewrite_scheduled"):
            if info.get("aof_last_bgrewrite_status") != "ok":
                raise MigrationError("AOF rewrite failed; do not restart FalkorDB before fixing it")
            return
        time.sleep(0.2)
    raise MigrationError("AOF rewrite did not finish; do not restart FalkorDB before it does")


# ------------------------------------------------------------------- helpers
def _ident(name: str) -> str:
    if not name.replace("_", "").isalnum():
        raise MigrationError(f"bad identifier {name!r}")
    return name


class _lock:
    def __init__(self, db: FalkorDB, graph_name: str, ttl_s: int = 120) -> None:
        self.conn = db.connection
        self.key = f"graphathon:migration_lock:{graph_name}"
        self.token = secrets.token_hex(8)
        self.ttl_s = ttl_s

    def __enter__(self) -> None:
        if not self.conn.set(self.key, self.token, nx=True, ex=self.ttl_s):
            raise MigrationError(f"another migration holds {self.key}")

    def __exit__(self, *exc: object) -> None:
        current = self.conn.get(self.key)
        if current in (self.token, self.token.encode()):
            self.conn.delete(self.key)
