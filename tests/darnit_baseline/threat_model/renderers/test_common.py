"""Tests for common threat model renderer helpers (repo_display_name)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from darnit_baseline.threat_model.renderers.common import repo_display_name


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
    )


class TestRepoDisplayName:
    """Tests for repo_display_name identity resolution."""

    def test_explicit_owner_and_repo_used_directly(self) -> None:
        assert (
            repo_display_name(
                "/any/local/path",
                owner="whiskeytastingfoundation",
                repo="wtf-frontend",
            )
            == "whiskeytastingfoundation/wtf-frontend"
        )

    def test_explicit_owner_and_repo_ignores_fork_remote(self, tmp_path: Any) -> None:
        repo_dir = tmp_path / "checkout"
        repo_dir.mkdir()
        _git(repo_dir, "init")
        _git(repo_dir, "remote", "add", "origin", "git@github.com:myfork/wtf-frontend.git")

        # When caller provides owner and repo, use that instead of the fork remote
        assert (
            repo_display_name(
                str(repo_dir),
                owner="whiskeytastingfoundation",
                repo="wtf-frontend",
            )
            == "whiskeytastingfoundation/wtf-frontend"
        )

    def test_explicit_repo_with_slash(self) -> None:
        assert (
            repo_display_name(
                "/any/path",
                repo="whiskeytastingfoundation/wtf-frontend",
            )
            == "whiskeytastingfoundation/wtf-frontend"
        )

    def test_no_identity_with_origin_remote(self, tmp_path: Any) -> None:
        repo_dir = tmp_path / "checkout"
        repo_dir.mkdir()
        _git(repo_dir, "init")
        _git(repo_dir, "remote", "add", "origin", "git@github.com:upstream-org/project.git")

        assert repo_display_name(str(repo_dir)) == "upstream-org/project"

    def test_no_identity_with_upstream_remote(self, tmp_path: Any) -> None:
        repo_dir = tmp_path / "checkout"
        repo_dir.mkdir()
        _git(repo_dir, "init")
        _git(repo_dir, "remote", "add", "upstream", "https://github.com/upstream-org/project.git")

        assert repo_display_name(str(repo_dir)) == "upstream-org/project"

    def test_no_identity_no_remote_falls_back_to_basename(self, tmp_path: Any) -> None:
        plain_dir = tmp_path / "repo"
        plain_dir.mkdir()
        assert repo_display_name(str(plain_dir)) == "repo"

    def test_partial_owner_only_with_remote(self, tmp_path: Any) -> None:
        repo_dir = tmp_path / "checkout"
        repo_dir.mkdir()
        _git(repo_dir, "init")
        _git(repo_dir, "remote", "add", "origin", "git@github.com:fork/my-project.git")

        assert repo_display_name(str(repo_dir), owner="real-org") == "real-org/my-project"

    def test_partial_repo_only_with_remote(self, tmp_path: Any) -> None:
        repo_dir = tmp_path / "checkout"
        repo_dir.mkdir()
        _git(repo_dir, "init")
        _git(repo_dir, "remote", "add", "origin", "git@github.com:my-org/old-name.git")

        assert repo_display_name(str(repo_dir), repo="new-name") == "my-org/new-name"

    def test_whitespace_stripped(self) -> None:
        assert (
            repo_display_name(
                "/any/path",
                owner="  my-org  ",
                repo="  my-repo  ",
            )
            == "my-org/my-repo"
        )

