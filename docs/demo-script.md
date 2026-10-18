# Demo script (recording)

All data is synthetic (NovaCommerce is fictional). About 8 to 10 minutes. The golden case is **INC-101** (`nova.inc.101`): checkout 5xx after payment deployment v2.4.

## 0. Setup (before recording)

Use a throwaway graph on the ephemeral `falkordb-test` so that nothing in the dev graph is touched. An investigation writes to the graph permanently, and `falkordb-test` has no persistence.

```bash
docker compose up -d falkordb-test postgres
export FALKORDB_URL=redis://127.0.0.1:56390 GRAPH_NAME=graphathon_demo_a1
.venv/bin/python scripts/migrate_graph.py && .venv/bin/python scripts/seed.py
.venv/bin/python scripts/migrate_postgres.py
.venv/bin/python scripts/index_documents.py --no-embed     # or without the flag if Ollama is running
LLM_PROVIDER=stub ORCHESTRATOR_ENABLED=true DEMO_CONTROLS_ENABLED=true \
  .venv/bin/uvicorn app.main:app --app-dir apps/api --env-file .env --host 127.0.0.1 --port 8001 --no-access-log
cd apps/web && GRAPHATHON_API_URL=http://127.0.0.1:8001 npm run dev      # http://127.0.0.1:5173
```

- Environment variables win over `.env`, so the lines above need no `.env` edit. Use a fresh `GRAPH_NAME` per take (`graphathon_demo_a2`, ...), or restart `falkordb-test`, to get INC-101 back to "not investigated".
- `LLM_PROVIDER=stub` is deterministic. `ollama` (qwen2.5:7b) also passes the safety gate but takes longer to answer.
- The investigation id is remembered per browser profile (localStorage). Use one browser window for the whole take.
- Switch identity with the **Demo identity** select in the header (it is not authentication).

| Identity | Can |
|---|---|
| `demo-viewer` | read everything; demo controls and Investigate are disabled |
| `demo-responder` | start investigations, flip the demo edges |
| `payments-lead` | all of the above, plus approve or reject actions and verify memory |

## Track 1: graph evidence (2 to 3 min)

Identity: `demo-viewer`, incident INC-101.

1. **Live Investigation.** Point out the banner (synthetic data) and the incident header: 2 alerts, service `checkout`, SEV2.
2. **Evidence Graph.** Checkout depends on Payment; Payment has a recent deployment (v2.4) that precedes the 5xx spike. The explanation path is labelled a **graph correlation, not a confirmed cause**. Each evidence item has a `source_ref` you can open.
3. Say: the graph returns the path `alert -> checkout -[DEPENDS_ON]-> payment <- deployment v2.4`; no model decided it.
4. **Demo controls** (panel at the top; the viewer sees it disabled). Switch to `demo-responder`:
   - **Remove link** on *Checkout depends on Payment*. The recommendation turns to **no rollback path** (rollback paths: 0) and the incident's explanation paths disappear without a reload. Click **Restore both**.
   - **Remove link** on *Rollback policy v2 governs Payment*. The recommendation turns to **no active policy: escalate** (a rollback must escalate, not go to the approver). Click **Restore both**.
   - Say: the answer follows the graph. No database edit was made; only the two edges were flipped.

## Track 2: verified memory and the company brain (2 min)

Identity: `demo-responder` or `demo-viewer`, tab **Knowledge & Memory**.

1. **Historical Memory.** INC-092 appears twice. *Rolling back a payment deployment* succeeded and **supports** the proposal. *Restarting checkout pods* failed and **warns against repeating** it. Both are verified by a human.
2. Point at "Not shown, because they cannot be evidence: 2 draft." Draft memories never reach retrieval.
3. **Company Knowledge.** The official policy (Payment rollback policy v2, requires `approver:payment`) and the runbook (Payment service deployment rollback) are authoritative. Matched documents are only context, never a conclusion.
4. Say: facts, memory and documents are labelled by how trustworthy they are (official, company document, inferred, AI-recorded).

## Track 3: orchestration and human-in-the-loop review (3 to 4 min)

1. As `demo-responder`, tab **Live Investigation**: choose mode **Simulation**, click **Start Investigation**. The stages run Detected, Gathering Context, Analyzing, Recommending and stop at **Human Review: waiting for human**. Say: three retrievals run in parallel (graph, memory, live evidence), the investigator proposes, and an evidence safety gate checks every claim before anything is shown.
2. Show **History**: the run, its status and the activity timeline (`Awaiting human approval`).
3. Switch to `payments-lead`, tab **Human Review**:
   - The proposed action is a *simulated deployment rollback* of `nova.dep.payment.v2_4`, risk medium, runbook v3, requires `approver:payment`. **Why this is recommended** states that the cause is not confirmed and cites 27 evidence items.
   - As `demo-responder` the **Approve** button is disabled (no `action:review`). Mention it.
   - Add a comment and click **Approve**.
4. Result: *Approved by payments-lead. Simulated execution succeeded (ticket SIM-...). Nothing real was changed.* Execution & Learning turns complete. The timeline shows Action approved, Simulated execution and the executor step. Say: the executor is idempotent (a retry never executes twice) and only ever simulates.
5. **Verify the outcome.** A draft memory was written. As `payments-lead` click **Mark successful**. Back in **Knowledge & Memory** the INC-101 memory now appears as a verified lesson and the draft count drops.
6. Closing line: agents propose, the graph and policy constrain, a person decides, and the outcome becomes verified memory.

## Reset between takes

- New graph name and a re-seed (Setup), or `docker compose restart falkordb-test` and re-run migrate and seed.
- Clear the browser's localStorage (or use a new profile) so the old investigation id is forgotten.
- Never run the demo against the dev graph on `:56379` without `scripts/backup_falkordb.sh` first.

## Troubleshooting

- Panel missing: the API was started without `DEMO_CONTROLS_ENABLED=true` (the readiness dot stays green).
- Approve disabled as `payments-lead` with "Start an investigation first": the browser profile has no remembered run. Start one in that profile (an active run in the same mode is returned instead of a new one).
- Port conflicts: the web proxy targets `GRAPHATHON_API_URL`; API on 8001, Vite on 5173.
