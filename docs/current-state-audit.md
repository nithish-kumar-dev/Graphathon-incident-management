# Current-State Audit (Phase 0)

- **Date:** 2026-10-18 (first pass 14:25, re-run and corrected later the same day; see §7)
- **Audited path:** `/Users/nithish-23288/Projects/Graphathon`
- **Mode:** read-only. The only writes were these two files in `docs/` and throwaway wheel downloads in a session scratch directory outside the repo. No database writes, no containers started.

## 1. Verdict

**The repository is empty.** It has no source code, manifests, lockfiles, schemas, seeds, migrations, tests, or git history. The 13 legacy graph labels, the memory paths, the orchestration and the Postgres ownership described in the Phase 0 brief **were not found in this repo, anywhere under `~/Projects`, or by a name search of the home directory**. No FalkorDB instance is running or installed.

Every claim about a "legacy system" is therefore **unverified**. The 13 labels exist only as a list in the brief, so this plan treats them as the **target spec**, not as existing data. Nothing here may be read as describing a real legacy system.

> If the legacy codebase lives somewhere else (another path, an uncloned remote, or a different branch or machine), this audit must be re-run against it. That is Step 0 in `docs/refactor-plan.md`.

## 2. Evidence summary

The exact commands are in Appendix A.

| # | Check | Observed result |
|---|---|---|
| E1 | Repo root listing | Only `docs/`, which this audit created. The directory was created 2026-10-18 14:15 |
| E2 | `git status` | `fatal: not a git repository`: no branch, no history |
| E3 | File count, excluding `.git` / `node_modules` / venvs | 2 files: the two docs written by this audit |
| E4 | Grep `~/Projects` for `AgentMemory\|FalkorDB\|falkordb\|TimelineEvent\|ApprovalRecord` | No matches outside `Graphathon/docs` |
| E5 | `find ~ -maxdepth 5` for `*falkor*`, `*graphathon*`, `*incident*agent*`, `NovaCommerce*` | Only this repo and its Claude project folder |
| E6 | Sibling projects `Graph`, `langgraph`, `RAG`, `postgres-ha-lab`, … | Unrelated: tutorials and labs, no incident-graph code |
| E7 | TCP listeners on 6379/5432/8000/3000/5173/55432 | Only **Postgres.app on 127.0.0.1:5432 and [::1]:5432**. Nothing on 6379 |
| E8 | `redis-cli -p 6379 PING` | Connection refused. No FalkorDB or Redis |
| E9 | `docker ps -a`, `docker image ls` | Docker 29.2.1, Compose 5.5.1. Only stopped, unrelated containers (etcd, pg-node1..3, n8n, open-webui). **No FalkorDB image.** `postgres:15-bookworm` is already cached. Podman and podman-compose are also installed |
| E10 | Postgres server version | PostgreSQL 15.15 (Postgres.app, aarch64) |
| E11 | Non-template databases | `postgres, nithish-23288, accounts_sync_server, accountsyncdb, sasdb1, zohodirectory_onpremise_jbossdb, accountsdb, onezoho_jbossdb, sasdb, art_db` |
| E12 | Each DB searched in `information_schema.tables` for `checkpoint%`, `%incident%`, `execution_locks`, `idempotency_records`, `notification_outbox` | **No matches in any DB** |
| E13 | Interpreters | `python3` 3.14.6 (default). `python3.13` 3.13.2 (Homebrew). `python3.12` 3.12.5 (`/usr/local/bin`, python.org build: **pip fails SSL certificate verification**). Node 22.22.0, npm 10.9.4. `psql` client 9.5.19 (older than the server). redis-cli 8.0.1. `uv`, `poetry`, `pnpm` absent |
| E14 | Latest PyPI versions | falkordb 1.8.0 · langgraph 1.2.16 · langgraph-checkpoint-postgres 3.2.0 · fastapi 0.143.3 · pydantic 2.14.1 · psycopg 3.3.6 |
| E15 | `pip download --only-binary :all:` on Python 3.14 | **All resolved as wheels:** falkordb 1.8.0, langgraph 1.2.16, langgraph-checkpoint 4.3.0, langgraph-checkpoint-postgres 3.2.0, psycopg 3.3.6 + psycopg_binary cp314 arm64, psycopg_pool 3.3.3, pydantic_core 2.50.1 cp314, orjson/ormsgpack/xxhash cp314, redis 8.1.0, fastapi 0.143.3 |

## 3. Brief checklist results

