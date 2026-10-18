# PostgreSQL

Postgres holds **only** LangGraph's durable execution state, plus (later) a few operational tables. Incidents, actions, approvals and memories live in FalkorDB (`falkordb.md`).

## Instance

| | |
|---|---|
| Server | `postgres:15-bookworm` (15.18) in docker compose, `127.0.0.1:55432`, volume `pg_data` |
| Database | `graphathon`, the only database this project may touch |
| DSN guard | `app.config.check_postgres_dsn` rejects any DSN whose database is not `graphathon`. Validation errors never echo the DSN (`hide_input_in_errors`), so the password cannot leak into logs |
| Never use | Host Postgres.app on `:5432`, which holds unrelated databases (`docs/current-state-audit.md` §5.1) |

## Checkpoint tables: owned by `langgraph-checkpoint-postgres` 3.2.0

These tables are created and upgraded **only** by the installed library's `PostgresSaver.setup()`, via `scripts/init_checkpointer.py` or `app.db.postgres.init_checkpointer()`. No project SQL creates, alters, normalizes or drops them. Upgrading the library and re-running `setup()` is the only supported migration path, and `setup()` is idempotent (test: `test_checkpointer_setup_is_library_owned_and_idempotent`).

Introspected on 2026-10-18, read-only:

| Table (schema `public`) | Columns | Indexes |
|---|---|---|
| `checkpoint_migrations` | v integer | pkey |
| `checkpoints` | thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint jsonb, metadata jsonb | pkey, thread_id_idx |
| `checkpoint_blobs` | thread_id, checkpoint_ns, channel, version, type, blob bytea | pkey, thread_id_idx |
| `checkpoint_writes` | thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob bytea, task_path | pkey, thread_id_idx |

`checkpoint_migrations` holds versions `{0..9}`, which is all 10 of the library's migrations.

`AgentSession.thread_id` in the graph is the LangGraph `thread_id`. Phase 4 resumes a run with that same ID.

## Operational tables

Following refactor-plan §3.5, these are added only when a phase needs them. They go in a separate `ops` schema with numbered project migrations (`apps/api/app/db/ops_migrations/NNNN_*.sql`, applied by `scripts/migrate_postgres.py` or when the worker starts, under an advisory lock and recorded in `ops.schema_migrations`), so they never mix with the library's tables in `public`. Never edit an applied migration; add a new one.

`ops.idempotency_records` exists (migration 0001). The other two are still planned.

| Table | When | Shape (planned) |
|---|---|---|
| `ops.idempotency_records` (done) | Phase 5 executor | `key text primary key` (`<action id>:<spec hash>`), `status` (`in_progress`/`succeeded`/`failed`), `request_hash`, `response jsonb`, `attempts`, `created_at_ms`, `updated_at_ms`, `expires_at_ms` (epoch ms); index on `expires_at_ms`. 60 s lease, 3 attempts, 7 day TTL (`app/db/idempotency.py`) |
| `ops.notification_outbox` | Phase 5, only if `notify_channel` exists | `id`, `dedup_key unique`, `payload jsonb`, `status` (pending/sent/failed), `attempts`, `next_attempt_at` (indexed), `created_at` |
| `ops.execution_locks` | Only if concurrent executor runs become possible | `resource text primary key`, `holder`, `expires_at` |

## Cross-database consistency

FalkorDB and Postgres are **not** atomic with each other, and nothing in this project claims they are.

- **Graph writes are idempotent** (`MERGE` on a globally unique `id`), so a retried step does not duplicate nodes.
- **Side effects come after the graph write.** In Phase 5, a side effect (a simulated execution or a notification) is recorded in an outbox or idempotency row keyed by action ID and spec hash, then performed. A reconciler re-drives pending rows and checks graph state before acting.
- **Checkpoints can run ahead of the graph.** A LangGraph checkpoint may be newer than the graph if the process dies between the two writes. Nodes after the interrupt must therefore re-read graph state, and must not trust state carried in the checkpoint.
