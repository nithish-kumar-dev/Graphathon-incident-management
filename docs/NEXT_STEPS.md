# Next steps: handoff (2026-10-18)

This is a handoff for the next coding assistant or engineer picking up this repo. Read §1–§3 before changing anything.

**Project:** graph-grounded incident investigation over SYNTHETIC data. NovaCommerce is a fictional company. The stack is FastAPI + FalkorDB (graph) + LangGraph (orchestration) + Postgres (LangGraph checkpoints only) + a React/Vite dashboard + local Ollama (embeddings and LLM).

**Phase briefs:** 02_PHASE_0 … 08_PHASE_6 were supplied in chat; their requirements are summarised in this file and in `docs/`. Signed-off decisions are in `docs/refactor-plan.md` §8.

---

## 1. Hard rules (break these and you lose data or the demo)

1. **The FalkorDB 4.22.x AOF bug.** On the persistent dev server, `falkordb` at `127.0.0.1:56379`:
   - NEVER drop a unique constraint.
   - NEVER `GRAPH.DELETE` a graph that has constraints.

   The next restart segfaults and the container crash-loops. Deleting *nodes* is safe. Tests use the ephemeral `falkordb-test` server at `127.0.0.1:56390` and refuse any persistent server. See `docs/schema/falkordb.md` → "Known server issue" for details and recovery, and use `scripts/repro_falkordb_aof_crash.sh` before upgrading the image.
2. **Postgres.**
   - The project uses its own container at `127.0.0.1:55432`, DB `graphathon`. The host Postgres.app on `:5432` holds unrelated real databases: never touch it. Config refuses any other DB name.
   - Never write DDL for LangGraph's checkpoint tables. Only `PostgresSaver.setup()` creates them (`scripts/init_checkpointer.py`).
3. **Port 8000 belongs to another local project** (`Raj-Graph/graphsentinel`). Do not kill it. Run this API on **:8001** and start Vite with `GRAPHATHON_API_URL=http://127.0.0.1:8001`.
4. **Dev-graph writes are permanent.** Clicking **Investigate** on INC-101 (or `POST /api/investigations`) moves it `open → investigating`, and transitions cannot go back. To rehearse, use the test server, or back up first with `scripts/backup_falkordb.sh`.
5. **Safety invariants must hold.** Tests enforce them; never weaken them:
   - Graph correlations are `correlated`, never `confirmed`. Only humans confirm.
   - Memories become `verified` only through `app/services/memories.py`, by human or ground-truth validation. A proposed or unexecuted fix is never a verified outcome.
   - `restricted` documents are never indexed or returned.
   - Every evidence id in a response exists in the graph.
   - Graph tools are read-only, through a `ReadOnlyGraph` handle.
   - `recommendation_only` mode never executes anything. The only allowed action type is `rollback_deployment_simulated`, and it is simulated.
   - No raw exceptions, DSNs or input values in API errors.
6. **Applied migrations are frozen.** Never edit one: `migrate.py` aborts on a checksum mismatch. Add `v000N_*.py` instead.

## 2. Run it

```bash
docker compose up -d                         # falkordb :56379, falkordb-test :56390, postgres :55432
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python scripts/migrate_graph.py && .venv/bin/python scripts/seed.py
.venv/bin/python scripts/index_documents.py   # needs Ollama + nomic-embed-text (else --no-embed)
.venv/bin/uvicorn app.main:app --app-dir apps/api --env-file .env --host 127.0.0.1 --port 8001 --no-access-log
cd apps/web && npm install && GRAPHATHON_API_URL=http://127.0.0.1:8001 npm run dev   # http://127.0.0.1:5173
```

| Check | Command | Last result |
|---|---|---|
| Backend tests | `.venv/bin/python -m pytest -q` | 255 passed (`test_phase4_investigator.py` excluded), plus 71 Phase 4 tests passed separately |
| Lint | `.venv/bin/ruff check apps tests scripts` | **2 errors**: C408 in `tests/test_phase4_investigator.py` lines 29 and 41. Fix with `ruff check --fix --unsafe-fixes` |
| Frontend | `cd apps/web && npm run typecheck && npm test && npm run build` | 92 tests pass, build OK |

