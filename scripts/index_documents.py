"""Chunk + embed authorised documents and memory summaries for a tenant (idempotent, incremental).

    .venv/bin/python scripts/index_documents.py              # tenant nova, EMBEDDING_PROVIDER from .env
    .venv/bin/python scripts/index_documents.py --no-embed   # chunks only (keyword retrieval still works)
"""

import argparse
import dataclasses
import json
import sys

import _bootstrap  # noqa: F401
from app.config import get_settings
from app.graph import client
from app.graph.repository import GraphRepository, Scope, now_ms
from app.rag import embeddings, indexer


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="nova")
    ap.add_argument("--env", default=None)
    ap.add_argument("--no-embed", action="store_true")
    args = ap.parse_args()
    s = get_settings()
    if args.tenant not in s.tenants:
        print(f"refusing: tenant {args.tenant!r} not in TENANT_ALLOWLIST", file=sys.stderr)
        return 2
    g = client.wait_until_ready(s.falkordb_url).select_graph(s.graph_name)
    repo = GraphRepository(g, Scope(args.tenant, args.env or s.default_env), timeout_ms=10_000)
    embedder = None if args.no_embed else embeddings.from_settings(s)
    rep = indexer.index_all(repo, embedder, allowed_classifications=s.allowed_classifications, now_ms=now_ms())
    print(json.dumps(dataclasses.asdict(rep), indent=2))
    return 0 if rep.embedding_error is None else 1


if __name__ == "__main__":
    sys.exit(main())
