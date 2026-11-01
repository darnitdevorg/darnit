"""Tests for darnit.core.utils module."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from darnit.core.utils import (
    clear_dir_entries_cache,
    file_exists,
    get_file_identity,
    get_git_commit,
    get_git_ref,
    gh_api,
    gh_api_safe,
    read_file,
    resolve_case_exact_path,
    set_gh_api_responder,
    validate_local_path,
)


class TestValidateLocalPath:
    """Tests for validate_local_path function."""

    @pytest.mark.unit
    def test_valid_git_repo(self, temp_git_repo: Path):
        """Test validation of a valid git repository."""
        resolved, error = validate_local_path(str(temp_git_repo))
        assert error is None
        assert resolved == str(temp_git_repo)

    @pytest.mark.unit
    def test_nonexistent_path(self, temp_dir: Path):
        """Test validation of a nonexistent path."""
        nonexistent = temp_dir / "does_not_exist"
        resolved, error = validate_local_path(str(nonexistent))
        assert error is not None
        assert "does not exist" in error

    @pytest.mark.unit
    def test_file_not_directory(self, temp_dir: Path):
        """Test validation fails for a file (not directory)."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("test")
        resolved, error = validate_local_path(str(test_file))
        assert error is not None
        assert "not a directory" in error

    @pytest.mark.unit
    def test_not_git_repo(self, temp_dir: Path):
        """Test validation fails for non-git directory."""
        resolved, error = validate_local_path(str(temp_dir))
        assert error is not None
        assert "not a git repository" in error

    @pytest.mark.unit
    def test_relative_path_resolution(self, temp_git_repo: Path, monkeypatch):
        """Test that relative paths are resolved to absolute."""
        monkeypatch.chdir(temp_git_repo)
        resolved, error = validate_local_path(".")
        assert error is None
        assert os.path.isabs(resolved)


class TestFileExists:
    """Tests for file_exists function."""

    @pytest.mark.unit
    def test_file_exists_single_pattern(self, temp_dir: Path):
        """Test file_exists with a single pattern."""
        (temp_dir / "README.md").write_text("# Test")
        assert file_exists(str(temp_dir), "README.md") is True
        assert file_exists(str(temp_dir), "NONEXISTENT.md") is False

    @pytest.mark.unit
    def test_file_exists_multiple_patterns(self, temp_dir: Path):
        """Test file_exists with multiple patterns."""
        (temp_dir / "README.md").write_text("# Test")
        assert file_exists(str(temp_dir), "SECURITY.md", "README.md") is True
        assert file_exists(str(temp_dir), "SECURITY.md", "LICENSE") is False

    @pytest.mark.unit
    def test_file_exists_glob_pattern(self, temp_dir: Path):
        """Test file_exists with glob patterns."""
        (temp_dir / "docs").mkdir()
        (temp_dir / "docs" / "guide.md").write_text("# Guide")
        assert file_exists(str(temp_dir), "docs/*.md") is True
        assert file_exists(str(temp_dir), "**/*.md") is True

    @pytest.mark.unit
    def test_file_exists_nested(self, temp_dir: Path):
        """Test file_exists with nested directories."""
        github_dir = temp_dir / ".github"
        github_dir.mkdir()
        (github_dir / "SECURITY.md").write_text("# Security")
        assert file_exists(str(temp_dir), ".github/SECURITY.md") is True
        # Also test with subdirectory glob
        assert file_exists(str(temp_dir), ".github/*.md") is True


class TestReadFile:
    """Tests for read_file function."""

    @pytest.mark.unit
    def test_read_existing_file(self, temp_dir: Path):
        """Test reading an existing file."""
        content = "Hello, World!"
        (temp_dir / "test.txt").write_text(content)
        result = read_file(str(temp_dir), "test.txt")
        assert result == content

    @pytest.mark.unit
    def test_read_nonexistent_file(self, temp_dir: Path):
        """Test reading a nonexistent file returns None."""
        result = read_file(str(temp_dir), "nonexistent.txt")
        assert result is None

    @pytest.mark.unit
    def test_read_file_utf8(self, temp_dir: Path):
        """Test reading file with UTF-8 content."""
        content = "Hello, 世界! 🌍"
        (temp_dir / "unicode.txt").write_text(content, encoding="utf-8")
        result = read_file(str(temp_dir), "unicode.txt")
        assert result == content


class TestGitCommit:
    """Tests for get_git_commit function."""

    @pytest.mark.unit
    def test_get_git_commit_valid_repo(self, temp_git_repo: Path):
        """Test getting commit from valid repo."""
        commit = get_git_commit(str(temp_git_repo))
        assert commit is not None
        assert len(commit) == 40  # Full SHA
        assert all(c in "0123456789abcdef" for c in commit)

    @pytest.mark.unit
    def test_get_git_commit_invalid_path(self, temp_dir: Path):
        """Test getting commit from non-git directory returns None."""
        commit = get_git_commit(str(temp_dir))
        assert commit is None


