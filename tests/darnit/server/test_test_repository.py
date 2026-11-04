"""Tests for create_test_repository MCP tool."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from darnit.server.tools.test_repository import create_test_repository_impl

_GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


@pytest.fixture(autouse=True)
def _set_git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure git commits in newly created test repositories succeed without global config."""
    for key, value in _GIT_IDENTITY.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def parent_git_dir(tmp_path: Path) -> Path:
    """Fixture providing a valid git repository to act as parent_dir."""
    parent = tmp_path / "workspace"
    parent.mkdir()
    subprocess.run(["git", "init"], cwd=str(parent), check=True, capture_output=True)
    return parent


@pytest.mark.unit
def test_invalid_parent_dir_returns_error(tmp_path: Path) -> None:
    nonexistent = str(tmp_path / "missing_dir_xyz")
    output = create_test_repository_impl(repo_name="demo", parent_dir=nonexistent)
    assert output.startswith("❌ Error: Path does not exist:")


@pytest.mark.unit
def test_parent_dir_not_git_repo_returns_error(tmp_path: Path) -> None:
    empty_dir = tmp_path / "plain_dir"
    empty_dir.mkdir()
    output = create_test_repository_impl(repo_name="demo", parent_dir=str(empty_dir))
    assert "not a git repository" in output


@pytest.mark.unit
def test_repo_already_exists_returns_error(parent_git_dir: Path) -> None:
    existing = parent_git_dir / "already-exists"
    existing.mkdir()
    output = create_test_repository_impl(repo_name="already-exists", parent_dir=str(parent_git_dir))
    assert f"Directory '{existing}' already exists" in output


@pytest.mark.unit
def test_creates_test_repo_locally_without_github(parent_git_dir: Path) -> None:
    repo_name = "sample-test-repo"
    output = create_test_repository_impl(
        repo_name=repo_name,
        parent_dir=str(parent_git_dir),
        create_github=False,
    )

    created_repo = parent_git_dir / repo_name
    assert created_repo.is_dir()
    assert (created_repo / "package.json").is_file()
    assert (created_repo / "src" / "index.js").is_file()
    assert (created_repo / ".gitignore").is_file()
    assert (created_repo / ".git").is_dir()

    # Package.json contents
    pkg_content = (created_repo / "package.json").read_text(encoding="utf-8")
    assert '"name": "baseline-test"' in pkg_content
    assert '"chalk"' in pkg_content

    # Output verification
    assert f"✅ Created test repository: {created_repo}" in output
    assert "What's intentionally MISSING" in output
    assert "- ✗ LICENSE file" in output
    assert "- ✗ README.md" in output

    # Git log verification
    log = subprocess.run(
        ["git", "log", "-1", "--oneline"],
        cwd=str(created_repo),
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Initial commit - intentionally non-compliant" in log.stdout


@pytest.mark.unit
def test_github_cli_unauthenticated_warning(parent_git_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_run = subprocess.run

    def mock_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "gh" and cmd[1:3] == ["auth", "status"]:
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="not logged in")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mock_run)

    output = create_test_repository_impl(
        repo_name="gh-unauth-repo",
        parent_dir=str(parent_git_dir),
        create_github=True,
    )
    assert "⚠️ GitHub CLI not authenticated. Skipping GitHub repo creation." in output


@pytest.mark.unit
def test_github_cli_not_found(parent_git_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_run = subprocess.run

    def mock_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "gh":
            raise FileNotFoundError("gh executable not found")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mock_run)

    output = create_test_repository_impl(
        repo_name="gh-missing-repo",
        parent_dir=str(parent_git_dir),
        create_github=True,
    )
    assert "⚠️ GitHub CLI (gh) not found. Skipping GitHub repo creation." in output


@pytest.mark.unit
def test_github_repo_creation_and_template_success(
    parent_git_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_run = subprocess.run
    gh_calls: list[list[str]] = []

    def mock_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "gh":
            gh_calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="mock-user", stderr="")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mock_run)

    output = create_test_repository_impl(
        repo_name="full-success-repo",
        parent_dir=str(parent_git_dir),
        github_org="custom-org",
        create_github=True,
        make_template=True,
    )

    assert "✅ GitHub repo created: https://github.com/custom-org/full-success-repo" in output
    assert "✅ Repository is now a template" in output
    # Verify gh commands were executed
    subcommands = [call[1] for call in gh_calls]
    assert "auth" in subcommands
    assert "repo" in subcommands
    assert "api" in subcommands