| Brief item | Finding |
|---|---|
| Repo layout, branch/status, languages, versions, dependency management | None: no VCS and no manifests (E1–E3) |
| API entry points, frontend, deployment manifests | None (E3) |
| 13 legacy labels: properties, `id` vs named-ID keys, edges and directions | **Not found** (E3–E5, E7–E9). Properties, ID-key inconsistencies and edge directions **cannot be audited**. The only source is the label list in the brief |
| Orphan / duplicate checks | Not possible because no graph exists (E8–E9). The queries are specified in the refactor plan for Phase 1 |
| Existing seeds and migration scripts | None |
| **Memory read/write paths** (node properties, serialized JSON, checkpoint, separate AgentMemory) | **None exist.** No code reads or writes memory in any form. Nothing has been assumed |
| Orchestration (LangGraph or custom), coordinator responsibilities, overlap, parallelism, error handling | None. No LangGraph or custom agent code exists |
| HITL and notification behavior | None |
| Postgres table ownership; is the checkpoint schema library-managed? | No checkpoint or project tables exist in any local DB (E12), so there is nothing to recreate by accident. Hazard: the host Postgres holds unrelated databases (§5.1) |
| Security: secrets, tenant filters, mock vs real execution, egress, data compliance | No code to review, so no secrets are in the repo. See §5 for environment risks that the design must close |

## 4. Feature-to-evidence matrix

Allowed states: `implemented` · `partial` · `missing` · `unverified`.

- A feature is marked `implemented` only after the code and tests for it have been checked; none qualify.
- "Target phase" is the brief that will deliver the feature.

| Feature | State | Evidence | Target phase |
|---|---|---|---|
| 13 legacy labels in FalkorDB | missing here, unverified elsewhere | E3–E5, E8–E9 | 1 |
| Evidence and ApprovalRecord labels | missing | E3 | 1 |
| DocumentChunk and vector index | missing; FalkorDB vector support unverified | E9 | 3 (optional) |
| Stable `id` key with `tenant_id` / `env` / `source` on every node | missing | E3 | 1 |
| Graph indexes and unique constraints | missing; syntax unverified on any running version | E8–E9 | 1 |
| Graph migration runner (idempotent) | missing | E3 | 1 |
| NovaCommerce synthetic seed, idempotent | missing | E3 | 1 |
| Reset script with confirmation | missing | E3 | 1 |
| docker-compose: FalkorDB and Postgres, loopback-only ports, health checks | missing | E3, E9 | 1 |
| LangGraph Postgres checkpointer tables | missing | E12 | 1 / 4 |
| `execution_locks` / `idempotency_records` / `notification_outbox` | missing | E12 | 1 (only if needed) / 5 |
| FastAPI typed API and OpenAPI | missing | E3 | 2 |
| Alert ingest with time-window dedup | missing | E3 | 2 |
| Bounded read-only graph tools (8 named) | missing | E3 | 3 |
| Verified-memory model (`memory_type`, `verification_status`, `outcome`, provenance) | missing | E3 | 3 |
| LangGraph coordinator with parallel retrieval and fan-in barrier | missing | E3 | 4 |
| Investigator structured output and evidence safety gate | missing | E3 | 4 |
| HITL `interrupt` / resume and ApprovalRecord bound to action hash | missing | E3 | 5 |
| Restricted executor (simulation only) | missing | E3 | 5 |
| React/Vite dashboard | missing | E3 | 6 |
| Tests / CI | missing | E3 | all |

## 5. Environment observations and risks for later phases

1. **The host Postgres holds unrelated, real-looking Zoho databases** (`accountsdb`, `onezoho_jbossdb`, `sasdb`, …) on the default port 5432 (E7, E11).
   - The project must use **its own Postgres in Docker**, bound to `127.0.0.1:55432`, with a database named `graphathon`.
   - `PostgresSaver.setup()` must never run against port 5432 or any existing DB.
   - The app should refuse to start if the DSN does not name the `graphathon` database.
2. **The `psql` client is 9.5** and the server is 15.x. Basic queries work, but `\d` meta-commands may misbehave. Use `docker compose exec postgres psql` for the project DB.
3. **Python.** The default 3.14.6 resolves every core dependency as a binary wheel (E15), so the earlier "3.14 wheel gap" concern is **closed**. Remaining caveats:
   - Running LangGraph and psycopg on 3.14 has not been tested; that happens in Phase 1.
   - The python.org 3.12 has a broken certificate store (E13). Do not use it without running its *Install Certificates* step.
   - Homebrew 3.13.2 is a fallback.
