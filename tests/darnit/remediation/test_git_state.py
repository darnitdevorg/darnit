"""Tests for darnit.remediation.git_state safe git runner (issue #617)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from darnit.remediation.git_state import (
    _auditor_gpg_program,
    _auditor_gpg_ssh_program,
    run_git,
)


@pytest.fixture
def clean_git_repo(tmp_path: Path) -> Path:
    """Create a clean git repository."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "Initial commit"], cwd=repo, check=True)
    return repo


class TestRunGitSecurity:
    """Verify that run_git neutralizes untrusted repository config (issue #617)."""

    @pytest.mark.unit
    def test_run_git_disables_planted_fsmonitor(self, clean_git_repo: Path):
        """core.fsmonitor in repository config must not execute."""
        witness = clean_git_repo / ".git" / "witness.txt"
        evil_script = clean_git_repo / ".git" / "evil_fsmonitor.sh"
        evil_script.write_text(f"#!/bin/sh\necho evil > {witness}\nexit 0\n")
        evil_script.chmod(0o755)

        subprocess.run(
            ["git", "config", "core.fsmonitor", str(evil_script)],
            cwd=clean_git_repo,
            check=True,
        )

        res = run_git(clean_git_repo, "status", "--porcelain")
        assert res.returncode == 0
        assert not witness.exists(), "Planted core.fsmonitor must not execute!"

    @pytest.mark.unit
    def test_run_git_pins_gpg_program(self, clean_git_repo: Path):
        """gpg.program in repository config must be overridden by auditor defaults."""
        subprocess.run(
            ["git", "config", "gpg.program", "/untrusted/malicious/gpg"],
            cwd=clean_git_repo,
            check=True,
        )

        res = run_git(clean_git_repo, "config", "gpg.program")
        assert res.returncode == 0
        expected = _auditor_gpg_program()
        assert res.stdout.strip() == expected
        assert res.stdout.strip() != "/untrusted/malicious/gpg"

    @pytest.mark.unit
    def test_run_git_pins_gpg_ssh_program(self, clean_git_repo: Path):
        """gpg.ssh.program in repository config must be overridden by auditor defaults."""
        subprocess.run(
            ["git", "config", "gpg.ssh.program", "/untrusted/malicious/ssh-keygen"],
            cwd=clean_git_repo,
            check=True,
        )

        res = run_git(clean_git_repo, "config", "gpg.ssh.program")
        assert res.returncode == 0
        expected = _auditor_gpg_ssh_program()
        assert res.stdout.strip() == expected
        assert res.stdout.strip() != "/untrusted/malicious/ssh-keygen"

    @pytest.mark.unit
    def test_run_git_timeout_handling(self, clean_git_repo: Path):
        """run_git passes timeout to subprocess.run."""
        with pytest.raises(subprocess.TimeoutExpired):
            run_git(clean_git_repo, "status", timeout=0.0000001)
