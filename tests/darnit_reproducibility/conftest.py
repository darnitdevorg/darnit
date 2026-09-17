"""Shared fixtures for the reproducibility plugin tests.

Feature 037. The `capture_deps_pinned` helper exists so that the SC-004 /
SC-005 baseline and the tests that assert against it agree on exactly what
"the handler's output" means -- including confidence, which the pre-existing
tests in test_handlers.py never asserted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from darnit.sieve.handler_registry import HandlerContext


def make_handler_ctx(repo: Path) -> HandlerContext:
    return HandlerContext(
        local_path=str(repo),
        owner="org",
        repo="repo",
        default_branch="main",
        control_id="RE-01.01",
        project_context={},
        gathered_evidence={},
        shared_cache={},
        dependency_results={},
    )


def capture_deps_pinned(repo: Path) -> dict[str, Any]:
    """Run repro_deps_pinned_handler and normalize its result for comparison.

    Imported lazily so this module stays importable regardless of which
    handler internals exist at any point during the feature's implementation.
    """
    from darnit_reproducibility.handlers import repro_deps_pinned_handler

    result = repro_deps_pinned_handler({}, make_handler_ctx(repo))
    return {
        "status": result.status.value,
        "message": result.message,
        "confidence": result.confidence,
        "evidence": result.evidence,
    }


@pytest.fixture
def lockfile_repo(tmp_path: Path) -> Path:
    """A repo judged by a lock file -- the path this feature must not touch."""
    (tmp_path / "uv.lock").write_text("lock content\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def no_deps_repo(tmp_path: Path) -> Path:
    """A repo with no dependency files at all."""
    return tmp_path
