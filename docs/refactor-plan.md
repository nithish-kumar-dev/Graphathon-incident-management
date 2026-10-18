# Refactor / Bootstrap Plan (output of Phase 0)

The audit (`docs/current-state-audit.md`) found an **empty repository**: no git history, no code, no graph, and no project tables. There is no legacy code to refactor yet. The 13 legacy labels are treated as the **target spec** from the briefs.

This plan has two branches, and **Step 0 decides which one applies**. §3 is the proposed first schema migration that the Phase 0 gate asks the team to agree on.

## Step 0: Decide the source of truth (blocking)

| Option | When | Next action |
|---|---|---|
| **A. Legacy repo exists elsewhere** | The 13-label system lives at another path, remote or machine | Point to it. Re-run Phase 0 against it. Keep §3 as the target schema and add a mapping from legacy to target |
| **B. Greenfield** | No legacy system exists, or the team will not carry it | Approve §3 and the open decisions in §5, then execute §2 |

Nothing in §2 runs until Step 0 is answered.

## 1. Non-negotiable boundaries (both options)

- **FalkorDB is canonical** for every incident, knowledge and agent-audit entity:
  - incident: Incident, Alert, Evidence, TimelineEvent
  - organization: Service, Team, Responder, Deployment
  - knowledge: Runbook, Decision, Document, and DocumentChunk (Phase 3, optional)
  - agent: AgentSession, AgentAction, ApprovalRecord, AgentMemory
- **Postgres** holds only:
  - LangGraph checkpointer tables, created **only** by the installed `PostgresSaver.setup()`. No project SQL ever creates, alters or normalizes `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` or `checkpoint_migrations`.
  - ops tables (`idempotency_records`, `notification_outbox`, and `execution_locks` if needed), added only when a phase actually needs them. They live in a separate `ops` schema with our own numbered migrations.
- **Isolated Postgres.** A dedicated container, `postgres:15-bookworm` (already cached locally), bound to `127.0.0.1:55432`, with DB `graphathon`. The host's Postgres.app on port 5432 holds unrelated databases and is never touched. Startup refuses any DSN whose database is not `graphathon`.
- **No distributed ACID.** A graph write and a Postgres write are never atomic together. Graph writes are idempotent (`MERGE` on `id`). Side effects go through the outbox and an idempotency key, and are reconciled. Nothing claims cross-database atomicity.
- **Three memories, kept separate:**
  - LangGraph checkpoints, in Postgres
  - `AgentMemory` nodes, in the graph
  - company knowledge (Service/Decision/Runbook/Document), in the graph

  Agents get named, bounded, typed repository functions. They get no shell and no Cypher assembled from user strings.

## 2. Priority order (Option B)

| P | Step | Exit criterion | Rollback |
|---|---|---|---|
| P0 | Answer Step 0, approve §3 and decide §5 | Sign-off recorded in §7 | None |
| P1 | `git init`. Scaffold `pyproject.toml`, `.gitignore` and `.env.example`. `docker-compose.yml` with a pinned FalkorDB tag on `127.0.0.1:56379`, Postgres on `127.0.0.1:55432`, named volumes and health checks | `docker compose up -d` reports both containers healthy. `redis-cli -p 56379 PING` returns PONG. `docker compose exec postgres pg_isready` succeeds | `docker compose down` (keeps volumes). `down -v` only with explicit approval |
| P2 | `scripts/probe_falkordb.py` runs against throwaway graph `__probe`. It checks range indexes (single and multi-property), full-text, vector, `GRAPH.CONSTRAINT` unique, temporal types, variable-length path bounds and query timeout | `docs/falkordb-capabilities.md` generated from real output, with the image tag and client version | Delete the generated file. The probe deletes `__probe` itself |
| P3 | Graph migration runner and `0001_schema_v1` (§3), with syntax taken from the P2 output | A second run is a no-op. `(:SchemaMigration {version:1, checksum})` is present. A checksum mismatch aborts | `0001.down` drops only the indexes and constraints `0001` created. Dev only; anything beyond dev needs approval |
| P4 | `scripts/init_checkpointer.py` calls the installed `PostgresSaver.setup()` behind the DSN guard | Checkpoint tables exist in `graphathon.public` only. A second run is a no-op | Drop DB `graphathon` in the container (dev only, with approval) |
| P5 | NovaCommerce seed (§4) plus a decoy tenant used only by tests. `scripts/reset_graph.py` requires typed confirmation and never runs at startup | A second seed changes no node or edge counts. Orphan and duplicate queries return 0 | `reset_graph.py --tenant nova --confirm nova` |
| P6 | Graph repository layer: allowlisted labels and relationship types, mandatory `tenant_id`/`env`, depth and limit bounds, parameterized queries only | Smoke tests pass: repeated seed, unique IDs, tenant scoping, persistence across restart, invalid relationship rejected, approval/version history | Revert commit |
| P7 | `docs/schema/falkordb.md`, `docs/schema/postgres.md`, `graph/queries/*.cypher`, migration notes | Docs match the P2 output and `0001` | Revert commit |

