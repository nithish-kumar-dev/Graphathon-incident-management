"""Tenant-scoped, allowlist-checked access to the FalkorDB graph.

Rules:
- Labels, relationship types and property keys come only from app.graph.schema.
- Values are always passed as query parameters.
- Every query filters on tenant_id and env.
- Reads use GRAPH.RO_QUERY with a timeout.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from falkordb import Graph

from app.graph import schema
from app.graph.client import CONNECTION_ERRORS, GraphUnavailable, ReadOnlyViolation

QUERY_DIR = Path(__file__).parent / "queries"


@cache
def load_query(name: str) -> str:
    return (QUERY_DIR / f"{name}.cypher").read_text()


def now_ms() -> int:
    return int(time.time() * 1000)


class TenantConflict(schema.SchemaViolation):
    """The id already belongs to a node in another tenant or env."""


class EndpointNotFound(schema.SchemaViolation):
    """A relationship endpoint does not exist within the caller's tenant/env."""


@dataclass(frozen=True)
class Scope:
    tenant_id: str
    env: str

    def __post_init__(self) -> None:
        if not schema.TENANT_PATTERN.match(self.tenant_id):
            raise schema.SchemaViolation("invalid tenant_id")
        if self.env not in schema.ENV_VALUES:
            raise schema.SchemaViolation("invalid env")


