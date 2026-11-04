"""Tests for get_remediation_status_impl git operations MCP tool."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from darnit.server.tools.git_operations import get_remediation_status_impl

_GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


@pytest.fixture(autouse=True)
def _set_git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set git identity so commits work cleanly in test repositories."""
    for key, value in _GIT_IDENTITY.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Create a clean git repository on branch main with an initial commit."""
    repo_dir = tmp_path / "test-repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_dir), check=True, capture_output=True)
    (repo_dir / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )
    return repo_dir


@pytest.mark.unit
def test_invalid_path_returns_error(tmp_path: Path) -> None:
    output = get_remediation_status_impl(str(tmp_path / "nonexistent"))
    assert output.startswith("Error: Path does not exist:")


@pytest.mark.unit
def test_not_a_git_repo_returns_error(tmp_path: Path) -> None:
    plain_dir = tmp_path / "plain_dir"
    plain_dir.mkdir()
    output = get_remediation_status_impl(str(plain_dir))
    assert "not a git repository" in output


@pytest.mark.unit
def test_default_branch_warning_on_main(repo: Path) -> None:
    output = get_remediation_status_impl(str(repo))
    assert "**Current branch:** `main`" in output
    assert "**Warning:** You're on the default branch. Create a remediation branch first:" in output
    assert "create_remediation_branch" in output


@pytest.mark.unit
def test_clean_working_tree_feature_branch(repo: Path) -> None:
    subprocess.run(["git", "checkout", "-b", "fix/compliance"], cwd=str(repo), check=True, capture_output=True)
    output = get_remediation_status_impl(str(repo))

    assert "**Current branch:** `fix/compliance`" in output
    assert "Working directory is clean." in output
    assert "**To start remediation:**" in output
    assert "create_remediation_branch" in output


@pytest.mark.unit
def test_uncommitted_changes_listed(repo: Path) -> None:
    subprocess.run(["git", "checkout", "-b", "fix/compliance"], cwd=str(repo), check=True, capture_output=True)
    (repo / "file1.txt").write_text("content 1\n", encoding="utf-8")
    (repo / "file2.txt").write_text("content 2\n", encoding="utf-8")

    output = get_remediation_status_impl(str(repo))
    assert "**Uncommitted changes:** 2 file(s)" in output
    assert "file1.txt" in output
    assert "file2.txt" in output
    assert "**Next step:** Commit your changes:" in output


@pytest.mark.unit
def test_uncommitted_changes_overflow_handled(repo: Path) -> None:
    subprocess.run(["git", "checkout", "-b", "fix/compliance"], cwd=str(repo), check=True, capture_output=True)
    for i in range(7):
        (repo / f"extra_{i}.txt").write_text(f"content {i}\n", encoding="utf-8")

    output = get_remediation_status_impl(str(repo))
    assert "**Uncommitted changes:** 7 file(s)" in output
    assert "... and 2 more" in output


@pytest.mark.unit
def test_unpushed_commits_reported(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subprocess.run(["git", "checkout", "-b", "fix/compliance"], cwd=str(repo), check=True, capture_output=True)
    real_run = subprocess.run

    def mock_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "log"] and "@{u}..HEAD" in cmd:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="a1b2c3d Fix security header\n", stderr="")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mock_run)

    output = get_remediation_status_impl(str(repo))
    assert "**Unpushed commits:** 1" in output
    assert "**Next step:** Create a pull request:" in output


@pytest.mark.unit
def test_open_pr_reported(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subprocess.run(["git", "checkout", "-b", "fix/compliance"], cwd=str(repo), check=True, capture_output=True)
    real_run = subprocess.run

    def mock_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "pr", "view"]:
            return subprocess.CompletedProcess(
                cmd, returncode=0, stdout="https://github.com/org/repo/pull/99\n", stderr=""
            )
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mock_run)

    output = get_remediation_status_impl(str(repo))
    assert "**Open PR:** https://github.com/org/repo/pull/99" in output
    assert "PR is open and ready for review!" in output


@pytest.mark.unit
def test_git_command_missing_handled(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_run = subprocess.run

    def mock_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "git":
            raise FileNotFoundError("git executable not found")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mock_run)

    output = get_remediation_status_impl(str(repo))
    assert output == "Error: git command not found. Ensure git is installed."


@pytest.mark.unit
def test_unexpected_exception_handled(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_run = subprocess.run

    def mock_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "git":
            raise OSError("I/O device failure")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mock_run)

    output = get_remediation_status_impl(str(repo))
    assert output == "Error: I/O device failure"