Phases 2–6 (API, graph tools and memory, LangGraph, HITL, frontend) start only once P0–P7 are green.

## 3. Proposed first schema migration: `graph/migrations/0001_schema_v1` (needs sign-off)

### 3.1 Conventions

- **Graph.** One graph named `graphathon`, resolved from config and never taken from request input. Every node carries `tenant_id` and `env`, and every repository query filters on them. A single graph keeps the tenant-scoping tests meaningful, because a decoy tenant shares the graph. Per-tenant graphs remain an upgrade path (§5, O2).
- **ID key.** Every label uses **`id`**: a string that is globally unique, so that a per-label unique constraint on `id` alone works. There are no `incident_id`-style keys.
  - Seed IDs are deterministic, so `MERGE` makes seeding idempotent: `nova.svc.checkout`, `nova.inc.101`, `nova.dep.payment.v2_4`.
  - Runtime IDs are a prefix plus a ULID: `act_01J…`, `apr_01J…`.
  - Human keys such as `INC-101` go in `key`.
  - External identifiers go in `source_ref`.
- **Common properties.** `id`, `tenant_id`, `env` (`dev` / `staging` / `prod` / `synthetic`), `source` (`seed` / `ingest` / `agent` / `human`), `created_at_ms`, `updated_at_ms`, `schema_version`.
- **Time and UTC policy.**
  - All timestamps are `*_at_ms`: integers in epoch milliseconds, UTC. They are range-indexable and portable.
  - The API converts them to and from ISO-8601 with `Z`.
  - Native temporal types are used only if P2 confirms them, and only alongside the integer field.
- **Arrays.** Small string lists (`roles`, `provenance_refs`, `allowed_action_types`) are stored as array properties if P2 confirms support. Otherwise they are stored as JSON strings, validated by Pydantic.

### 3.2 Labels and properties beyond the common ones

| Label | Properties |
|---|---|
| Incident | `key`, `title`, `severity` (sev1–4), `status` (open/investigating/mitigated/resolved), `started_at_ms`, `resolved_at_ms` |
| Alert | `fingerprint`, `severity`, `fired_at_ms`, `summary_redacted`, `source_ref` |
| Evidence *(new)* | `kind` (metric/log/deploy_event/alert/ticket/doc), `source_ref` (required), `excerpt_redacted`, `observed_at_ms`, `content_hash` |
| TimelineEvent | `at_ms`, `type`, `actor`, `summary`, `ref_id` |
| Service | `name`, `tier` |
| Team | `name` |
| Responder | `handle` (synthetic, no PII), `roles` (e.g. `approver:payment`) |
| Deployment | `version`, `deployed_at_ms`, `status`, `source_ref` |
| Runbook | `title`, `version`, `uri`, `allowed_action_types` |
| Decision | Policy or ADR, **not** an agent conclusion. `title`, `statement`, `status` (active/superseded), `effective_from_ms`, `effective_to_ms`, `required_approver_role` |
| Document | `title`, `uri`, `doc_type` (adr/policy/postmortem/runbook), `classification` |
| AgentSession | `thread_id` (the LangGraph thread), `run_id`, `mode` (recommendation_only/simulation), `status`, `started_at_ms`, `ended_at_ms`, `revision_count` |
| AgentAction | `proposal_id`, `version`, `action_type` (allowlisted), `spec_json` (canonical JSON), `spec_hash` (sha256 hex of `spec_json`), `target_service_id`, `risk`, `mode`, `status`, `approval_expires_at_ms`. **Each revision is a new node** with the same `proposal_id`, `version+1` and a new hash |
| ApprovalRecord *(new)* | `decision` (APPROVE/REJECT/REQUEST_REVISION/ESCALATE), `spec_hash`, `action_version`, `approver_id`, `decided_at_ms`, `expires_at_ms`, `scope`, `policy_decision_id`, `comment` |
| AgentMemory | `memory_type` (episodic/procedural), `verification_status` (draft/verified/rejected/superseded), `outcome` (successful/failed/unknown), `summary`, `provenance_refs`, `model_version`, `validated_at_ms`. **`verified` is set only by a human validation or by accepted ground truth.** A proposed fix is never a verified outcome. Failed outcomes are kept |
| DocumentChunk *(Phase 3, optional)* | Not in `0001`. Added by a later migration only if Phase 3 selects RAG |
| SchemaMigration | Bookkeeping: `version`, `name`, `checksum`, `applied_at_ms` |

