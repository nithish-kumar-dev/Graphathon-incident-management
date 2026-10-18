"""Run the Phase 4 orchestrator worker standalone (instead of inside the API process).

    .venv/bin/python scripts/run_worker.py [--workers 2]

Claims queued investigations atomically, runs them (LangGraph + Postgres checkpoints) and, on start,
resumes sessions left `running` by a previous process. Ctrl-C stops it cleanly. Run only ONE worker per
graph: set ORCHESTRATOR_ENABLED=false for the API when this script is used.
"""

import argparse
import signal
import sys
import threading

import _bootstrap  # noqa: F401
from app.api.logging import configure_logging
from app.config import get_settings
from app.orchestrator.runner import Worker


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workers", type=int, default=2, help="concurrent investigation runs (1-8)")
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    worker = Worker(settings, max_workers=max(1, min(args.workers, 8)))
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    worker.start()
    stop.wait()
    worker.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
