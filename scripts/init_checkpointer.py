"""Create or upgrade the LangGraph checkpoint tables using the installed library's own setup().

    .venv/bin/python scripts/init_checkpointer.py
"""

import sys

import _bootstrap  # noqa: F401
from app.config import get_settings
from app.db import postgres


def main() -> int:
    dsn = get_settings().postgres_dsn.get_secret_value()
    before = postgres.checkpoint_status(dsn)
    after = postgres.init_checkpointer(dsn)
    print(f"before: {before}")
    print(f"after:  {after}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
