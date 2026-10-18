"""The LangGraph checkpointer: the installed PostgresSaver on the project DSN (guarded).

The tables belong to langgraph-checkpoint-postgres and are created only by its own `setup()`
(scripts/init_checkpointer.py, or `setup=True` here). This module never runs DDL of its own.
"""

from __future__ import annotations

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import check_postgres_dsn


def open_pool(dsn: str, *, max_size: int = 4) -> ConnectionPool:
    """A small pool with the connection settings PostgresSaver requires. Raises ValueError for a DSN that
    does not target the project database, before any connection is made."""
    check_postgres_dsn(dsn)
    return ConnectionPool(dsn, min_size=1, max_size=max_size, open=True, timeout=10,
                          kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                          check=ConnectionPool.check_connection)


def make_saver(pool: ConnectionPool, *, setup: bool = False) -> PostgresSaver:
    saver = PostgresSaver(pool)
    if setup:
        saver.setup()   # the library's own idempotent migrations; no project DDL
    return saver
