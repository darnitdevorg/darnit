"""SC-004 / SC-005: paths this feature must not have touched.

The baseline in `baselines/deps_pinned_before.json` was captured from
unmodified code before implementation began. That ordering is the whole point:
a golden generated during implementation proves only that the code agrees with
itself. Feature 028 reached the same conclusion when it rejected snapshot
tooling whose update flag silently absorbs regressions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import capture_deps_pinned

BASELINE = json.loads((Path(__file__).parent / "baselines" / "deps_pinned_before.json").read_text(encoding="utf-8"))


@pytest.mark.unit
def test_lock_file_output_is_byte_identical(lockfile_repo: Path) -> None:
    """SC-004: status, message, confidence, and evidence all unchanged."""
    assert capture_deps_pinned(lockfile_repo) == BASELINE["lockfile_repo"]


@pytest.mark.unit
def test_no_dependency_files_output_is_byte_identical(no_deps_repo: Path) -> None:
    """SC-005."""
    assert capture_deps_pinned(no_deps_repo) == BASELINE["no_deps_repo"]
