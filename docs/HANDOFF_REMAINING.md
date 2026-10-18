# Handoff: what remains after Phase 6 (2026-10-18)

Everything below is **uncommitted**. Do not commit or push unless the owner asks.

## Done

- Phase 5 gap closing: LangGraph `interrupt()` and `Command(resume=...)`, `ops.idempotency_records` (`scripts/migrate_postgres.py`), idempotent simulated executor. Docs updated.
- Phase 6 backend: `DEMO_CONTROLS_ENABLED` (default off), `GET /api/demo/controls`, `PUT /api/demo/controls/{toggle_id}`, `PUT /api/demo/controls/reset`, permission `demo:control`. Toggles: `checkout_depends_on_payment`, `rollback_policy_governs_payment`. Tests: `tests/test_phase6_demo.py`.
- Phase 6 web: `layout/DemoControlsPanel.tsx` (+ test), refetch after a toggle (`graphEpoch` in `App.tsx`, `refreshKey` in `IncidentWorkspace.tsx`).
- Live browser walkthrough (Chrome, 1440 px and 390 px): 3 users x 5 tabs, both toggles, simulation run, approve, mark outcome successful. No console errors or 5xx. Screenshots are in `.playwright-mcp/shots/`.
- Fixed: the History runs table overflowed at 390 px (wrapped in `overflow-x-auto`, `features/history/HistoryTab.tsx`).
- Docs: `docs/demo-script.md` (new), demo-controls section in `docs/api.md`, Phase 6 section and status row in `docs/NEXT_STEPS.md`, one sentence in `README.md`.

## Not done (do these next)

1. **Final verification was not run** (the run was cancelled). Run:
   ```bash
   .venv/bin/ruff check apps tests scripts
   .venv/bin/python -m pytest -q          # last known: 354 passed before Phase 6, plus 8 new = 362 expected
   cd apps/web && npm run typecheck && npm test && npm run build   # last known: 109 tests
   ```
   Changes made after the last green run: `HistoryTab.tsx` (table wrapper) and docs only, plus any edits made in the other terminals (see item 2).
2. **Check the edits made in other terminals.** Shell history shows scripted edits to `apps/web/src/features/investigation/model.test.ts` (new fixtures `investigation_executed_101.json`, `investigation_rejected_101.json`, `investigation_events_101.json`, `runEventsToTimeline`) and to `docs/api.md` / `docs/schema/falkordb.md`. I did not review or run these. Confirm the fixtures exist, `runEventsToTimeline` is exported from `model.ts`, and `npx vitest run` is green. Run `git status --short` to see the full set of changes.
3. **Docs consistency.** `docs/NEXT_STEPS.md` §2 still lists old test counts (255 / 92) and says "work is committed locally" in §3. Refresh them after the verification run.
4. **Stop the dev processes and clean up.**
   - API on `:8001` (graph `graphathon_demo_a1` on `falkordb-test` `:56390`) and Vite on `:5173` are still running.
   - `docker compose stop falkordb-test` discards the demo graph (no persistence), which is fine.
   - `/tmp/pw-walk` holds the throwaway Playwright scripts (outside the repo; safe to delete).
5. **Commit** only if the owner asks. Suggested split: Phase 5 gap closing; Phase 6 demo controls (API, web); docs.

## Known rough edges (not blocking)

- The remembered investigation id lives in `localStorage` per incident, so a fresh browser profile shows "Not investigated" until a run is started there. History still lists the run.
- After a reload the mode select shows its default, not the run's mode.
- The "Verify the outcome" banner text stays until the incident refetches.
- The graph canvas on the Evidence Graph tab is small at 1440 px (cosmetic).
- REQUEST_REVISION still creates no new action version (documented deviation).
- Skipped on the web: the run-scoped retrieval snapshot endpoint.

## Hard rules (unchanged)

- Never run a demo or an investigation against the dev graph (`:56379`) without `scripts/backup_falkordb.sh`. Do not drop constraints or delete the graph there (AOF bug).
- Postgres: only database `graphathon`. Multi-statement SQL needs `execute(sql, prepare=False)`.
- Do not use `npx prettier` here (it hung the terminal).
- `read_file` can return stale content after external edits; verify with the terminal.
- All data is synthetic (NovaCommerce).

## Run the demo

See `docs/demo-script.md` (setup, three tracks, reset).
