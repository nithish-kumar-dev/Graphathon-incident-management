"""Shared CLI setup: put apps/api on sys.path and load settings from the repo root .env."""

import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
os.chdir(ROOT)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
