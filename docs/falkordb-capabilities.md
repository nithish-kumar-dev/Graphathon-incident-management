# FalkorDB capabilities (generated)

- Generated: 2026-10-18T09:15:39+00:00 by `scripts/probe_falkordb.py`
- Image: `falkordb/falkordb:v4.22.0` (docker-compose.yml)
- Server graph module version: `42200`
- Python client: falkordb 1.8.0
- Endpoint: `redis://127.0.0.1:56379` (throwaway graph `__probe`, deleted after the run)

**Do not hand-edit.** Re-run the probe after any image or client upgrade.

| Check | Statement | Result | Observed |
|---|---|---|---|
| CREATE with params | `CREATE (:P {id:$id, title:$t})` | ok | [] |
| Array property | `CREATE (:P {id:'p2', tags:['a','b']}) RETURN n.tags` | ok | [[['a', 'b']]] |
| MERGE idempotent (run twice, count) | `MERGE (n:P {id:'p3'}) ON CREATE SET n.c=1 ON MATCH SET n.c=n.c+1` | ok | [[1, 2]] |
| Range index (single prop) | `CREATE INDEX FOR (n:P) ON (n.id)` | ok | 'list' |
| Range index re-create (idempotency?) | `CREATE INDEX FOR (n:P) ON (n.id)  -- second time` | **FAILED** | ResponseError: Attribute 'id' is already indexed |
| Range index (multi prop) | `CREATE INDEX FOR (n:P) ON (n.tenant_id, n.status)` | ok | [] |
| List indexes | `CALL db.indexes()` | ok | [['P', ['id', 'tenant_id', 'status'], OrderedDict({'id': ['RANGE'], 'tenant_id': ['RANGE'], 'status': ['RANGE']})]] |
| Index used by planner | `EXPLAIN MATCH (n:P {id:'p1'}) RETURN n` | ok | ['Results', '    Project', '        Node By Index Scan \| (n:P)'] |
| Unique constraint create | `GRAPH.CONSTRAINT CREATE __probe UNIQUE NODE P PROPERTIES 1 id` | ok | 'PENDING' |
| List constraints | `CALL db.constraints()` | ok | [{'type': 'UNIQUE', 'label': 'P', 'properties': ['id'], 'entitytype': 'NODE', 'status': 'OPERATIONAL'}] |
| Unique constraint rejects duplicate | `CREATE (:P {id:'p1'})  -- expect error` | ok | 'errored as expected: ResponseError: unique constraint violation on node of type P' |
| Unique constraint re-create (idempotency?) | `GRAPH.CONSTRAINT CREATE ... (second time)` | **FAILED** | ResponseError: Constraint already exists |
| Full-text index create | `CALL db.idx.fulltext.createNodeIndex('P', 'title')` | ok | [] |
| Full-text query | `CALL db.idx.fulltext.queryNodes('P', 'rollback') YIELD node, score` | ok | [['p1', 2.0]] |
| Vector index create | `CREATE VECTOR INDEX FOR (n:V) ON (n.emb) OPTIONS {dimension:3, similarityFunction:'cosine'}` | ok | [] |
| Vector store | `CREATE (:V {id:'v1', emb: vecf32([0.1,0.2,0.3])})` | ok | [] |
| Vector query | `CALL db.idx.vector.queryNodes('V','emb',2,vecf32([0.1,0.2,0.3])) YIELD node, score` | ok | [['v1', 0.0], ['v2', 0.675345301628113]] |
| Vector wrong dimension | `CREATE (:V {id:'v3', emb: vecf32([0.1,0.2])})  -- dim 2 into dim-3 index` | ok | [[1]] |
| timestamp() | `RETURN timestamp()` | ok | [[1792314939489]] |
| Temporal datetime() | `RETURN datetime()` | **FAILED** | ResponseError: Unknown function 'datetime' |
| Temporal localdatetime() | `RETURN localdatetime()` | ok | [[datetime.datetime(2026, 10, 18, 9, 15, 39, tzinfo=datetime.timezone.utc)]] |
| Temporal date() | `RETURN date()` | ok | [[datetime.date(2026, 10, 18)]] |
| Temporal localtime() | `RETURN localtime()` | ok | [[datetime.time(9, 15, 39)]] |
| Temporal duration('P1D') | `RETURN duration('P1D')` | ok | [[relativedelta(days=+1)]] |
| Integer epoch-ms range filter | `MATCH (n:T) WHERE n.at_ms >= $from RETURN count(n)` | ok | [[1]] |
| Variable-length path *1..2 | `MATCH (a:S {id:'a'})-[:DEPENDS_ON*1..2]->(x) RETURN x.id` | ok | [['b'], ['c']] |
| Path, relationships(), nodes() | `MATCH p=(a:S {id:'a'})-[:DEPENDS_ON*1..3]->(x) RETURN [n IN nodes(p)\|n.id], [r IN relationships(p)\|type(r)]` | ok | [[['a', 'b', 'c', 'd'], ['DEPENDS_ON', 'DEPENDS_ON', 'DEPENDS_ON']]] |
| shortestPath in MATCH | `MATCH p=shortestPath((a)-[:DEPENDS_ON*]->(d)) RETURN length(p)` | **FAILED** | ResponseError: FalkorDB currently only supports shortestPaths in WITH or RETURN clauses |
| shortestPath in WITH | `MATCH (a),(d) WITH shortestPath((a)-[:DEPENDS_ON*]->(d)) AS p RETURN length(p)` | ok | [[3]] |
| Parameterised variable-length bound | `MATCH (a)-[:DEPENDS_ON*1..$d]->(x)  -- expect unsupported` | **FAILED** | ResponseError: Encountered unhandled type in inlined properties. |
| RO_QUERY rejects writes | `GRAPH.RO_QUERY ... CREATE  -- expect error` | ok | 'errored as expected: ResponseError: graph.RO_QUERY is to be executed only on read-only queries' |
| Per-query timeout (ms) | `g.ro_query(heavy, timeout=1)  -- expect timeout error` | ok | 'errored as expected: ResponseError: Query timed out' |
| Server TIMEOUT config | `GRAPH.CONFIG GET TIMEOUT_MAX / TIMEOUT_DEFAULT` | ok | [['TIMEOUT', 1000], ['TIMEOUT_DEFAULT', 0], ['TIMEOUT_MAX', 0]] |
| db.labels() | `CALL db.labels()` | ok | [['P'], ['V'], ['T'], ['S']] |
| db.relationshipTypes() | `CALL db.relationshipTypes()` | ok | [['DEPENDS_ON']] |
