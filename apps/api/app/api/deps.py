"""Request-scoped dependencies: settings, clock, graph handle, principal, scoped repository, embedder."""

from __future__ import annotations

import threading
import time
from typing import Annotated

from falkordb import FalkorDB, Graph
from fastapi import Depends, Security
from fastapi.security import APIKeyHeader

from app.api.errors import Forbidden, Unauthenticated
from app.auth import DEMO_USERS, Principal
from app.config import Settings, get_settings
from app.graph import client
from app.graph.repository import GraphRepository, Scope
from app.rag import embeddings

SettingsDep = Annotated[Settings, Depends(get_settings)]

_demo_user_header = APIKeyHeader(
    name="X-Demo-User", auto_error=False, scheme_name="DemoUser",
    description="Fictional demo identity, NOT authentication. One of: " + ", ".join(sorted(DEMO_USERS)),
)

_clients: dict[str, FalkorDB] = {}
_clients_lock = threading.Lock()


def get_now_ms() -> int:
    return int(time.time() * 1000)


NowMs = Annotated[int, Depends(get_now_ms)]


def _falkordb(url: str) -> FalkorDB:
    """One client (connection pool) per URL. Not cached on failure, so recovery is automatic."""
    db = _clients.get(url)
    if db is None:
        with _clients_lock:
            db = _clients.get(url)
            if db is None:
                db = client.connect(url)  # raises GraphUnavailable -> 503
                _clients[url] = db
    return db


def get_graph(settings: SettingsDep) -> Graph:
    return _falkordb(settings.falkordb_url).select_graph(settings.graph_name)


GraphDep = Annotated[Graph, Depends(get_graph)]


def get_embedder(settings: SettingsDep) -> embeddings.Embedder | None:
    """None when EMBEDDING_PROVIDER=none. Overridden in tests. Retrieval degrades to graph + keyword
    when the provider is down, so this never fails the request."""
    return embeddings.from_settings(settings)


EmbedderDep = Annotated[embeddings.Embedder | None, Depends(get_embedder)]


def get_principal(settings: SettingsDep, user: str | None = Security(_demo_user_header)) -> Principal:
    if not user:
        raise Unauthenticated("missing X-Demo-User header (demo identity)")
    principal = DEMO_USERS.get(user)
    if principal is None:
        raise Unauthenticated("unknown demo user")
    if principal.tenant_id not in settings.tenants:
        raise Forbidden("tenant not enabled on this deployment")
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require(permission: str):
    def _check(principal: PrincipalDep) -> Principal:
        if not principal.can(permission):
            raise Forbidden(f"missing permission {permission}")
        return principal
    return _check


def get_repo(principal: PrincipalDep, graph: GraphDep,
             settings: SettingsDep) -> GraphRepository:
    return GraphRepository(graph, Scope(principal.tenant_id, principal.env), timeout_ms=settings.graph_query_timeout_ms)


RepoDep = Annotated[GraphRepository, Depends(get_repo)]