### 3.3 Relationships

The Phase 1 essential list, verbatim. Each name and direction is used everywhere: Cypher, DTOs, tests and docs.

```
(Incident)-[:HAS_ALERT]->(Alert)
(Incident)-[:HAS_EVIDENCE]->(Evidence)
(Incident)-[:AFFECTS]->(Service)
(Service)-[:DEPENDS_ON]->(Service)
(Deployment)-[:DEPLOYED_TO]->(Service)
(Team)-[:OWNS]->(Service)
(Responder)-[:MEMBER_OF]->(Team)
(Decision)-[:GOVERNS]->(Service)
(Decision)-[:DOCUMENTED_IN]->(Document)
(Decision)-[:SUPERSEDES]->(Decision)
(Runbook)-[:APPLIES_TO]->(Service)
(Evidence)-[:OBSERVED_ON]->(Service)
(Evidence)-[:REFERS_TO]->(Deployment)
(AgentAction)-[:SUPPORTED_BY]->(Evidence)
(AgentAction)-[:TARGETS]->(Service)
(AgentAction)-[:PART_OF]->(AgentSession)
(AgentAction)-[:HAS_REVIEW]->(ApprovalRecord)
(AgentMemory)-[:ABOUT]->(Incident)
(AgentMemory)-[:DERIVED_FROM]->(AgentAction)
(AgentMemory)-[:GROUNDED_IN]->(Evidence)
(AgentMemory)-[:VALIDATED_BY]->(Responder)
(AgentMemory)-[:SUPERSEDES]->(AgentMemory)
(Document)-[:RELATES_TO]->(Service)
(Document)-[:RELATES_TO]->(Incident)
```

**Proposed additions.** The briefs need these, but the Phase 1 list does not include them, so they need sign-off (§5, O5):

```
(Incident)-[:HAS_EVENT]->(TimelineEvent)        // Phase 2 timeline endpoint; TimelineEvent otherwise has no edges
(AgentSession)-[:INVESTIGATES]->(Incident)      // Phase 2 investigation-by-incident; otherwise reachable only via actions
(ApprovalRecord)-[:DECIDED_BY]->(Responder)     // Phase 5 "linked to authenticated Responder"
(Document)-[:HAS_CHUNK]->(DocumentChunk)        // Phase 3 only, in a later migration
```

The repository layer holds an allowlist of `(source label, relationship type, target label)` triples. Any write outside it is rejected, and a P6 test covers that.

### 3.4 Indexes and constraints (hot lookups only)

The syntax is finalized from P2 output. Every statement checks first whether the index or constraint already exists, so it is idempotent.

| What | Why |
|---|---|
| Range index on `id`, every label | `MERGE` and point lookups. A prerequisite for the unique constraint |
| Unique constraint on `id`, every label | Only if P2 confirms `GRAPH.CONSTRAINT`, and only **after** the duplicate-check query returns 0. Fallback: `MERGE`-only writes plus a duplicate check in CI |
| `Incident.tenant_id`, `Incident.status`, `Incident.started_at_ms` | Incident list |
| `Alert.fingerprint`, `Alert.fired_at_ms` | Ingest dedup window |
| `Deployment.deployed_at_ms` | `get_recent_deployments` |
| `Decision.status`, `AgentMemory.verification_status` | Active-decision and verified-memory filters |
| `AgentAction.spec_hash`, `AgentSession.thread_id` | Approval check and resume lookup |
| Full-text index on `Runbook.title`, `Document.title` | Phase 3 keyword fallback. Only if P2 confirms support |

`0001` creates no vector index. That waits for a Phase 3 migration, after the embedding dimension has been measured.

### 3.5 Postgres in Phase 1

- Phase 1 creates only the checkpointer tables, via `PostgresSaver.setup()`.
- These ops tables are deferred:
  - `ops.idempotency_records`, with a unique `key` and a status: Phase 2 if alert-ingest idempotency is not covered by graph `MERGE`, otherwise Phase 5.
  - `ops.notification_outbox`: Phase 5, only if `notify_channel` exists.
  - `ops.execution_locks`: only if concurrent executor runs are possible.

