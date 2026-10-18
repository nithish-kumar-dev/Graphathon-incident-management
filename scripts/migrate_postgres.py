"""Apply the project's own Postgres migrations (schema `ops`, e.g. `ops.idempotency_records`).

    .venv/bin/python scripts/migrate_postgres.py

Idempotent. The LangGraph checkpoint tables are separate: scripts/init_checkpointer.py. The API worker applies the
same migrations when it starts, so running this by hand is only needed for a standalone setup or inspection.
"""

import sys

import _bootstrap  # noqa: F401
from app.config import get_settings
from app.db.ops import apply_migrations, migration_files
from app.orchestrator.checkpoint import open_pool


def main() -> int:
    pool = open_pool(get_settings().postgres_dsn.get_secret_value(), max_size=2)
    try:
        applied = apply_migrations(pool)
    finally:
        pool.close()
    print(f"available: {[v for v, _, _ in migration_files()]}")
    print(f"applied now: {applied or 'none (already up to date)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
