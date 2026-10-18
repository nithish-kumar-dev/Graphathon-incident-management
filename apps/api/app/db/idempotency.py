"""Idempotency for the restricted executor's side effects (`ops.idempotency_records`).

Protocol per side effect, with key = "<action id>:<spec hash>" and request_hash = spec hash:
    begin()    -> NEW (go), DONE (already ran: replay `response`), BUSY (another runner holds a fresh lease),
                  CONFLICT (key reused for a different request), EXHAUSTED (attempt cap reached)
    complete() -> record the outcome (succeeded / failed) and the response to replay.
A stale `in_progress` row (lease expired: the runner died) is taken over and counts as another attempt.
Both stores share one pure decision function, so the in-memory store used in tests behaves like Postgres.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Literal, Protocol

from psycopg.types.json import Jsonb

LEASE_MS = 60_000
MAX_ATTEMPTS = 3
TTL_MS = 7 * 24 * 3600 * 1000

Decision = Literal["new", "done", "busy", "conflict", "exhausted"]


@dataclass(frozen=True)
class Begin:
    decision: Decision
    response: dict | None = None
    attempts: int = 0


class IdempotencyStore(Protocol):
    def begin(self, key: str, request_hash: str, *, now_ms: int) -> Begin: ...

    def complete(self, key: str, *, status: Literal["succeeded", "failed"], response: dict, now_ms: int) -> None: ...


def decide(row: dict | None, request_hash: str, now_ms: int) -> tuple[Begin, dict | None]:
    """(result, new row or None when the row is unchanged). `row` is the stored record or None."""
    if row is None:
        return Begin("new", attempts=1), {
            "status": "in_progress", "request_hash": request_hash, "response": None, "attempts": 1,
            "created_at_ms": now_ms, "updated_at_ms": now_ms, "expires_at_ms": now_ms + TTL_MS}
    if row["request_hash"] != request_hash:
        return Begin("conflict", attempts=row["attempts"]), None
    if row["status"] == "succeeded":
        return Begin("done", row["response"], row["attempts"]), None
    stale = row["status"] == "in_progress" and row["updated_at_ms"] + LEASE_MS <= now_ms
    if row["status"] == "in_progress" and not stale:
        return Begin("busy", attempts=row["attempts"]), None
    if row["attempts"] >= MAX_ATTEMPTS:     # a failed or abandoned row that used up its attempts
        failed = {**row, "status": "failed", "updated_at_ms": now_ms,
                  "response": row["response"] or {"result": "failed", "note": "attempt limit reached"}}
        return Begin("exhausted", failed["response"], row["attempts"]), failed
    return Begin("new", attempts=row["attempts"] + 1), {
        **row, "status": "in_progress", "attempts": row["attempts"] + 1, "updated_at_ms": now_ms}


class MemoryIdempotencyStore:
    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}
        self._lock = threading.Lock()

    def begin(self, key: str, request_hash: str, *, now_ms: int) -> Begin:
        with self._lock:
            result, new = decide(self._rows.get(key), request_hash, now_ms)
            if new is not None:
                self._rows[key] = new
            return result

    def complete(self, key: str, *, status: Literal["succeeded", "failed"], response: dict, now_ms: int) -> None:
        with self._lock:
            self._rows[key] = {**self._rows[key], "status": status, "response": response, "updated_at_ms": now_ms}

    def row(self, key: str) -> dict | None:
        return self._rows.get(key)


_COLS = "status, request_hash, response, attempts, created_at_ms, updated_at_ms, expires_at_ms"


class PostgresIdempotencyStore:
    """Needs the pool from `app.orchestrator.checkpoint.open_pool` and the `ops` migrations applied."""

    def __init__(self, pool) -> None:
        self.pool = pool

    def begin(self, key: str, request_hash: str, *, now_ms: int) -> Begin:
        with self.pool.connection() as conn, conn.transaction():
            inserted = conn.execute(
                "INSERT INTO ops.idempotency_records (key, status, request_hash, attempts, created_at_ms, "
                "updated_at_ms, expires_at_ms) VALUES (%s, 'in_progress', %s, 1, %s, %s, %s) "
                "ON CONFLICT (key) DO NOTHING", (key, request_hash, now_ms, now_ms, now_ms + TTL_MS)).rowcount
            if inserted:
                return Begin("new", attempts=1)
            row = conn.execute(f"SELECT {_COLS} FROM ops.idempotency_records WHERE key = %s FOR UPDATE",
                               (key,)).fetchone()
            result, new = decide(row, request_hash, now_ms)
            if new is not None:
                conn.execute("UPDATE ops.idempotency_records SET status = %s, response = %s, attempts = %s, "
                             "updated_at_ms = %s WHERE key = %s",
                             (new["status"], Jsonb(new["response"]) if new["response"] is not None else None,
                              new["attempts"], new["updated_at_ms"], key))
            return result

    def complete(self, key: str, *, status: Literal["succeeded", "failed"], response: dict, now_ms: int) -> None:
        with self.pool.connection() as conn:
            conn.execute("UPDATE ops.idempotency_records SET status = %s, response = %s, updated_at_ms = %s "
                         "WHERE key = %s", (status, Jsonb(response), now_ms, key))
