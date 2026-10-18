"""Read-only, whole-graph integrity inventory (orphans, duplicates, schema drift).

Runs across all tenants on purpose: it is an operator check, never exposed through the API.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from falkordb import Graph

from app.graph import schema
from app.graph.repository import load_query


@dataclass
class IntegrityReport:
    label_counts: dict[str, int] = field(default_factory=dict)
    edge_triples: list[tuple[str, str, str, int]] = field(default_factory=list)
    unknown_labels: list[str] = field(default_factory=list)
    invalid_triples: list[tuple[str, str, str, int]] = field(default_factory=list)
    orphans: list[tuple[str, str]] = field(default_factory=list)
    duplicates: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    missing_scope: list[tuple[str, str]] = field(default_factory=list)
    cross_tenant_edges: list[tuple[str, str, str]] = field(default_factory=list)
    unvalidated_verified_memory: list[str] = field(default_factory=list)
    evidence_without_source: list[str] = field(default_factory=list)
    bad_embeddings: list[tuple[str, str]] = field(default_factory=list)

    @property
    def problems(self) -> dict[str, object]:
        checks = {
            "unknown_labels": self.unknown_labels,
            "invalid_triples": self.invalid_triples,
            "orphans": self.orphans,
            "duplicates": self.duplicates,
            "missing_scope": self.missing_scope,
            "cross_tenant_edges": self.cross_tenant_edges,
            "unvalidated_verified_memory": self.unvalidated_verified_memory,
            "evidence_without_source": self.evidence_without_source,
            "bad_embeddings": self.bad_embeddings,
        }
        return {k: v for k, v in checks.items() if v}

    @property
    def ok(self) -> bool:
        return not self.problems


def run(graph: Graph, *, timeout_ms: int = 10_000, embedding_dim: int = 768) -> IntegrityReport:
    def rows(name: str, label: str | None = None, params: dict | None = None) -> list[list]:
        q = load_query(name)
        if label is not None:
            q = q.replace("__LABEL__", label)
        return graph.ro_query(q, params, timeout=timeout_ms).result_set

    rep = IntegrityReport()
    rep.label_counts = {label: n for label, n in rows("integrity_label_counts")}
    rep.unknown_labels = sorted(set(rep.label_counts) - schema.LABELS - {schema.MIGRATION_LABEL})
    rep.edge_triples = [tuple(r) for r in rows("integrity_edge_triples")]
    rep.invalid_triples = [t for t in rep.edge_triples if t[:3] not in schema.ALLOWED_EDGES]
    rep.orphans = [tuple(r) for r in rows("integrity_orphans")]
    for label in sorted(schema.LABELS | {schema.MIGRATION_LABEL}):
        dups = [tuple(r) for r in rows("integrity_duplicates", label)]
        if dups:
            rep.duplicates[label] = dups
    rep.missing_scope = [tuple(r) for r in rows("integrity_missing_scope")]
    rep.cross_tenant_edges = [tuple(r) for r in rows("integrity_cross_tenant_edges")]
    rep.unvalidated_verified_memory = [r[0] for r in rows("integrity_unvalidated_verified_memory")]
    rep.evidence_without_source = [r[0] for r in rows("integrity_evidence_without_source")]
    rep.bad_embeddings = [tuple(r) for r in rows("integrity_bad_embeddings", params={"dim": embedding_dim})]
    return rep
