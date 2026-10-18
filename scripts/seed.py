"""Seed a synthetic tenant (idempotent, MERGE-only). Never runs at app startup.

    .venv/bin/python scripts/seed.py            # NovaCommerce ("nova")
    .venv/bin/python scripts/seed.py --tenant acme
"""

import argparse
import sys

import _bootstrap  # noqa: F401
from app.config import get_settings
from app.graph import client, integrity
from app.seeds.loader import SEEDS, apply_seed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="nova", choices=sorted(SEEDS))
    args = ap.parse_args()
    s = get_settings()
    if args.tenant not in s.tenants:
        print(f"refusing: tenant {args.tenant!r} not in TENANT_ALLOWLIST", file=sys.stderr)
        return 2
    g = client.wait_until_ready(s.falkordb_url).select_graph(s.graph_name)
    before = integrity.run(g).label_counts
    nodes, edges = apply_seed(g, SEEDS[args.tenant])
    rep = integrity.run(g)
    print(f"seeded tenant={args.tenant}: {nodes} node specs, {edges} edge specs")
    print(f"node counts before={sum(before.values())} after={sum(rep.label_counts.values())}")
    print("integrity:", "ok" if rep.ok else rep.problems)
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
