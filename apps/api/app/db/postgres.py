"""PostgreSQL: readiness and LangGraph checkpointer bootstrap.

The checkpoint tables (checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_migrations)
are owned by the installed langgraph-checkpoint-postgres package and created only by its own
PostgresSaver.setup(). This project never writes DDL for them.
"""

from __future__ import annotations

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver

from app.config import check_postgres_dsn

CHECKPOINT_TABLES = ("checkpoint_migrations", "checkpoints", "checkpoint_blobs", "checkpoint_writes")


class PostgresUnavailable(RuntimeError):
    """Postgres cannot be reached. The message never includes the DSN."""


def ping(dsn: str, *, timeout_s: int = 3) -> bool:
    try:
        with psycopg.connect(dsn, connect_timeout=timeout_s) as conn:
            conn.execute("SELECT 1")
        return True
    except psycopg.Error:
        return False


def init_checkpointer(dsn: str) -> dict[str, object]:
    check_postgres_dsn(dsn)
    try:
        with PostgresSaver.from_conn_string(dsn) as saver:
            saver.setup()
            expected_versions = len(saver.MIGRATIONS)
        return {**checkpoint_status(dsn), "expected_versions": expected_versions}
    except psycopg.OperationalError as exc:
        raise PostgresUnavailable("postgres unavailable") from exc


def checkpoint_status(dsn: str) -> dict[str, object]:
    check_postgres_dsn(dsn)
    with psycopg.connect(dsn, connect_timeout=3) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT table_schema || '.' || table_name FROM information_schema.tables "
            "WHERE table_name = ANY(%s) ORDER BY 1", (list(CHECKPOINT_TABLES),))]
        versions = 0
        if "public.checkpoint_migrations" in tables:
            versions = conn.execute("SELECT count(*) FROM checkpoint_migrations").fetchone()[0]
    return {"tables": tables, "applied_versions": versions}
