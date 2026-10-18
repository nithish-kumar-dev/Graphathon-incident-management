"""Apply a seed module through the validated repository: MERGE-only and idempotent."""

from __future__ import annotations

from types import ModuleType

from falkordb import Graph

from app.graph.repository import GraphRepository, Scope
from app.seeds import decoy_acme, novacommerce
from app.services import memories

SEEDS: dict[str, ModuleType] = {"nova": novacommerce, "acme": decoy_acme}


def apply_seed(graph: Graph, seed: ModuleType) -> tuple[int, int]:
    repo = GraphRepository(graph, Scope(seed.TENANT, seed.ENV))
    for label, node_id, props in seed.NODES:
        repo.merge_node(label, node_id, props, at_ms=seed.SEED_AT_MS)
    for src_label, src_id, rel, dst_label, dst_id in seed.EDGES:
        repo.merge_edge(src_label, src_id, rel, dst_label, dst_id, at_ms=seed.SEED_AT_MS)
    for memory_id, responder_id, outcome, validated_at in getattr(seed, "VALIDATIONS", []):
        memories.validate_by_human(repo, memory_id, responder_id=responder_id, outcome=outcome, now_ms=validated_at)
    return len(seed.NODES), len(seed.EDGES)