### 3.6 Diff against the first-pass draft

The draft written earlier today did not follow the Phase 1 brief. Nothing was ever applied.

| Draft | Now | Reason |
|---|---|---|
| `(Alert)-[:GROUPED_INTO]->(Incident)` | `(Incident)-[:HAS_ALERT]->(Alert)` | Phase 1 edge list |
| `(Evidence)-[:ABOUT]->(Incident)` | `(Incident)-[:HAS_EVIDENCE]->(Evidence)` | Phase 1 |
| `(Service)-[:OWNED_BY]->(Team)` | `(Team)-[:OWNS]->(Service)` | Phase 1 |
| `(Evidence)-[:DERIVED_FROM]->(…)` | `OBSERVED_ON` Service, `REFERS_TO` Deployment | Phase 1 |
| `(AgentSession)-[:PERFORMED]->(AgentAction)` | `(AgentAction)-[:PART_OF]->(AgentSession)` | Phase 1 |
| `(AgentAction)-[:APPROVED_VIA]->(ApprovalRecord)` plus `APPROVED_BY` | `HAS_REVIEW` plus proposed `DECIDED_BY` | Phase 1 / Phase 5 |
| `Decision` = hypothesis or root cause, with `CITES` Evidence | `Decision` = policy/ADR with `GOVERNS` / `DOCUMENTED_IN` / `SUPERSEDES` | Phase 1. Agent hypotheses are not Decisions (§5, O1) |
| AgentMemory `scope`, `confidence`; `LEARNED_FROM` AgentSession | `memory_type`, `verification_status`, `outcome`, provenance; `ABOUT`, `DERIVED_FROM`, `GROUNDED_IN`, `VALIDATED_BY`, `SUPERSEDES` | Phase 1 / Phase 3 |
| Graph per tenant (`incidents__{tenant}__{env}`) | Single graph `graphathon` with mandatory property filters | Simpler runner. Scoping tests stay meaningful (O2) |
| Tenant `synthetic_acme` | `nova` (NovaCommerce) | Phase 1 seed spec |
| `TimelineEvent-[:NEXT]` chain | Dropped; order by `at_ms` | Not required. A chain is fragile under concurrent inserts |

## 4. NovaCommerce seed (P5) and the "edge changes the recommendation" path

**Seed contents:**

- Services: checkout, payment, inventory, auth, ledger, each with an owning Team and Responders.
- Deployment `v2.4` DEPLOYED_TO payment.
- Prior incident INC-092, resolved, with one **verified** episodic AgentMemory:
  - VALIDATED_BY a Responder
  - GROUNDED_IN Evidence
  - outcome `successful`, confirmed by a synthetic post-incident result
- Current incident INC-101, open.
- A Runbook APPLIES_TO payment, with `allowed_action_types: ["rollback_deployment_simulated"]`.
- Two Decisions on payment: an active one that SUPERSEDES a superseded one. Each is DOCUMENTED_IN a Document.
- Evidence nodes, each with a `source_ref`.

**Golden evidence path** (exact IDs are fixed when P5 lands):

```
(nova.inc.101)-[:AFFECTS]->(nova.svc.checkout)-[:DEPENDS_ON]->(nova.svc.payment)
    <-[:DEPLOYED_TO]-(nova.dep.payment.v2_4)<-[:REFERS_TO]-(nova.ev.101.deploy)<-[:HAS_EVIDENCE]-(nova.inc.101)
(nova.dec.payment.rollback_v2)-[:GOVERNS]->(nova.svc.payment)          // active policy: who may approve
(nova.dec.payment.rollback_v2)-[:SUPERSEDES]->(nova.dec.payment.rollback_v1)
```

**The two changes the demo makes:**

- Remove `checkout-[:DEPENDS_ON]->payment`. The v2.4 deployment leaves the blast radius, and the rollback recommendation disappears.
- Point the active Decision elsewhere. The required approver changes.

A test asserts both changes, and the demo performs them through a safe script, not by editing the DB by hand during narration.

## 5. Open decisions (answer with the sign-off)

