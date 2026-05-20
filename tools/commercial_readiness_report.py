#!/usr/bin/env python3
"""Generate a local commercial readiness report for Reverie Studio."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils.commercial_readiness import main


if __name__ == "__main__":
    raise SystemExit(main())
