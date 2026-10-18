"""The project's own Postgres tables: schema `ops`, created by numbered SQL migrations.

This is separate from the LangGraph checkpoint tables (owned by the library, never touched here). A migration
file is `NNNN_name.sql`; applied versions are recorded in `ops.schema_migrations`, and an applied file is never
edited. `apply_migrations` is idempotent and safe to call concurrently (an advisory lock serialises runners).
"""

from __future__ import annotations

from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "ops_migrations"
_LOCK_KEY = 7_265_120_001   # arbitrary constant; one advisory lock for the ops migrator


def migration_files() -> list[tuple[int, str, str]]:
    out = []
    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        version, _, name = path.stem.partition("_")
        out.append((int(version), name, path.read_text()))
    return out


def apply_migrations(pool) -> list[int]:
    """Apply pending migrations in order. Returns the versions applied by this call."""
    applied: list[int] = []
    with pool.connection() as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
        conn.execute("CREATE SCHEMA IF NOT EXISTS ops")
        conn.execute("CREATE TABLE IF NOT EXISTS ops.schema_migrations ("
                     "version integer PRIMARY KEY, name text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())")
        done = {row["version"] for row in conn.execute("SELECT version FROM ops.schema_migrations")}
        for version, name, sql in migration_files():
            if version in done:
                continue
            conn.execute(sql, prepare=False)   # a file holds several statements; never a prepared one
            conn.execute("INSERT INTO ops.schema_migrations (version, name) VALUES (%s, %s)", (version, name))
            applied.append(version)
    return applied