| # | Decision | Recommendation |
|---|---|---|
| O1 | Where investigator findings (`observed` / `correlated` / `hypothesis` / `confirmed`) persist | Live in checkpoint state during the run. At `persist_outcome`, store them as Pydantic-validated `findings_json` on AgentSession, citing Evidence IDs that were checked to exist. No new label in `0001` |
| O2 | Single graph versus a graph per tenant | Single graph `graphathon` for the hackathon |
| O3 | FalkorDB host port | `127.0.0.1:56379`, to avoid any future local Redis on 6379 |
| O4 | Python version and dependency tooling | 3.14 (wheels verified, audit E15), with 3.13 fallback. `pyproject.toml` plus a lockfile from `pip freeze` into `requirements.lock`. `uv` optional |
| O5 | The proposed extra edges in §3.3 | Approve all three for `0001`. `HAS_CHUNK` waits for Phase 3 |

## 6. File-level plan: as built in Phase 1

These are the files actually delivered. Deviations from the original plan are marked †.

```
.gitignore · pyproject.toml · requirements.lock · .env.example · README.md
docker-compose.yml                       # falkordb v4.22.0 :56379 (AOF) · † falkordb-test :56390 (ephemeral) · postgres :55432
apps/api/app/config.py                   # settings, DSN guard (db must be 'graphathon'), hide_input_in_errors
apps/api/app/main.py                     # /healthz, /readyz
apps/api/app/db/postgres.py              # readiness, PostgresSaver.setup() wrapper, read-only status
apps/api/app/domain/actions.py           # canonical JSON, sha256 spec hash, approval validity
apps/api/app/graph/schema.py             # labels, props, enums, ALLOWED_EDGES (source of truth)
apps/api/app/graph/client.py             # connect, readiness wait, GraphUnavailable
apps/api/app/graph/repository.py         # tenant-scoped, allowlisted reads and writes
apps/api/app/graph/integrity.py          # inventory and integrity report
apps/api/app/graph/migrate.py            # runner: introspective, checksummed, locked, AOF rewrite on down
apps/api/app/graph/migrations/v0001_schema_v1.py   # † Python declarative spec, not .cypher (re-creation errors on this server)
apps/api/app/graph/queries/*.cypher      # † moved from graph/queries/ so the package ships them
apps/api/app/seeds/{novacommerce,decoy_acme,loader}.py  # † Python data through the validated repository, not raw .cypher
scripts/{probe_falkordb,migrate_graph,init_checkpointer,seed,reset_graph,inventory_graph}.py
scripts/backup_falkordb.sh · scripts/repro_falkordb_aof_crash.sh (†)
tests/                                   # 93 tests (unit, migrate/seed, scoping/relationships, golden path, approvals, infra)
docs/falkordb-capabilities.md · docs/schema/falkordb.md · docs/schema/postgres.md
```

`apps/web/` is not scaffolded until Phase 6.

## 7. Risks and rollback

| Risk | Mitigation / rollback |
|---|---|
| A legacy repo exists and greenfield work diverges from it | Step 0 is blocking |
| FalkorDB constraint, index, vector or temporal syntax differs in the pinned image | P2 probe gates `0001`. Unsupported features fall back as documented in §3.4 |
| Accidental writes to the host's Zoho databases on 5432 | Separate container on 55432, DSN guard, and no tooling defaults to 5432 |
| Manual DDL drifts the checkpoint schema | Only `PostgresSaver.setup()` touches it. Ops tables live in the separate `ops` schema |
| Partial failure between graph and Postgres writes | Idempotent `MERGE`, outbox and reconciliation. No claim of atomicity |
| The reset script runs against the wrong data | Typed tenant confirmation, a dev-only guard, never imported by the app |
| Docker and Podman both installed | Docs and scripts use `docker compose` only |
| **FalkorDB 4.22.x AOF-replay segfault after a unique constraint is dropped** (found in Phase 1) | Tests use the ephemeral `falkordb-test` service only. Nothing drops constraints on the dev server. `migrate --down` rewrites the AOF. Recovery runbook and repro script: `docs/schema/falkordb.md` |
| A destructive change (`down -v`, `GRAPH.DELETE`, `DROP DATABASE`) | Requires explicit approval each time. Nothing destructive has been run so far |

## 8. Sign-off

- [x] Step 0 answered: **B, greenfield**
- [x] §3 schema v1 approved as written
- [x] §5 O1–O5 decided: all recommendations accepted
- [x] Phase 4 LLM: local **Ollama** for development, behind a configurable provider. The stub LLM stays the default, and the provider changes at deploy time
- [x] Approved by: project owner (nithishkumar.srinivasan)  Date: 2026-10-18
