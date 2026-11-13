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
    from darnit_amber.handlers import repro_deps_pinned_handler

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


def repro_ctx(repo: Path, dependency_results: dict[str, str] | None = None) -> HandlerContext:
    """HandlerContext for a reproducibility handler under test (feature 038).

    `dependency_results` carries prior control verdicts. RE-02.01's Nix strong
    signal is gated on `dependency_results["RE-01.02"] == "PASS"`, so exercising
    the FR-010 propagation means setting it here.
    """
    return HandlerContext(
        local_path=str(repo),
        owner="org",
        repo="repo",
        default_branch="main",
        control_id="RE-TEST",
        project_context={},
        gathered_evidence={},
        shared_cache={},
        dependency_results=dependency_results or {},
    )


# --- run bundles (test_run_bundle, and the identity/publish and store tests that build on it) ---


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A clean git checkout with one committed results file: the precomputed-results case."""
    import subprocess

    r = tmp_path / "artifact"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    (r / "results").mkdir()
    (r / "results" / "table.txt").write_text("speedup: 2.4\n")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    subprocess.run(["git", "-C", str(r), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(r), "commit", "-q", "-m", "init"], check=True, env={**env, "PATH": "/usr/bin:/bin"}
    )
    return r


@pytest.fixture
def no_signing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """``execute`` with statement signing replaced: an unsigned envelope carrying the canonical statement."""
    import base64

    from darnit_amber import run as r

    from tests.darnit_amber.test_run_bundle import _FsStore

    monkeypatch.setattr(r.Path, "exists", lambda self: True)  # the darnit CLI next to the interpreter
    monkeypatch.setattr(
        r,
        "sign_statement",
        lambda stmt, key, tsa: {
            "payloadType": "stmt",
            "payload": base64.b64encode(r._canonical(stmt)).decode(),
            "signatures": [],
        },
    )
    return _FsStore(tmp_path / "store")


@pytest.fixture
def stamped(monkeypatch: pytest.MonkeyPatch) -> None:
    """``verify`` with timestamp checking replaced: every signature counts as stamped at STAMP_TIME."""
    from darnit_amber import rerun as rr

    from tests.darnit_amber.test_run_bundle import _stamps_for

    monkeypatch.setattr(rr, "_timestamps", _stamps_for)