class GraphRepository:
    def __init__(self, graph: Graph, scope: Scope, *, timeout_ms: int = 2000) -> None:
        self.graph = graph
        self.scope = scope
        self.timeout_ms = timeout_ms

    # ------------------------------------------------------------------ writes
    def merge_node(self, label: str, node_id: str, props: dict, *, at_ms: int | None = None) -> None:
        schema.check_label(label)
        schema.check_id(node_id)
        clean = {k: v for k, v in props.items() if v is not None}
        schema.check_props(label, clean)
        create_only: dict = {}
        if label == "AgentMemory":
            create_only = {k: clean.pop(k) for k in list(clean) if k in schema.MEMORY_VERIFICATION_PROPS}
            if create_only.get("verification_status") != "draft" or create_only.get("outcome") != "unknown" \
                    or {"validated_at_ms", "validation_method"} & set(create_only):
                raise schema.SchemaViolation("AgentMemory is created as draft/unknown; verification goes through "
                                             "app.services.memories")
        q = load_query("merge_node").replace("__LABEL__", label)
        rows = self._write(q, {"id": node_id, "props": clean, "create_only": create_only,
                               "now_ms": at_ms or now_ms(), "schema_version": schema.SCHEMA_VERSION})
        if not rows:
            raise TenantConflict(f"{label} {node_id!r} exists outside this tenant/env")

    def merge_edge(self, src_label: str, src_id: str, rel: str, dst_label: str, dst_id: str,
                   *, at_ms: int | None = None) -> None:
        q = self._edge_query("merge_edge", src_label, rel, dst_label)
        rows = self._write(q, {"src_id": schema.check_id(src_id), "dst_id": schema.check_id(dst_id),
                               "now_ms": at_ms or now_ms()})
        if not rows or rows[0][0] == 0:
            raise EndpointNotFound(f"({src_label} {src_id!r})-[:{rel}]->({dst_label} {dst_id!r}): "
                                   "endpoint missing in this tenant/env")

    def delete_edge(self, src_label: str, src_id: str, rel: str, dst_label: str, dst_id: str) -> int:
        q = self._edge_query("delete_edge", src_label, rel, dst_label)
        rows = self._write(q, {"src_id": schema.check_id(src_id), "dst_id": schema.check_id(dst_id)})
        return rows[0][0] if rows else 0

    def update_node(self, label: str, node_id: str, props: dict, *, at_ms: int | None = None) -> bool:
        clean = {k: v for k, v in props.items() if v is not None}
        schema.check_props(label, clean, partial=True)
        if label == "AgentMemory" and schema.MEMORY_VERIFICATION_PROPS & set(clean):
            raise schema.SchemaViolation("AgentMemory verification state changes only via app.services.memories")
        q = load_query("update_node").replace("__LABEL__", schema.check_label(label))
        return bool(self._write(q, {"id": schema.check_id(node_id), "props": clean, "now_ms": at_ms or now_ms()}))

    def set_embedding(self, label: str, node_id: str, vector: list[float], *, model: str, version: str,
                      dim: int, content_hash: str, at_ms: int | None = None) -> bool:
        if label not in schema.EMBEDDING_LABELS:
            raise schema.SchemaViolation(f"{label} does not carry embeddings")
        if len(vector) != dim:
            raise schema.SchemaViolation(f"embedding has {len(vector)} dimensions, expected {dim}")
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in vector):
            raise schema.SchemaViolation("embedding contains non-finite values")
        q = load_query("set_embedding").replace("__LABEL__", label)
        return bool(self._write(q, {"id": schema.check_id(node_id), "vector": [float(x) for x in vector],
                                    "model": model, "version": version, "dim": dim, "hash": content_hash,
                                    "now_ms": at_ms or now_ms()}))

    def set_memory_verification(self, memory_id: str, *, status: str, outcome: str, validated_at_ms: int | None,
                                method: str | None, at_ms: int) -> bool:
        """Internal: only app.services.memories may call this, after its rules pass."""
        schema.check_props("AgentMemory", {"verification_status": status, "outcome": outcome,
                                           **({"validation_method": method} if method else {})}, partial=True)
        return bool(self._write(load_query("set_memory_verification"), {
            "id": schema.check_id(memory_id), "status": status, "outcome": outcome,
            "validated_at_ms": validated_at_ms, "method": method, "now_ms": at_ms}))

    def delete_nodes(self, label: str, ids: list[str]) -> int:
        ids = sorted({schema.check_id(i) for i in ids})
        if not ids:
            return 0
        q = load_query("delete_nodes").replace("__LABEL__", schema.check_label(label))
        rows = self._write(q, {"ids": ids})
        return rows[0][0] if rows else 0

    def alert_dedup(self, *, fingerprint: str, source_ref: str, at_ms: int, window_ms: int, now: int,
                    max_refs: int = 50) -> dict | None:
        rows = self._write_dicts(load_query("alert_dedup"), {
            "fingerprint": fingerprint, "source_ref": source_ref, "at": at_ms, "lo": at_ms - window_ms,
            "hi": at_ms + window_ms, "max_refs": max_refs, "now_ms": now})
        return rows[0] if rows else None

    def merge_alert(self, alert_id: str, props: dict, *, at_ms: int) -> bool:
        schema.check_props("Alert", props)
        rows = self._write_dicts(load_query("merge_alert"), {
            "id": schema.check_id(alert_id), "props": props, "now_ms": at_ms,
            "schema_version": schema.SCHEMA_VERSION})
        if not rows:
            raise TenantConflict(f"Alert {alert_id!r} exists outside this tenant/env")
        return bool(rows[0]["created"])

    def attach_alert(self, alert_id: str, service_id: str, *, new_incident_id: str, incident_props: dict,
                     at_ms: int) -> dict:
        """Atomically attach an alert to its incident: existing link, else the open incident on the
        service, else a new incident (next INC-<n> key). Returns incident_id, incident_key, created."""
        if "key" in incident_props:
            raise schema.SchemaViolation("Incident.key is allocated by the server")
        schema.check_props("Incident", incident_props, partial=True)
        missing = schema.REQUIRED_PROPS["Incident"] - {"key"} - set(incident_props)
        if missing:
            raise schema.SchemaViolation(f"Incident: missing required properties {sorted(missing)}")
        rows = self._write_dicts(load_query("attach_alert"), {
            "alert_id": schema.check_id(alert_id), "service_id": schema.check_id(service_id),
            "new_incident_id": schema.check_id(new_incident_id), "incident_props": incident_props,
            "now_ms": at_ms, "schema_version": schema.SCHEMA_VERSION})
        if not rows:
            raise EndpointNotFound(f"alert {alert_id!r} or service {service_id!r} missing in this tenant/env")
        return rows[0]

    def claim_session(self, session_id: str, *, now_ms: int) -> bool:
        """Phase 4 worker claim: `queued` -> `running` in one write query. True only for the winner."""
        return bool(self._write(load_query("claim_session"), {"id": schema.check_id(session_id), "now_ms": now_ms}))

    # ------------------------------------------------------------------- reads
    def sessions_by_status(self, statuses: list[str], *, limit: int = 50) -> list[dict]:
        bad = set(statuses) - schema.ENUMS[("AgentSession", "status")]
        if bad:
            raise schema.SchemaViolation(f"unknown AgentSession status {sorted(bad)}")
        return self._read_dicts(load_query("sessions_by_status"), {"statuses": list(statuses),
                                                                    "limit": _bounded(limit)})

    def session_actions(self, session_id: str) -> list[dict]:
        rows = self._read_dicts(load_query("session_actions"), {"session_id": schema.check_id(session_id)})
        for row in rows:
            row["evidence"] = [e for e in row["evidence"] if e is not None]
        return rows

    def get_node(self, label: str, node_id: str) -> dict | None:
        q = load_query("get_node").replace("__LABEL__", schema.check_label(label))
        rows = self._read(q, {"id": schema.check_id(node_id)})
        return rows[0][0] if rows else None

    def get_nodes(self, label: str, ids: list[str]) -> dict[str, dict]:
        ids = sorted({schema.check_id(i) for i in ids})
        if not ids:
            return {}
        q = load_query("get_nodes").replace("__LABEL__", schema.check_label(label))
        return {row[0]: row[1] for row in self._read(q, {"ids": ids})}

    def list_nodes(self, label: str, *, limit: int = 500) -> list[dict]:
        q = load_query("list_nodes").replace("__LABEL__", schema.check_label(label))
        return [r[0] for r in self._read(q, {"limit": _bounded(limit, 1000)})]

    def fulltext_search(self, label: str, terms: list[str], *, k: int) -> list[dict]:
        """OR-query over sanitised terms. Returns [{id, score}] (higher score = better)."""
        clean = sorted({t for t in (re.sub(r"[^a-z0-9]", "", t.lower()) for t in terms) if len(t) >= 3})
        if not clean:
            return []
        return self._read_dicts(load_query("fulltext_search"), {
            "label": schema.check_label(label), "query": "|".join(clean[:20]), "k": _bounded(k, 100)})

    def vector_search(self, label: str, vector: list[float], *, k: int, model: str, version: str,
                      dim: int) -> list[dict]:
        """Returns [{id, distance}] (cosine distance, lower = closer)."""
        if label not in schema.EMBEDDING_LABELS:
            raise schema.SchemaViolation(f"{label} has no vector index")
        if len(vector) != dim:
            raise schema.SchemaViolation(f"query vector has {len(vector)} dimensions, expected {dim}")
        k = _bounded(k, 100)
        return self._read_dicts(load_query("vector_search"), {
            "label": label, "vector": [float(x) for x in vector], "k": k, "k_raw": k * 4, "model": model,
            "version": version, "dim": dim})

    def node_indexes(self) -> dict[tuple[str, str], dict]:
        """{(label, property): {"types": {...}, "options": {...}}} for node indexes on this graph."""
        out: dict[tuple[str, str], dict] = {}
        for label, types, options, entitytype in self._read(load_query("node_indexes"), {}, strip=False):
            if entitytype != "NODE":
                continue
            for prop, kinds in types.items():
                out[(label, prop)] = {"types": set(kinds), "options": dict((options or {}).get(prop) or {})}
        return out

    def memory_details(self, ids: list[str]) -> list[dict]:
        ids = sorted({schema.check_id(i) for i in ids})
        if not ids:
            return []
        rows = self._read_dicts(load_query("memory_details"), {"ids": ids})
        for row in rows:
            row["actions"] = [a for a in row["actions"] if a.get("id")]
        return rows

    def chunk_details(self, ids: list[str]) -> list[dict]:
        ids = sorted({schema.check_id(i) for i in ids})
        if not ids:
            return []
        rows = self._read_dicts(load_query("chunk_details"), {"ids": ids})
        for row in rows:
            row["decisions"] = [d for d in row["decisions"] if d.get("id")]
            row["relates_to"] = [x for x in row["relates_to"] if x.get("id")]
        return rows

    def neighbors(self, anchor_label: str, anchor_id: str, rel: str, other_label: str, *, outgoing: bool,
                  order_by: str = "id", descending: bool = False, limit: int = 100) -> list[dict]:
        """Nodes linked to the anchor by one allowlisted relationship, in either direction."""
        src, dst = (anchor_label, other_label) if outgoing else (other_label, anchor_label)
        q = self._edge_query("neighbors_out" if outgoing else "neighbors_in", src, rel, dst)
        q = q.replace("__ORDER__", schema.check_order_prop(other_label, order_by))
        q = q.replace("__DIR__", "DESC" if descending else "ASC")
        rows = self._read(q, {"id": schema.check_id(anchor_id), "limit": _bounded(limit)})
        return [r[0] for r in rows]

    def list_incidents(self, *, status: str | None, limit: int, offset: int) -> list[dict]:
        return self._read_dicts(load_query("list_incidents"),
                                {"status": status, "limit": _bounded(limit), "offset": max(0, int(offset))})

    def incident_evidence(self, incident_id: str, *, limit: int = 200) -> list[dict]:
        return self._read_dicts(load_query("incident_evidence"),
                                {"incident_id": schema.check_id(incident_id), "limit": _bounded(limit, 500)})

    def service_neighbourhood(self, service_id: str, *, upstream: bool, depth: int, limit: int) -> list[dict]:
        if depth < 1:
            raise schema.SchemaViolation("depth must be at least 1")
        name = "service_dependents" if upstream else "service_dependencies"
        q = load_query(name).replace("__DEPTH__", str(schema.check_depth(depth)))
        return self._read_dicts(q, {"service_id": schema.check_id(service_id), "limit": _bounded(limit)})

    def service_owners(self, service_id: str) -> list[dict]:
        rows = self._read_dicts(load_query("service_owners"), {"service_id": schema.check_id(service_id)})
        for row in rows:
            row["members"] = [m for m in row["members"] if m.get("id")]
        return rows

    def service_decisions(self, service_id: str) -> list[dict]:
        rows = self._read_dicts(load_query("service_decisions"), {"service_id": schema.check_id(service_id)})
        for row in rows:
            row["documents"] = [d for d in row["documents"] if d.get("id")]
        return rows

    def incident_memories(self, incident_id: str, *, include_unverified: bool, limit: int) -> list[dict]:
        return self._read_dicts(load_query("incident_memories"), {
            "incident_id": schema.check_id(incident_id), "include_unverified": bool(include_unverified),
            "limit": _bounded(limit)})

    def rollback_candidates(self, incident_id: str, *, depth: int = schema.MAX_TRAVERSAL_DEPTH,
                            at_ms: int | None = None) -> list[dict]:
        q = load_query("rollback_candidates").replace("__DEPTH__", str(schema.check_depth(depth)))
        return self._read_dicts(q, {"incident_id": schema.check_id(incident_id), "now_ms": at_ms or now_ms()})

    def valid_approvals(self, action_id: str, *, at_ms: int | None = None) -> list[dict]:
        return self._read_dicts(load_query("valid_approvals"),
                                {"action_id": schema.check_id(action_id), "now_ms": at_ms or now_ms()})

    def action_versions(self, proposal_id: str) -> list[dict]:
        rows = self._read_dicts(load_query("action_versions"), {"proposal_id": schema.check_id(proposal_id)})
        for row in rows:
            row["reviews"] = [r for r in row["reviews"] if r is not None]
        return rows

    # --------------------------------------------------------------- internals
    def _edge_query(self, name: str, src: str, rel: str, dst: str) -> str:
        schema.check_edge(src, rel, dst)
        return load_query(name).replace("__SRC__", src).replace("__REL__", rel).replace("__DST__", dst)

    def _params(self, params: dict) -> dict:
        return {**params, "tenant_id": self.scope.tenant_id, "env": self.scope.env}

    def _write(self, q: str, params: dict) -> list:
        try:
            return self.graph.query(q, self._params(params), timeout=self.timeout_ms).result_set
        except ReadOnlyViolation:
            raise
        except CONNECTION_ERRORS as exc:
            raise GraphUnavailable("graph database unavailable") from exc

    def _read(self, q: str, params: dict, *, strip: bool = True) -> list:
        try:
            rows = self.graph.ro_query(q, self._params(params), timeout=self.timeout_ms).result_set
        except CONNECTION_ERRORS as exc:
            raise GraphUnavailable("graph database unavailable") from exc
        # strip=False only for index metadata, whose dicts are keyed by property name ("embedding").
        return [[_strip_vectors(v) for v in row] for row in rows] if strip else rows

    def _read_dicts(self, q: str, params: dict) -> list[dict]:
        try:
            res = self.graph.ro_query(q, self._params(params), timeout=self.timeout_ms)
        except CONNECTION_ERRORS as exc:
            raise GraphUnavailable("graph database unavailable") from exc
        return _as_dicts(res)

    def _write_dicts(self, q: str, params: dict) -> list[dict]:
        try:
            res = self.graph.query(q, self._params(params), timeout=self.timeout_ms)
        except ReadOnlyViolation:
            raise
        except CONNECTION_ERRORS as exc:
            raise GraphUnavailable("graph database unavailable") from exc
        return _as_dicts(res)


def _bounded(limit: int, ceiling: int = 200) -> int:
    return max(1, min(int(limit), ceiling))


def _as_dicts(res) -> list[dict]:
    cols = [h[1] if isinstance(h, (list, tuple)) else h for h in res.header]
    cols = [c.decode() if isinstance(c, bytes) else c for c in cols]
    return [dict(zip(cols, [_strip_vectors(v) for v in row], strict=True)) for row in res.result_set]


def _strip_vectors(value):
    """Embeddings never leave the repository (768 floats per node; not useful to callers)."""
    if isinstance(value, dict) and "embedding" in value:
        return {k: v for k, v in value.items() if k != "embedding"}
    return value
