"""P2 capability probe: verify FalkorDB features against the running, pinned image.

Uses a throwaway graph `__probe`, which is deleted at the end. It never touches the app graph.
Writes docs/falkordb-capabilities.md from the observed results.

    .venv/bin/python scripts/probe_falkordb.py
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import time
from pathlib import Path

from falkordb import FalkorDB

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "falkordb-capabilities.md"
PROBE_GRAPH = "__probe"


def main() -> int:
    url = os.environ.get("FALKORDB_URL", "redis://127.0.0.1:56379")
    db = FalkorDB.from_url(url)
    conn = db.connection
    if PROBE_GRAPH in db.list_graphs():
        db.select_graph(PROBE_GRAPH).delete()
    g = db.select_graph(PROBE_GRAPH)

    results: list[tuple[str, str, bool, str]] = []

    def check(name: str, statement: str, fn) -> object | None:
        try:
            value = fn()
            results.append((name, statement, True, _fmt(value)))
            return value
        except Exception as exc:  # noqa: BLE001 - recording any failure is the point
            results.append((name, statement, False, f"{type(exc).__name__}: {exc}"))
            return None

    def q(cypher: str, params: dict | None = None, **kw):
        return g.query(cypher, params, **kw).result_set

    # --- basic writes, params, arrays, MERGE idempotency
    check("CREATE with params", "CREATE (:P {id:$id, title:$t})",
          lambda: q("CREATE (:P {id:$id, title:$t, n:1})", {"id": "p1", "t": "payment rollback runbook"}))
    check("Array property", "CREATE (:P {id:'p2', tags:['a','b']}) RETURN n.tags",
          lambda: q("CREATE (n:P {id:'p2', tags:['a','b'], title:'checkout latency'}) RETURN n.tags"))
    check("MERGE idempotent (run twice, count)", "MERGE (n:P {id:'p3'}) ON CREATE SET n.c=1 ON MATCH SET n.c=n.c+1",
          lambda: [q("MERGE (n:P {id:'p3'}) ON CREATE SET n.c=1 ON MATCH SET n.c=n.c+1") for _ in range(2)]
          and q("MATCH (n:P {id:'p3'}) RETURN count(n), n.c"))

    # --- indexes
    check("Range index (single prop)", "CREATE INDEX FOR (n:P) ON (n.id)",
          lambda: q("CREATE INDEX FOR (n:P) ON (n.id)").__class__.__name__)
    check("Range index re-create (idempotency?)", "CREATE INDEX FOR (n:P) ON (n.id)  -- second time",
          lambda: q("CREATE INDEX FOR (n:P) ON (n.id)"))
    check("Range index (multi prop)", "CREATE INDEX FOR (n:P) ON (n.tenant_id, n.status)",
          lambda: q("CREATE INDEX FOR (n:P) ON (n.tenant_id, n.status)"))
    check("List indexes", "CALL db.indexes()",
          lambda: [r[:3] for r in q("CALL db.indexes() YIELD label, properties, types RETURN label, properties, types")])
    check("Index used by planner", "EXPLAIN MATCH (n:P {id:'p1'}) RETURN n",
          lambda: [str(x) for x in g.explain("MATCH (n:P {id:'p1'}) RETURN n").plan] if hasattr(
              g.explain("MATCH (n:P) RETURN n"), "plan") else str(g.explain("MATCH (n:P {id:'p1'}) RETURN n")))

    # --- unique constraint
    check("Unique constraint create", "GRAPH.CONSTRAINT CREATE __probe UNIQUE NODE P PROPERTIES 1 id",
          lambda: conn.execute_command("GRAPH.CONSTRAINT", "CREATE", PROBE_GRAPH, "UNIQUE", "NODE", "P",
                                       "PROPERTIES", 1, "id"))
    time.sleep(0.5)
    check("List constraints", "CALL db.constraints()", lambda: g.list_constraints())
    check("Unique constraint rejects duplicate", "CREATE (:P {id:'p1'})  -- expect error",
          lambda: _expect_error(lambda: q("CREATE (:P {id:'p1'})")))
    check("Unique constraint re-create (idempotency?)", "GRAPH.CONSTRAINT CREATE ... (second time)",
          lambda: conn.execute_command("GRAPH.CONSTRAINT", "CREATE", PROBE_GRAPH, "UNIQUE", "NODE", "P",
                                       "PROPERTIES", 1, "id"))

    # --- full-text
    check("Full-text index create", "CALL db.idx.fulltext.createNodeIndex('P', 'title')",
          lambda: q("CALL db.idx.fulltext.createNodeIndex('P', 'title')"))
    check("Full-text query", "CALL db.idx.fulltext.queryNodes('P', 'rollback') YIELD node, score",
          lambda: q("CALL db.idx.fulltext.queryNodes('P', 'rollback') YIELD node, score RETURN node.id, score"))

    # --- vector
    check("Vector index create", "CREATE VECTOR INDEX FOR (n:V) ON (n.emb) OPTIONS {dimension:3, similarityFunction:'cosine'}",
          lambda: q("CREATE VECTOR INDEX FOR (n:V) ON (n.emb) OPTIONS {dimension:3, similarityFunction:'cosine'}"))
    check("Vector store", "CREATE (:V {id:'v1', emb: vecf32([0.1,0.2,0.3])})",
          lambda: q("CREATE (:V {id:'v1', emb: vecf32([0.1,0.2,0.3])}), (:V {id:'v2', emb: vecf32([0.9,0.1,0.0])})"))
    check("Vector query", "CALL db.idx.vector.queryNodes('V','emb',2,vecf32([0.1,0.2,0.3])) YIELD node, score",
          lambda: q("CALL db.idx.vector.queryNodes('V','emb',2,vecf32([0.1,0.2,0.3])) YIELD node, score "
                    "RETURN node.id, score"))
    check("Vector wrong dimension", "CREATE (:V {id:'v3', emb: vecf32([0.1,0.2])})  -- dim 2 into dim-3 index",
          lambda: q("CREATE (:V {id:'v3', emb: vecf32([0.1,0.2])}) RETURN 1") or "accepted (no error)")

    # --- temporal
    check("timestamp()", "RETURN timestamp()", lambda: q("RETURN timestamp()"))
    for fn in ["datetime()", "localdatetime()", "date()", "localtime()", "duration('P1D')"]:
        check(f"Temporal {fn}", f"RETURN {fn}", lambda fn=fn: q(f"RETURN {fn}"))
    check("Integer epoch-ms range filter", "MATCH (n:T) WHERE n.at_ms >= $from RETURN count(n)",
          lambda: (q("CREATE (:T {at_ms: $a}), (:T {at_ms: $b})",
                     {"a": _ms(dt.datetime(2026, 1, 1, tzinfo=dt.UTC)), "b": _ms(dt.datetime(2026, 6, 1, tzinfo=dt.UTC))}),
                   q("MATCH (n:T) WHERE n.at_ms >= $f RETURN count(n)",
                     {"f": _ms(dt.datetime(2026, 3, 1, tzinfo=dt.UTC))}))[1])

    # --- traversal
    q("CREATE (:S {id:'a'})-[:DEPENDS_ON]->(:S {id:'b'})-[:DEPENDS_ON]->(:S {id:'c'})-[:DEPENDS_ON]->(:S {id:'d'})")
    check("Variable-length path *1..2", "MATCH (a:S {id:'a'})-[:DEPENDS_ON*1..2]->(x) RETURN x.id",
          lambda: q("MATCH (a:S {id:'a'})-[:DEPENDS_ON*1..2]->(x) RETURN x.id ORDER BY x.id"))
    check("Path, relationships(), nodes()", "MATCH p=(a:S {id:'a'})-[:DEPENDS_ON*1..3]->(x) RETURN [n IN nodes(p)|n.id], [r IN relationships(p)|type(r)]",
          lambda: q("MATCH p=(a:S {id:'a'})-[:DEPENDS_ON*1..3]->(x:S {id:'d'}) "
                    "RETURN [n IN nodes(p) | n.id], [r IN relationships(p) | type(r)]"))
    check("shortestPath in MATCH", "MATCH p=shortestPath((a)-[:DEPENDS_ON*]->(d)) RETURN length(p)",
          lambda: q("MATCH (a:S {id:'a'}), (d:S {id:'d'}) MATCH p=shortestPath((a)-[:DEPENDS_ON*]->(d)) RETURN length(p)"))
    check("shortestPath in WITH", "MATCH (a),(d) WITH shortestPath((a)-[:DEPENDS_ON*]->(d)) AS p RETURN length(p)",
          lambda: q("MATCH (a:S {id:'a'}), (d:S {id:'d'}) WITH shortestPath((a)-[:DEPENDS_ON*]->(d)) AS p RETURN length(p)"))
    check("Parameterised variable-length bound", "MATCH (a)-[:DEPENDS_ON*1..$d]->(x)  -- expect unsupported",
          lambda: q("MATCH (a:S {id:'a'})-[:DEPENDS_ON*1..$d]->(x) RETURN count(x)", {"d": 2}))

    # --- read-only and timeouts
    check("RO_QUERY rejects writes", "GRAPH.RO_QUERY ... CREATE  -- expect error",
          lambda: _expect_error(lambda: g.ro_query("CREATE (:X)")))
    check("Per-query timeout (ms)", "g.ro_query(heavy, timeout=1)  -- expect timeout error",
          lambda: _expect_error(lambda: g.ro_query("UNWIND range(1, 20000000) AS x RETURN sum(x)", timeout=1)))
    check("Server TIMEOUT config", "GRAPH.CONFIG GET TIMEOUT_MAX / TIMEOUT_DEFAULT",
          lambda: [conn.execute_command("GRAPH.CONFIG", "GET", k) for k in ("TIMEOUT", "TIMEOUT_DEFAULT", "TIMEOUT_MAX")])

    # --- misc procedures used by migrations / inventory
    check("db.labels()", "CALL db.labels()", lambda: q("CALL db.labels()"))
    check("db.relationshipTypes()", "CALL db.relationshipTypes()", lambda: q("CALL db.relationshipTypes()"))

    module_ver = next((m.get("ver") for m in conn.execute_command("MODULE", "LIST") if m.get("name") == "graph"), None)
    g.delete()
    _write_report(results, module_ver, url)
    ok = sum(1 for r in results if r[2])
    print(f"{ok}/{len(results)} checks returned without error -> {OUT.relative_to(ROOT)}")
    return 0


def _expect_error(fn) -> str:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        return f"errored as expected: {type(exc).__name__}: {exc}"
    raise AssertionError("statement succeeded but was expected to fail")


def _ms(t: dt.datetime) -> int:
    return int(t.timestamp() * 1000)


def _fmt(v: object) -> str:
    s = repr(v)
    return s if len(s) <= 220 else s[:217] + "..."


def _write_report(results, module_ver, url) -> None:
    from importlib.metadata import version

    lines = [
        "# FalkorDB capabilities (generated)",
        "",
        f"- Generated: {dt.datetime.now(dt.UTC).isoformat(timespec='seconds')} by `scripts/probe_falkordb.py`",
        "- Image: `falkordb/falkordb:v4.22.0` (docker-compose.yml)",
        f"- Server graph module version: `{module_ver}`",
        f"- Python client: falkordb {version('falkordb')}",
        f"- Endpoint: `{url}` (throwaway graph `{PROBE_GRAPH}`, deleted after the run)",
        "",
        "**Do not hand-edit.** Re-run the probe after any image or client upgrade.",
        "",
        "| Check | Statement | Result | Observed |",
        "|---|---|---|---|",
    ]
    for name, stmt, ok, obs in results:
        lines.append(f"| {name} | `{_md(stmt)}` | {'ok' if ok else '**FAILED**'} | {_md(obs)} |")
    OUT.write_text("\n".join(lines) + "\n")


def _md(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    sys.exit(main())
