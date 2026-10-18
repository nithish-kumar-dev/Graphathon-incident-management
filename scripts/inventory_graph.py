"""Read-only inventory of the app graph: counts, edge triples, integrity problems.

    .venv/bin/python scripts/inventory_graph.py
"""

import sys

import _bootstrap  # noqa: F401
from app.config import get_settings
from app.graph import client, integrity


def main() -> int:
    s = get_settings()
    rep = integrity.run(client.wait_until_ready(s.falkordb_url).select_graph(s.graph_name))
    print(f"graph={s.graph_name}")
    for label, n in rep.label_counts.items():
        print(f"  {label:<16}{n:>5}")
    print("edges:")
    for src, rel, dst, n in rep.edge_triples:
        print(f"  ({src})-[:{rel}]->({dst}) x{n}")
    print("integrity:", "ok" if rep.ok else rep.problems)
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
