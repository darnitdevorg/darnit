"""Unit tests for Git attestation helpers (darnit_baseline.attestation.git)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from darnit_baseline.attestation.git import get_git_commit, get_git_ref


@pytest.mark.unit
class TestGetGitCommit:
    """Tests for commit SHA extraction."""

    def test_get_git_commit_success(self) -> None:
        mock_proc = MagicMock(returncode=0, stdout="4b825dc642cb6eb9a060e54bf8d69288fbee4904\n")
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            commit = get_git_commit("/path/to/repo")
            assert commit == "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
            mock_run.assert_called_once_with(
                ["git", "rev-parse", "HEAD"],
                cwd="/path/to/repo",
                capture_output=True,
                text=True,
            )

    def test_get_git_commit_non_zero_exit(self) -> None:
        mock_proc = MagicMock(returncode=128, stdout="", stderr="fatal: not a git repository")
        with patch("subprocess.run", return_value=mock_proc):
            assert get_git_commit("/not/a/repo") is None

    def test_get_git_commit_subprocess_error(self) -> None:
        with patch("subprocess.run", side_effect=subprocess.SubprocessError("git timeout")):
            assert get_git_commit("/path/to/repo") is None

    def test_get_git_commit_file_not_found(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError("git binary not found")):
            assert get_git_commit("/path/to/repo") is None

    def test_get_git_commit_os_error(self) -> None:
        with patch("subprocess.run", side_effect=OSError("permission denied")):
            assert get_git_commit("/path/to/repo") is None


@pytest.mark.unit
class TestGetGitRef:
    """Tests for git ref (branch or tag) resolution."""

    def test_get_git_ref_branch_success(self) -> None:
        mock_proc = MagicMock(returncode=0, stdout="feature/my-branch\n")
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            ref = get_git_ref("/path/to/repo")
            assert ref == "feature/my-branch"
            mock_run.assert_called_once_with(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd="/path/to/repo",
                capture_output=True,
                text=True,
            )

    def test_get_git_ref_detached_head_with_tag(self) -> None:
        branch_proc = MagicMock(returncode=0, stdout="HEAD\n")
        tag_proc = MagicMock(returncode=0, stdout="v1.2.3\n")

        with patch("subprocess.run", side_effect=[branch_proc, tag_proc]) as mock_run:
            ref = get_git_ref("/path/to/repo")
            assert ref == "v1.2.3"
            assert mock_run.call_count == 2
            mock_run.assert_any_call(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd="/path/to/repo",
                capture_output=True,
                text=True,
            )
            mock_run.assert_any_call(
                ["git", "describe", "--tags", "--exact-match"],
                cwd="/path/to/repo",
                capture_output=True,
                text=True,
            )

    def test_get_git_ref_detached_head_without_tag(self) -> None:
        branch_proc = MagicMock(returncode=0, stdout="HEAD\n")
        tag_proc = MagicMock(returncode=128, stdout="", stderr="fatal: no tag exactly matches")

        with patch("subprocess.run", side_effect=[branch_proc, tag_proc]):
            assert get_git_ref("/path/to/repo") is None

    def test_get_git_ref_failure_non_zero_exit(self) -> None:
        mock_proc = MagicMock(returncode=128, stdout="", stderr="fatal: not a git repo")
        with patch("subprocess.run", return_value=mock_proc):
            assert get_git_ref("/not/a/repo") is None

    def test_get_git_ref_subprocess_error(self) -> None:
        with patch("subprocess.run", side_effect=subprocess.SubprocessError("error")):
            assert get_git_ref("/path/to/repo") is None

    def test_get_git_ref_file_not_found(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError("no git")):
            assert get_git_ref("/path/to/repo") is None

    def test_get_git_ref_os_error(self) -> None:
        with patch("subprocess.run", side_effect=OSError("os error")):
            assert get_git_ref("/path/to/repo") is None


@pytest.mark.integration
class TestRealGitRepoIntegration:
    """Live verification against an initialized temporary git repository."""

    def test_real_git_repository_commit_and_ref(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        # Initialize real git repo
        subprocess.run(["git", "init", "--quiet"], cwd=str(repo_dir), check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo_dir), check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo_dir), check=True)

        # Before any commit, HEAD is unborn
        assert get_git_commit(str(repo_dir)) is None

        # Create first commit
        (repo_dir / "file.txt").write_text("hello", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(repo_dir), check=True)

        commit = get_git_commit(str(repo_dir))
        assert commit is not None
        assert len(commit) == 40
        assert all(c in "0123456789abcdef" for c in commit)

        ref = get_git_ref(str(repo_dir))
        assert ref in ("main", "master")
