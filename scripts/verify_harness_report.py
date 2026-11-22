#!/usr/bin/env python3
"""CLI wrapper to verify harness report invariants (#781, #780)."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root is on sys.path so tests modules import cleanly
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.darnit.harness.verify_report import (  # noqa: E402
    is_llm_evaluated,
    main,
    verify_control_llm_judgment,
    verify_deterministic_parity,
    verify_harness_report,
)

__all__ = [
    "is_llm_evaluated",
    "main",
    "verify_control_llm_judgment",
    "verify_deterministic_parity",
    "verify_harness_report",
]

if __name__ == "__main__":
    sys.exit(main())
