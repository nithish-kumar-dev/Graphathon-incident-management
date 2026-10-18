"""Apply graph migrations (idempotent), or roll one back (dev only, explicit confirmation).

    .venv/bin/python scripts/migrate_graph.py
    .venv/bin/python scripts/migrate_graph.py --status
    .venv/bin/python scripts/migrate_graph.py --down 1 --confirm <graph name>
"""

import argparse
import sys

import _bootstrap  # noqa: F401
from app.config import get_settings
from app.graph import client, migrate


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--down", type=int)
    ap.add_argument("--confirm")
    args = ap.parse_args()
    s = get_settings()
    db = client.wait_until_ready(s.falkordb_url)
    g = db.select_graph(s.graph_name)
    if args.status:
        print(f"graph={s.graph_name} recorded={migrate.recorded(g)}")
        print(f"indexes={len(migrate.existing_indexes(g))} constraints={migrate.existing_constraints(g)}")
        return 0
    if args.down is not None:
        if args.confirm != s.graph_name:
            print(f"refusing: pass --confirm {s.graph_name} to drop migration {args.down} objects", file=sys.stderr)
            return 2
        print("dropped:", migrate.rollback(db, s.graph_name, args.down))
        return 0
    r = migrate.migrate(db, s.graph_name)
    print(f"graph={s.graph_name} applied={r.applied} skipped={r.skipped} created={len(r.created)} objects")
    return 0


if __name__ == "__main__":
    sys.exit(main())