4. **Container runtime.** Docker 29.2.1 with Compose 5.5.1 works (E9). Podman is also installed. Use the `docker compose` commands only, so the team does not end up with volumes split across two runtimes.
5. **No FalkorDB is available** (E8, E9). These capabilities are **unverified** and must stay optional until a probe against a pinned image confirms them:
   - range indexes, including multi-property indexes
   - full-text indexes
   - unique constraints (`GRAPH.CONSTRAINT`)
   - vector indexes and `db.idx.vector.queryNodes`
   - native temporal types
   - `shortestPath` and variable-length path limits
   - query timeouts
6. LangGraph APIs the design depends on, to be confirmed against the pinned lockfile in Phase 1 / Phase 4:
   - parallel branches with reducer-based fan-in
   - `interrupt()` with `Command(resume=…)`
   - `PostgresSaver.setup()` owning the `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` and `checkpoint_migrations` tables
7. **Security baseline.** Because there is no code yet, every control is greenfield:
   - no secrets in the repo; `.env.example` holds placeholders only
   - mandatory `tenant_id` / `env` filters in the repository layer
   - labels and relationship types taken from allowlists, never from user strings
   - `simulation` as the only executable mode
   - no outbound network calls except the configured LLM endpoint
   - synthetic data only, with no real PII

## 6. Gate status

**Not met.** The gate requires that the team can describe the current architecture accurately and agree on the first schema migration.

- **Current architecture:** the team can now describe it accurately. **There is no current architecture in this repo.**
- **First schema migration:** proposed in `docs/refactor-plan.md` §3, aligned with the Phase 1–5 briefs. It needs the team's answer to Step 0 and explicit sign-off.

## 7. Corrections made in the re-run

The first pass got these wrong; this version fixes them.

| First-pass claim | Correction |
|---|---|
| "Python 3.14 wheel availability unverified; pin 3.12 via uv" | 3.14 wheels were verified (E15). The python.org 3.12 has a broken SSL certificate store (E13). Recommend 3.14, with 3.13 as fallback; `uv` is optional |
| Docker was described only as "no containers" | Docker and Compose versions recorded; `postgres:15-bookworm` is cached; Podman is also present (E9) |
| Commands were given only in abridged form | Exact commands added in Appendix A |
| The draft schema in the refactor plan did not follow the Phase 1 edge list | The refactor plan §3 is rewritten. A diff against the draft is in §3.6 of that file |

## Appendix A: Exact commands run (all read-only)

```bash
cd /Users/nithish-23288/Projects/Graphathon
ls -la
git status
find . -type f -not -path '*/node_modules/*' -not -path '*/.venv/*' -not -path '*/venv/*' -not -path '*/.git/*' | wc -l
grep -rlI --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=venv --exclude-dir=.git \
  -E "AgentMemory|FalkorDB|falkordb|TimelineEvent|ApprovalRecord" ~/Projects
find ~ -maxdepth 5 \( -path ~/Library -o -path '*/node_modules' -o -path '*/.Trash' -o -path '*/.cache' \) -prune -o \
  \( -iname '*falkor*' -o -iname '*graphathon*' -o -iname '*incident*agent*' -o -iname 'NovaCommerce*' \) -print
lsof -nP -iTCP -sTCP:LISTEN | awk 'NR==1 || /:(6379|5432|8000|3000|5173|55432) /'
redis-cli -p 6379 PING
docker --version; docker compose version; docker ps -a --format '{{.Names}} | {{.Image}} | {{.Status}}'
docker image ls | grep -i -E 'falkor|redis|postgres'
command -v podman podman-compose docker-compose
psql -h localhost -d postgres -Atc "select version()"
for db in $(psql -h localhost -d postgres -Atc "select datname from pg_database where not datistemplate"); do
  psql -h localhost -d "$db" -Atc "select table_schema||'.'||table_name from information_schema.tables
    where table_name like 'checkpoint%' or table_name like '%incident%'
       or table_name in ('execution_locks','idempotency_records','notification_outbox')"
done
python3 --version; /usr/local/bin/python3.12 --version; /opt/homebrew/bin/python3.13 --version
node --version; npm --version; psql --version; redis-cli --version
for p in falkordb langgraph langgraph-checkpoint-postgres fastapi pydantic psycopg; do python3 -m pip index versions $p | head -1; done
# wheel resolution, downloaded to a session scratch dir (not the repo):
python3 -m pip download -q --only-binary :all: -d <scratch>/wheels-14 \
  falkordb langgraph langgraph-checkpoint-postgres "psycopg[binary]" psycopg-pool fastapi
/usr/local/bin/python3.12 -m pip download ...   # -> SSLCertVerificationError
```