- Ollama on `127.0.0.1:11434` has `nomic-embed-text` (768-d, measured) and `qwen2.5:7b` (JSON-schema output verified; cold load about 12 s).
- `.env` is set to: `LLM_PROVIDER=stub`, `OLLAMA_MODEL=qwen2.5:7b`, `EMBEDDING_PROVIDER=ollama`, `ORCHESTRATOR_ENABLED=true`.

## 3. Where things stand

| Phase | Status | Docs |
|---|---|---|
| 0 Audit | Done (greenfield) | `docs/current-state-audit.md`, `docs/refactor-plan.md` |
| 1 DBs, migrations, seed | Done | `docs/schema/falkordb.md`, `docs/schema/postgres.md`, `docs/falkordb-capabilities.md` |
| 2 Typed API | Done | `docs/api.md` |
| 3 Graph tools + hybrid GraphRAG | Done (migration 0002 applied to dev; docs indexed) | `docs/retrieval.md` |
| 4 LangGraph orchestration | Done (stub and Ollama investigators, gate, parallel retrieval, Postgres checkpoints, recovery) | `docs/investigator.md`, `docs/orchestration.md` |
| 5 Human review + executor | Not started | — |
| 6 Frontend | Built; fixtures regenerated from the real API; live browser re-check pending (§4) | `apps/web/README.md` |

The work is committed locally (nothing pushed). The remote `origin` is the empty `github.com/nithish-kumar-dev/Graphathon-incident-management`. `.env` and `backups/` are gitignored.

## 4. Phase 4: done

The deterministic golden path works end to end with `LLM_PROVIDER=stub`, and `LLM_PROVIDER=ollama` passes the gate on INC-101 (live test, no fallback). Details: `docs/investigator.md` (stub, Ollama prompt and format, fallback label, gate rules, telemetry) and `docs/orchestration.md` (nodes, state, statuses, recovery, worker).

- **Tests:** 306 backend (`tests/test_phase4_{investigator,gate,telemetry,orchestrator}.py` among them; the orchestrator suite also runs against the real `PostgresSaver`) and 92 web.
- **Ollama fix.** The 7B model chose `deployment_id: null` and cited a memory id as evidence. The Ollama `format` schema now requires `deployment_id` (`output_format_schema()`), and the prompt lists `action_candidates`. The gate was not changed.
- **Web fixtures** `apps/web/src/test/fixtures/investigation_{completed,awaiting_review,escalated,failed}_101.json` are generated from the real API by `scripts/gen_web_fixtures.py` (ephemeral `falkordb-test` only). Regenerate them whenever the investigation payload changes.
- **Still to do from Phase 4:** the live browser check (§6) against a backed-up or test graph. Clicking Investigate on INC-101 in the dev graph is irreversible.
- **Carried into Phase 5:** add `required_approver_role` to `ProposedActionOut` (computed server-side from the active Decision) and have the UI prefer it over matching paths. `human_review` and `restricted_executor` are placeholders. AgentAction statuses are in `app/graph/schema.py` ENUMS.

## 5. Phase 5: human review and the safe executor (after Phase 4 passes)
- **Replace the `human_review` placeholder with LangGraph `interrupt()`** and resume with `Command(resume=...)` on the same thread_id. Use the durable Postgres checkpointer. Verify the installed API by introspection: langgraph 1.2.16 exposes `interrupt` and `Command` in `langgraph.types`.
- **Add `POST /api/actions/{id}/review`** with body `{decision: APPROVE|REJECT|REQUEST_REVISION|ESCALATE, comment?}`, requiring the `action:review` permission.
  - Check server-side that the reviewer's Responder holds the active Decision's `required_approver_role`, and that the policy's effective dates cover now.
  - Save an `ApprovalRecord` per decision, with `spec_hash`, `action_version`, `approver_id`, `decided_at_ms`, `expires_at_ms`, `policy_decision_id`, and edges `HAS_REVIEW` and `DECIDED_BY`. **Never store a bare boolean.**
  - REQUEST_REVISION creates a new AgentAction version with a new hash and needs fresh validation. Any old approval must not apply: `valid_approvals.cypher` and `app/domain/actions.approval_applies` already enforce this.
