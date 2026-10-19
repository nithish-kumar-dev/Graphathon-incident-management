"""Prepare the graph when the API starts, so a fresh deployment (e.g. a cold Render instance) has data.

Controlled by STARTUP_DATA:
    none   do nothing (default; local dev runs the scripts by hand)
    seed   migrate_graph + seed + index_documents. Idempotent, keeps data created since.
    reset  as `seed`, but first deletes every node of each seeded tenant (scripts/reset_graph.py).
           Investigations, actions and memories created since the last start are lost.

Only tenants that are both in TENANT_ALLOWLIST and have a seed module are touched. Reset uses DETACH DELETE
and never drops a constraint or the graph itself (docs/schema/falkordb.md, "Known server issue").
"""

from __future__ import annotations

import logging
import time

from app.config import Settings
from app.graph import client, integrity, migrate
from app.graph.repository import GraphRepository, Scope, now_ms
from app.rag import embeddings, indexer
from app.seeds.loader import SEEDS, apply_seed

log = logging.getLogger("app.startup")


def prepare(settings: Settings) -> None:
    mode = settings.startup_data
    if mode == "none":
        return
    started = time.monotonic()
    db = client.wait_until_ready(settings.falkordb_url)
    r = migrate.migrate(db, settings.graph_name)
    log.info("startup data: graph=%s mode=%s migrations applied=%s skipped=%s",
             settings.graph_name, mode, r.applied, r.skipped)
    g = db.select_graph(settings.graph_name)
    for tenant in sorted(settings.tenants & SEEDS.keys()):
        seed = SEEDS[tenant]
        if mode == "reset":
            deleted = g.query("MATCH (n {tenant_id: $t}) DETACH DELETE n", {"t": tenant}).nodes_deleted
            log.info("startup data: deleted %d nodes of tenant %s", deleted, tenant)
        nodes, edges = apply_seed(g, seed)
        repo = GraphRepository(g, Scope(seed.TENANT, seed.ENV), timeout_ms=10_000)
        rep = indexer.index_all(repo, embeddings.from_settings(settings),
                                allowed_classifications=settings.allowed_classifications, now_ms=now_ms())
        log.info("startup data: seeded tenant %s (%d node specs, %d edge specs), indexed %d documents, "
                 "%d chunks, %d embedded", tenant, nodes, edges, rep.documents_indexed, rep.chunks_written,
                 rep.embedded)
        if rep.embedding_error:
            log.warning("startup data: embeddings skipped for %s (keyword retrieval still works): %s",
                        tenant, rep.embedding_error)
    report = integrity.run(g, embedding_dim=settings.embedding_dim)
    if not report.ok:
        log.warning("startup data: integrity problems: %s", report.problems)
    log.info("startup data: done in %.1fs", time.monotonic() - started)
