# Graphathon: graph-grounded incident investigation

Incident investigation grounded in a FalkorDB knowledge graph, with LangGraph orchestration that keeps durable checkpoints in Postgres.

**All data is synthetic.** NovaCommerce is a fictional company. Nothing here is a production system.

- **Status:** Phase 1 (databases, migrations, seed), Phase 2 (typed API: `docs/api.md`), Phase 3 (graph tools + hybrid retrieval: `docs/retrieval.md`) and Phase 4 (investigator, safety gate, LangGraph orchestration: `docs/investigator.md`, `docs/orchestration.md`) are done. Human review and the restricted executor (Phase 5) are placeholders; nothing is ever executed.
- **Plan:** `docs/refactor-plan.md`; what comes next: `docs/NEXT_STEPS.md`
- **Schema:** `docs/schema/`

## Prerequisites

- Docker with Compose v2
- Python 3.14 (3.13 also works)
- Optional: local [Ollama](https://ollama.com) with `nomic-embed-text` (`ollama pull nomic-embed-text`) for vector retrieval. Without it, set `EMBEDDING_PROVIDER=none`; retrieval then uses graph + keyword only
- Optional: an Ollama chat model (for example `qwen2.5:7b`) for `LLM_PROVIDER=ollama`. The default `LLM_PROVIDER=stub` is deterministic and needs no model
- `redis-cli`, used by the backup script

## Setup

```bash
cp .env.example .env            # then set POSTGRES_PASSWORD (and the same value inside POSTGRES_DSN)
docker compose up -d            # falkordb :56379 (AOF), falkordb-test :56390 (ephemeral), postgres :55432
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
                                # exact versions: requirements.lock

.venv/bin/python scripts/migrate_graph.py       # graph indexes, unique constraints, full-text + vector indexes (idempotent)
.venv/bin/python scripts/init_checkpointer.py   # LangGraph checkpoint tables via the library's own setup()
.venv/bin/python scripts/seed.py                # NovaCommerce synthetic tenant (idempotent)
.venv/bin/python scripts/index_documents.py     # chunk authorised docs, embed chunks + m
emories via Ollama (idempotent)
.venv/bin/python scripts/inventory_graph.py     # read-only counts + integrity report
.venv/bin/python scripts/retrieve_context.py nova.inc.101   # print the investigator's retrieval bundle (--full for JSON)
```

All ports are bound to `127.0.0.1`. The host's own Postgres on `:5432` is never used, and config refuses any database other than `graphathon`.

## Run

```bash
.venv/bin/uvicorn app.main:app --app-dir apps/api --env-file .env --port 8000 --no-access-log
# Swagger at http://127.0.0.1:8000/docs. Authorize with X-Demo-User = demo-viewer | demo-responder | payments-lead
curl -H 'X-Demo-User: demo-viewer' http://127.0.0.1:8000/api/incidents/nova.inc.101   # golden case
curl -H 'X-Demo-User: demo-viewer' http://127.0.0.1:8000/api/incidents/nova.inc.101/retrieval   # hybrid context
```

With `ORCHESTRATOR_ENABLED=true` the API process also runs the investigation worker: `POST /api/investigations` queues a run, the worker claims it, and `GET /api/investigations/{id}` shows the outcome. Or run the worker on its own with `scripts/run_worker.py` and `ORCHESTRATOR_ENABLED=false` for the API. Run exactly one worker per graph. An investigation writes to the graph permanently (evidence, session, proposed actions), so back up first (`scripts/backup_falkordb.sh`) if you use the dev graph.

Web UI (`apps/web`): `cd apps/web && npm install && npm run dev`. Vite proxies `/api` to `GRAPHATHON_API_URL` (default `http://127.0.0.1:8000`). Checks: `npm run typecheck && npm test && npm run build`. The test fixtures in `apps/web/src/test/fixtures/investigation_*.json` come from the real API: regenerate them with `.venv/bin/python scripts/gen_web_fixtures.py` (ephemeral `falkordb-test` only; it refuses a persistent server).

## Tests

```bash
.venv/bin/python -m pytest -q
```

The suite runs against the ephemeral `falkordb-test` service and refuses to start against any server with persistence enabled. Retrieval tests use a deterministic test-only embedder; one live test uses local Ollama and is skipped when it is not running. The infra tests restart the dev `falkordb` container once, to prove data survives a restart.

## Operations

| Task | Command |
|---|---|
| Migration status | `scripts/migrate_graph.py --status` |
| Re-index documents (no embeddings) | `scripts/index_documents.py --no-embed` |
| Backup graph | `scripts/backup_falkordb.sh` → `backups/falkordb-<UTC>.rdb` |
| Remove one tenant's data (dev) | `scripts/reset_graph.py --tenant nova --confirm nova` |
| Roll back a migration (dev) | `scripts/migrate_graph.py --down 1 --confirm graphathon`. Rewrites the AOF afterwards; see the known issue below |
| Re-probe server features | `scripts/probe_falkordb.py` → `docs/falkordb-capabilities.md` |
| Check an image upgrade | `scripts/repro_falkordb_aof_crash.sh falkordb/falkordb:<tag>`. Must exit 0 before the guards are relaxed |

**Known server issue.** Dropping a unique constraint, or deleting a constrained graph, on an AOF-persisted FalkorDB 4.22.x crashes the server on a later restart. See `docs/schema/falkordb.md` for the rules and the recovery steps.

## Layout

```
apps/api/app/
  config.py                 settings + Postgres DSN guard
  main.py                   FastAPI app factory
  auth.py · ids.py          demo permission context · typed per-kind ids, ULIDs
  api/                      routes/, models.py (contracts), deps.py, errors.py (envelope), logging.py (JSON, limits)
  services/                 alerts (dedup/correlation), incidents, investigations, service_context,
                            memories (the only path to a verified memory)
  tools/graph_tools.py      8 named, read-only, bounded graph tools
  agents/                   contracts, investigators (stub, Ollama), prompts, safety_gate
  orchestrator/             LangGraph state/graph, persist_outcome, Postgres checkpointer, Worker
  telemetry/synthetic.py    the only live-evidence source (deterministic, synthetic)
  rag/                      embeddings (Ollama, test-only hashing), indexer (chunk + embed), retrieval (hybrid)
  db/postgres.py            readiness + checkpointer setup
  domain/actions.py         canonical action JSON, spec hash, approval validity
  graph/schema.py           labels, properties, enums, allowed edges (source of truth)
  graph/repository.py       tenant-scoped, allowlisted graph access
  graph/migrate.py          migration runner; migrations/v0001_schema_v1.py, v0002_hybrid_retrieval.py
  graph/integrity.py        orphan / duplicate / drift checks
  graph/queries/*.cypher    every named query
  seeds/                    novacommerce (demo), decoy_acme (tests only), loader
scripts/                    CLI entry points (see Operations); run_worker.py, gen_web_fixtures.py
tests/                      unit + integration tests against compose services
docs/                       audit, plan, schema docs, api.md, retrieval.md, investigator.md, orchestration.md, probe output
```