- **Restricted executor:**
  - It runs allowlisted types only (`rollback_deployment_simulated`). In `simulation` mode it writes a deterministic simulated ticket/status (AgentAction `executed_simulated` plus a TimelineEvent).
  - `recommendation_only` never invokes it. No shell, no real rollback, no webhooks.
  - Use `ops.idempotency_records` (new Postgres table in the `ops` schema, with its own numbered SQL migration; never in `public`) keyed by action id and spec hash. Bounded retries, audit events, and honest failure reporting.
  - Side effects only AFTER the interrupt resumes, in nodes that are not replayed.
- **Tests:** reject → no execution; a changed hash invalidates the approval; an expired approval fails; the revision cap; resume after restart; a repeated resume is safe; recommendation mode runs zero actions.
- **Web:** enable the Review buttons when the API exists. Keep the per-user disabled reasons, show the server's 403/409 errors, and show the ApprovalRecord and simulated outcome with exact evidence ids.
- **Gate:** a judge can inspect the approval and the simulated outcome with exact evidence ids.

## 6. Phase 6 gate: demo readiness
- **Safe demo controls.** No manual DB edits during narration. Add an endpoint or script to toggle the `nova.svc.checkout -[DEPENDS_ON]-> nova.svc.payment` edge and the `nova.dec.payment.rollback_v2 -[GOVERNS]-> nova.svc.payment` edge. Use `GraphRepository.delete_edge` / `merge_edge`: node and edge writes are safe on AOF; constraint drops are not. Gate it behind a demo-only setting, and show the recommendation changing.
- **"No stale result after graph mutation":** after a toggle, the UI must refetch. The hooks already key on incident and user, so add a reload trigger.
- **Browser walkthrough with Playwright,** saving screenshots to `.playwright-mcp/shots/` (gitignored):
  - INC-101 with each demo user (`demo-viewer`, `demo-responder`, `payments-lead`) across all 5 tabs
  - an Investigate run on a **backed-up or test** graph
  - the 390 px layout
- **Recording script:** the three tracks are (1) graph evidence, (2) verified memory and the company brain, (3) agent orchestration plus human-in-the-loop review.

## 7. Nice-to-haves and known limits
- Alert ingest: two different events in adjacent dedup buckets arriving at the same instant can both be created. A crash between writes can lose a timeline event. Both are documented in `docs/api.md`.
- The retrieval endpoint builds an embedder per request, which costs one Ollama `/api/tags` call each time. Cache the model version.
- Full-text and vector indexes are graph-wide. The demo filters to one tenant; production should use per-tenant graphs (`docs/retrieval.md`).
- Dev-mode React StrictMode shows aborted duplicate requests in the network tab. This is expected.
- `docs/refactor-plan.md` §6's file list predates Phase 3+. Refresh it.

## 8. Key file map

```
apps/api/app/
  agents/contracts.py        Phase 4 shared types (investigator I/O, gate, telemetry)
  agents/{investigator,prompts,safety_gate}.py
  telemetry/synthetic.py
  orchestrator/{state,graph,dependencies,checkpoint,persist,runner}.py   (untested)
  rag/{embeddings,indexer,retrieval}.py      tools/graph_tools.py
  services/{alerts,incidents,investigations,memories,service_context}.py
  graph/{schema,repository,migrate,integrity}.py   graph/queries/*.cypher   graph/migrations/
  api/{models,deps,errors,logging}.py  api/routes/*.py   main.py (lifespan starts the worker)
apps/web/src/  api/ hooks/ components/ui/ layout/ features/{overview,evidence,activity,memory,review}/
scripts/       migrate_graph, seed, index_documents, retrieve_context, inventory_graph, init_checkpointer,
               run_worker, backup_falkordb.sh, reset_graph, probe_falkordb, repro_falkordb_aof_crash.sh
tests/         conftest.py (test server only), test_phase4_*.py, test_api_*.py, ...
```
