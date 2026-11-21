"""Regression tests for issue #617: hardening read-side git calls against untrusted repo config."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from darnit_gittuf.handlers import gittuf_commits_signed_handler

from darnit.core.audit_cache import (
    read_audit_cache,
    write_audit_cache,
)
from darnit.remediation import git_state
from darnit.sieve.handler_registry import HandlerContext


def _init_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    (repo / "README.md").write_text("# test\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)


@pytest.mark.unit
def test_run_git_disables_fsmonitor() -> None:
    with patch("subprocess.run") as mock_run:
        git_state.run_git("/tmp/repo", "status", "--porcelain")
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "git"
        assert "-c" in cmd
        idx = cmd.index("-c")
        assert cmd[idx + 1] == "core.fsmonitor=false"


@pytest.mark.unit
def test_run_git_pins_signing_programs_when_requested() -> None:
    with patch("subprocess.run") as mock_run:
        git_state.run_git("/tmp/repo", "log", "-1", verify_signatures=True)
        cmd = mock_run.call_args[0][0]
        kv_pairs = [cmd[i + 1] for i, tok in enumerate(cmd) if tok == "-c" and i + 1 < len(cmd)]
        assert "core.fsmonitor=false" in kv_pairs
        assert any(kv.startswith("gpg.program=") for kv in kv_pairs)
        assert any(kv.startswith("gpg.ssh.program=") for kv in kv_pairs)


@pytest.mark.integration
@pytest.mark.skipif(os.name == "nt", reason="POSIX executable script test")
def test_planted_fsmonitor_does_not_run_during_audit(tmp_path: Path) -> None:
    """A planted core.fsmonitor in an untrusted repo's .git/config must not execute."""
    repo = tmp_path / "untrusted_repo"
    repo.mkdir()
    _init_repo(repo)

    marker = tmp_path / "fsmonitor_ran.marker"
    malicious_fsmonitor = tmp_path / "evil_fsmonitor.sh"
    malicious_fsmonitor.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    malicious_fsmonitor.chmod(malicious_fsmonitor.stat().st_mode | stat.S_IEXEC)

    # Plant core.fsmonitor directly in the repository's local .git/config
    subprocess.run(
        ["git", "config", "--local", "core.fsmonitor", str(malicious_fsmonitor)],
        cwd=repo,
        check=True,
    )

    # Exercise audit-path git operations (cache write/read + state inspection + full sieve audit)
    from darnit.tools.audit import run_sieve_audit

    write_audit_cache(str(repo), [], {"PASS": 1}, level=1, framework="openssf-baseline")
    assert read_audit_cache(str(repo)) is not None
    assert git_state.is_work_tree(repo) is True
    assert git_state.has_tracked_changes(repo) is False
    assert git_state.current_branch(repo) == "main"
    run_sieve_audit(local_path=str(repo), owner="testowner", repo="testrepo", default_branch="main", level=1, framework_name="openssf-baseline")

    assert not marker.exists(), "Planted core.fsmonitor executed during read-side audit git calls!"


@pytest.mark.integration
@pytest.mark.skipif(os.name == "nt", reason="POSIX executable script test")
def test_planted_gpg_program_does_not_run_during_signature_check(tmp_path: Path) -> None:
    """A planted gpg.program in an untrusted repo's .git/config must not execute."""
    repo = tmp_path / "untrusted_sig_repo"
    repo.mkdir()
    _init_repo(repo)

    marker = tmp_path / "gpg_program_ran.marker"
    malicious_gpg = tmp_path / "evil_gpg.sh"
    malicious_gpg.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n", encoding="utf-8")
    malicious_gpg.chmod(malicious_gpg.stat().st_mode | stat.S_IEXEC)

    subprocess.run(
        ["git", "config", "--local", "gpg.program", str(malicious_gpg)],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "--local", "gpg.ssh.program", str(malicious_gpg)],
        cwd=repo,
        check=True,
    )

    ctx = HandlerContext(
        local_path=str(repo),
        owner="testowner",
        repo="testrepo",
        default_branch="main",
        control_id="GT-02.01",
        project_context={},
        gathered_evidence={},
        dependency_results={},
    )
    gittuf_commits_signed_handler({}, ctx)

    assert not marker.exists(), "Planted gpg.program / gpg.ssh.program executed during signature check!"
