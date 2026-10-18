"""FalkorDB connection handling: readiness wait and clean failure on outage."""

from __future__ import annotations

import logging
import time

from falkordb import FalkorDB, Graph
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

log = logging.getLogger(__name__)

CONNECTION_ERRORS = (RedisConnectionError, RedisTimeoutError, ConnectionRefusedError, OSError)


class GraphUnavailable(RuntimeError):
    """FalkorDB cannot be reached. The message never includes connection details."""


class ReadOnlyViolation(PermissionError):
    """A write was attempted through a read-only graph handle. PermissionError is an OSError, so the
    repository re-raises it explicitly instead of reporting it as an outage (CONNECTION_ERRORS)."""


def connect(url: str, *, socket_timeout: float = 5.0) -> FalkorDB:
    """FalkorDB.from_url talks to the server immediately, so an outage surfaces here."""
    try:
        return FalkorDB.from_url(url, socket_timeout=socket_timeout, socket_connect_timeout=3.0)
    except CONNECTION_ERRORS as exc:
        raise GraphUnavailable("graph database unavailable") from exc


def ping(db: FalkorDB) -> bool:
    try:
        return bool(db.connection.ping())
    except CONNECTION_ERRORS:
        return False


def ping_url(url: str, *, socket_timeout: float = 2.0) -> bool:
    try:
        return ping(connect(url, socket_timeout=socket_timeout))
    except GraphUnavailable:
        return False


def wait_until_ready(url: str, *, timeout_s: float = 30.0, interval_s: float = 1.0) -> FalkorDB:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            db = connect(url)
            if ping(db):
                return db
        except GraphUnavailable:
            pass
        if time.monotonic() >= deadline:
            raise GraphUnavailable("FalkorDB did not become ready in time")
        log.info("waiting for FalkorDB")
        time.sleep(interval_s)


def select_graph(db: FalkorDB, name: str) -> Graph:
    return db.select_graph(name)
