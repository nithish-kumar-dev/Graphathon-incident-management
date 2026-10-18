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
| Backend tests | `.venv/bin/python -m pytest -q` | 363 passed |
| Lint | `.venv/bin/ruff check apps tests scripts` | All checks pass |
| Frontend | `cd apps/web && npm run typecheck && npm test && npm run build` | 109 tests pass, build OK |

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
| 5 Human review + executor | Done (`interrupt()` review and resume, idempotent simulated executor, step events, run list, memory validation; web wired). Apply graph v0003 and `scripts/migrate_postgres.py` on dev | `docs/api.md`, `docs/orchestration.md` |
| 6 Demo readiness | Done: demo controls (API and web panel), refetch after a toggle, live browser walkthrough, recording script | `docs/demo-script.md`, `docs/api.md` |

The work through Phase 6 is uncommitted (see `docs/HANDOFF_REMAINING.md`); nothing is pushed. The remote `origin` is the empty `github.com/nithish-kumar-dev/Graphathon-incident-management`. `.env` and `backups/` are gitignored.

## 4. Phase 4: done

The deterministic golden path works end to end with `LLM_PROVIDER=stub`, and `LLM_PROVIDER=ollama` passes the gate on INC-101 (live test, no fallback). Details: `docs/investigator.md` (stub, Ollama prompt and format, fallback label, gate rules, telemetry) and `docs/orchestration.md` (nodes, state, statuses, recovery, worker).

- **Tests:** 306 backend (`tests/test_phase4_{investigator,gate,telemetry,orchestrator}.py` among them; the orchestrator suite also runs against the real `PostgresSaver`) and 92 web.
- **Ollama fix.** The 7B model chose `deployment_id: null` and cited a memory id as evidence. The Ollama `format` schema now requires `deployment_id` (`output_format_schema()`), and the prompt lists `action_candidates`. The gate was not changed.
- **Web fixtures** `apps/web/src/test/fixtures/investigation_{completed,awaiting_review,escalated,failed}_101.json` are generated from the real API by `scripts/gen_web_fixtures.py` (ephemeral `falkordb-test` only). Regenerate them whenever the investigation payload changes.
- **Still to do from Phase 4:** the live browser check (§6) against a backed-up or test graph. Clicking Investigate on INC-101 in the dev graph is irreversible.
- **Carried into Phase 5 (done):** `required_approver_role` is on `ProposedActionOut` and the UI prefers it over matching paths.

## 5. Phase 5: human review and the safe executor

**Status: done, following the plan below.**

- **`interrupt()` and resume.** `human_review` pauses the run (`awaiting_review`); `POST /api/actions/{id}/review` records the `ApprovalRecord` (bound to `spec_hash` and version), then resumes the same `thread_id` with `Command(resume=...)`. Without an in-process worker the decision is saved and the standalone worker's poll resumes the run. Details: `docs/orchestration.md`.
- **Executor and idempotency.** Only `rollback_deployment_simulated`, only for `simulation` runs. Each effect is guarded by `ops.idempotency_records` (`scripts/migrate_postgres.py`, key `<action id>:<spec hash>`, lease, 3 attempts); replays heal state and never run twice. Expired approvals become `expired`. Without a store it fails closed. The draft memory stays out of retrieval until a person validates it.
- **REQUEST_REVISION creates no new action version.** The action becomes `revision_requested`, the session `completed`, and the user starts a new investigation. This is still a deviation from the plan.
- **Events by polling.** `GET /api/investigations/{id}/events` replaces SSE. Events are `AgentEvent` nodes (migration v0003, additive).
- **Skipped on the web:** the run-scoped retrieval snapshot (`GET /api/investigations/{id}/retrieval`) is not used by the UI, and the web fixtures for review states are hand-built rather than generated by `scripts/gen_web_fixtures.py`.
- **One-time steps:** `.venv/bin/python scripts/migrate_graph.py` on the dev graph (v0003) and `.venv/bin/python scripts/migrate_postgres.py` (ops tables).
- **Tests:** `tests/test_phase5_review.py`, `tests/test_ops_idempotency.py` (the review suite also runs against the real `PostgresSaver` and Postgres idempotency store).

## 6. Phase 6: demo readiness

**Status: done (uncommitted). The recording script is `docs/demo-script.md`.**

- **Safe demo controls.** `DEMO_CONTROLS_ENABLED=true` (default off) exposes `GET/PUT /api/demo/controls` (`docs/api.md`). Only `merge_edge` / `delete_edge` on the `DEPENDS_ON` and `GOVERNS` edges; permission `demo:control` (responder, payments lead). The web panel (`layout/DemoControlsPanel.tsx`) is hidden when the flag is off.
- **No stale result after a toggle.** The panel bumps a `graphEpoch` in `App.tsx`; `IncidentWorkspace` takes it as `refreshKey` and refetches the incident, timeline, memories and graph context.
- **Browser walkthrough (Playwright, 1440 px, test graph `graphathon_demo_*` on `falkordb-test`).** INC-101 as each demo user across all 5 tabs: no console errors and no 5xx. Both toggles flip the recommendation and the incident view refreshes. A simulation investigation reaches `awaiting_review`; `payments-lead` approves; the simulated execution succeeds; the draft memory is marked successful and then appears under Historical Memory. Viewers see the toggle buttons disabled. Screenshots are in `.playwright-mcp/shots/` (gitignored).
- **390 px check.** All five tabs fit. The History runs table overflowed (492 px) and now scrolls inside its card.
- **Known rough edges.** The investigation id is remembered per browser (localStorage), so a fresh browser profile shows "Not investigated" until a run is started there; the History tab still lists the run. After a reload the mode select shows its default, not the run's mode. The banner keeps saying "Verify the outcome" until the incident refetches.
- **Recording script:** `docs/demo-script.md` (three tracks: graph evidence, verified memory and the company brain, agent orchestration plus human review).

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
