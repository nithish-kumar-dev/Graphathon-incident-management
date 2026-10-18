"""Delete ONE tenant's nodes and edges from the app graph. Destructive, dev only.

Requires the tenant to be typed twice: --tenant nova --confirm nova.
Never imported by the application. Schema objects (indexes, constraints) are kept.

    .venv/bin/python scripts/reset_graph.py --tenant nova --confirm nova
"""

import argparse
import sys

import _bootstrap  # noqa: F401
from app.config import get_settings
from app.graph import client
from app.graph.schema import TENANT_PATTERN


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--confirm", required=True)
    args = ap.parse_args()
    s = get_settings()
    if not TENANT_PATTERN.match(args.tenant) or args.confirm != args.tenant:
        print("refusing: --confirm must repeat --tenant exactly", file=sys.stderr)
        return 2
    g = client.wait_until_ready(s.falkordb_url).select_graph(s.graph_name)
    n = g.ro_query("MATCH (n {tenant_id: $t}) RETURN count(n)", {"t": args.tenant}).result_set[0][0]
    g.query("MATCH (n {tenant_id: $t}) DETACH DELETE n", {"t": args.tenant})
    print(f"deleted {n} nodes of tenant {args.tenant!r} from graph {s.graph_name!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
