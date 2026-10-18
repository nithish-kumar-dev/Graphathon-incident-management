"""Print the hybrid retrieval bundle the investigator will receive (read-only).

    .venv/bin/python scripts/retrieve_context.py nova.inc.101 [--full]
"""

import argparse
import sys

import _bootstrap  # noqa: F401
from app.config import get_settings
from app.graph import client
from app.graph.repository import Scope, now_ms
from app.rag import embeddings
from app.rag.retrieval import retrieve
from app.tools.graph_tools import ToolContext


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("incident_id")
    ap.add_argument("--tenant", default="nova")
    ap.add_argument("--full", action="store_true", help="print the whole JSON bundle")
    args = ap.parse_args()
    s = get_settings()
    g = client.wait_until_ready(s.falkordb_url).select_graph(s.graph_name)
    ctx = ToolContext.read_only(g, Scope(args.tenant, s.default_env), now_ms=now_ms(),
                                timeout_ms=s.graph_query_timeout_ms)
    b = retrieve(ctx, args.incident_id, embedder=embeddings.from_settings(s),
                 allowed_classifications=s.allowed_classifications)
    if args.full:
        print(b.model_dump_json(indent=2))
        return 0
    print(f"{b.graph_context.incident.key}  steps: " + ", ".join(f"{k}={v.status}({v.candidates})"
                                                            for k, v in b.steps.items()))
    print(f"extracted: services={b.extracted.service_ids} terms={b.extracted.error_terms}")
    for p in b.graph_context.explanation_paths:
        print(f"path [{p.claim_type}] " + " | ".join(f"{h.from_id} -[{h.rel}]-> {h.to_id}" for h in p.hops))
    print("memories:")
    for x in b.memory_context.items:
        print(f"  {x.score:.3f} {x.id} {x.applicability} precedent={x.precedent} via={x.matched_by}")
        for r in x.rationale:
            print(f"        - {r}")
    print(f"  excluded: {b.memory_context.excluded}")
    print("knowledge:")
    for c in b.knowledge_context.items:
        print(f"  {c.score:.3f} {c.id} ({c.source_ref}) via={c.matched_by}")
        for r in c.rationale:
            print(f"        - {r}")
    print(f"  excluded: {b.knowledge_context.excluded}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