class TestGitRef:
    """Tests for get_git_ref function."""

    @pytest.mark.unit
    def test_get_git_ref_main_branch(self, temp_git_repo: Path):
        """Test getting ref from main branch."""
        ref = get_git_ref(str(temp_git_repo))
        assert ref is not None
        # Could be 'main' or 'master' depending on git config
        assert ref in ["main", "master"]

    @pytest.mark.unit
    def test_get_git_ref_invalid_path(self, temp_dir: Path):
        """Test getting ref from non-git directory returns None."""
        ref = get_git_ref(str(temp_dir))
        assert ref is None


class TestGithubCliErrors:
    """Tests for GitHub CLI helper failures."""

    @pytest.fixture(autouse=True)
    def _no_responder(self):
        """These tests drive the real ``gh`` path with a mocked ``subprocess.run``; drop the suite's responder (#548)."""
        previous = set_gh_api_responder(None)
        yield
        set_gh_api_responder(previous)

    @pytest.mark.unit
    def test_gh_api_missing_cli_shows_helpful_message(self):
        """Missing gh CLI should raise a user-facing RuntimeError."""
        with (
            patch("darnit.core.utils.subprocess.run", side_effect=FileNotFoundError),
            pytest.raises(RuntimeError, match=r"GitHub CLI \(gh\) not found"),
        ):
            gh_api("repos/kusari-oss/darnit")

    @pytest.mark.unit
    def test_gh_api_safe_missing_cli_returns_none(self):
        """Safe helper should swallow missing gh CLI errors."""
        with patch("darnit.core.utils.subprocess.run", side_effect=FileNotFoundError):
            assert gh_api_safe("repos/kusari-oss/darnit") is None


class TestResolveCaseExactPath:
    """Tests for resolve_case_exact_path and case-exact resolution."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        clear_dir_entries_cache()
        yield
        clear_dir_entries_cache()

    @pytest.mark.unit
    def test_case_exact_file_in_root(self, temp_dir: Path):
        readme = temp_dir / "README.md"
        readme.write_text("content")

        assert resolve_case_exact_path("README.md", str(temp_dir)) == str(readme)
        # Lowercase probe must return None even on case-insensitive filesystems
        assert resolve_case_exact_path("readme.md", str(temp_dir)) is None
        assert resolve_case_exact_path("Readme.md", str(temp_dir)) is None

    @pytest.mark.unit
    def test_case_exact_nested_path(self, temp_dir: Path):
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        arch = docs_dir / "ARCHITECTURE.md"
        arch.write_text("arch")

        assert resolve_case_exact_path("docs/ARCHITECTURE.md", str(temp_dir)) == str(arch)
        # Mismatched file case
        assert resolve_case_exact_path("docs/architecture.md", str(temp_dir)) is None
        # Mismatched directory case
        assert resolve_case_exact_path("DOCS/ARCHITECTURE.md", str(temp_dir)) is None

    @pytest.mark.unit
    def test_nonexistent_file_returns_none(self, temp_dir: Path):
        assert resolve_case_exact_path("MISSING.md", str(temp_dir)) is None
        assert resolve_case_exact_path("docs/MISSING.md", str(temp_dir)) is None

    @pytest.mark.unit
    def test_empty_or_root_path(self, temp_dir: Path):
        assert resolve_case_exact_path("", str(temp_dir)) is None
        assert resolve_case_exact_path(".", str(temp_dir)) == str(temp_dir)

    @pytest.mark.unit
    def test_traversal_outside_root_returns_none(self, temp_dir: Path):
        assert resolve_case_exact_path("../outside.txt", str(temp_dir)) is None

    @pytest.mark.unit
    def test_double_dot_prefixed_filename(self, temp_dir: Path):
        f = temp_dir / "..b.md"
        f.write_text("two dots")
        assert resolve_case_exact_path("..b.md", str(temp_dir)) == str(f)


class TestGetFileIdentity:
    """Tests for get_file_identity deduplication helper."""

    @pytest.mark.unit
    def test_same_file_returns_same_identity(self, temp_dir: Path):
        f = temp_dir / "sample.txt"
        f.write_text("hello")

        id1 = get_file_identity(str(f))
        id2 = get_file_identity(str(f))
        assert id1 == id2

    @pytest.mark.unit
    def test_different_files_return_different_identities(self, temp_dir: Path):
        f1 = temp_dir / "a.txt"
        f2 = temp_dir / "b.txt"
        f1.write_text("a")
        f2.write_text("b")

        assert get_file_identity(str(f1)) != get_file_identity(str(f2))
