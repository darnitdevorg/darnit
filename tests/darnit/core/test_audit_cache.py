"""Tests for darnit.core.audit_cache module."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from darnit.core.audit_cache import (
    CACHE_FILENAME,
    CACHE_VERSION,
    _get_cache_dir,
    _get_head_commit,
    _is_working_tree_dirty,
    invalidate_audit_cache,
    read_audit_cache,
    write_audit_cache,
)


@pytest.fixture
def sample_results() -> list[dict]:
    return [
        {"id": "OSPS-AC-01.01", "status": "PASS", "details": "OK", "level": 1},
        {"id": "OSPS-DO-02.01", "status": "FAIL", "details": "Missing", "level": 1},
        {"id": "OSPS-GV-01.01", "status": "WARN", "details": "Manual", "level": 1},
    ]


@pytest.fixture
def sample_summary() -> dict[str, int]:
    return {"PASS": 1, "FAIL": 1, "WARN": 1, "N/A": 0, "ERROR": 0, "total": 3}


class TestGitHelpers:
    """Tests for _get_head_commit and _is_working_tree_dirty."""

    @pytest.mark.unit
    def test_get_head_commit_in_git_repo(self, temp_git_repo: Path):
        commit = _get_head_commit(str(temp_git_repo))
        assert commit is not None
        assert len(commit) == 40  # Full SHA

    @pytest.mark.unit
    def test_get_head_commit_non_git_dir(self, temp_dir: Path):
        commit = _get_head_commit(str(temp_dir))
        assert commit is None

    @pytest.mark.unit
    def test_is_working_tree_dirty_clean(self, temp_git_repo: Path):
        dirty = _is_working_tree_dirty(str(temp_git_repo))
        assert dirty is False

    @pytest.mark.unit
    def test_is_working_tree_dirty_with_changes(self, temp_git_repo: Path):
        (temp_git_repo / "new_file.txt").write_text("hello")
        dirty = _is_working_tree_dirty(str(temp_git_repo))
        assert dirty is True


class TestCacheDir:
    """Tests for _get_cache_dir."""

    @pytest.mark.unit
    def test_returns_temp_based_path(self, temp_git_repo: Path):
        cache_dir = _get_cache_dir(str(temp_git_repo))
        assert "darnit" in str(cache_dir)
        assert cache_dir != temp_git_repo  # Not inside repo

    @pytest.mark.unit
    def test_deterministic_for_same_path(self, temp_git_repo: Path):
        a = _get_cache_dir(str(temp_git_repo))
        b = _get_cache_dir(str(temp_git_repo))
        assert a == b

    @pytest.mark.unit
    def test_different_for_different_repos(self, tmp_path: Path):
        repo_a = tmp_path / "repo-a"
        repo_b = tmp_path / "repo-b"
        repo_a.mkdir()
        repo_b.mkdir()
        a = _get_cache_dir(str(repo_a))
        b = _get_cache_dir(str(repo_b))
        assert a != b


class TestWriteReadRoundTrip:
    """Tests for write/read round-trip."""

    @pytest.mark.unit
    def test_write_then_read(
        self, temp_git_repo: Path, sample_results, sample_summary
    ):
        write_audit_cache(
            str(temp_git_repo), sample_results, sample_summary, 3, "openssf-baseline"
        )

        cache = read_audit_cache(str(temp_git_repo))
        assert cache is not None
        assert cache["version"] == CACHE_VERSION
        assert cache["level"] == 3
        assert cache["framework"] == "openssf-baseline"
        assert cache["results"] == sample_results
        assert cache["summary"] == sample_summary
        assert cache["commit"] is not None
        assert isinstance(cache["commit_dirty"], bool)
        assert "timestamp" in cache

    @pytest.mark.unit
    def test_creates_cache_directory(
        self, temp_git_repo: Path, sample_results, sample_summary
    ):
        cache_dir = _get_cache_dir(str(temp_git_repo))
        assert not cache_dir.exists()

        write_audit_cache(
            str(temp_git_repo), sample_results, sample_summary, 1, "test"
        )

        assert cache_dir.is_dir()
        assert (cache_dir / CACHE_FILENAME).is_file()

    @pytest.mark.unit
    def test_no_files_in_repo_dir(
        self, temp_git_repo: Path, sample_results, sample_summary
    ):
        """Cache should be written to temp dir, not the repo itself."""
        write_audit_cache(
            str(temp_git_repo), sample_results, sample_summary, 1, "test"
        )
        assert not (temp_git_repo / ".darnit").exists()

    @pytest.mark.unit
    def test_envelope_structure(
        self, temp_git_repo: Path, sample_results, sample_summary
    ):
        write_audit_cache(
            str(temp_git_repo), sample_results, sample_summary, 2, "test-fw"
        )
        cache_path = _get_cache_dir(str(temp_git_repo)) / CACHE_FILENAME
        with open(cache_path) as f:
            data = json.load(f)

        assert set(data.keys()) == {
            "version",
            "timestamp",
            "commit",
            "commit_dirty",
            "level",
            "framework",
            "results",
            "summary",
        }


class TestStalenessDetection:
    """Tests for cache staleness via commit hash and dirty state."""

    @pytest.mark.unit
    def test_stale_after_new_commit(
        self, temp_git_repo: Path, sample_results, sample_summary
    ):
        write_audit_cache(
            str(temp_git_repo), sample_results, sample_summary, 3, "test"
        )

        # Make a new commit
        (temp_git_repo / "change.txt").write_text("change")
        subprocess.run(
            ["git", "add", "."], cwd=temp_git_repo, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "new commit"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True,
        )

        assert read_audit_cache(str(temp_git_repo)) is None

    @pytest.mark.unit
    def test_stale_when_tree_becomes_dirty(
        self, temp_git_repo: Path, sample_results, sample_summary
    ):
        # Write cache with clean tree
        write_audit_cache(
            str(temp_git_repo), sample_results, sample_summary, 3, "test"
        )
        assert read_audit_cache(str(temp_git_repo)) is not None

        # Make tree dirty
        (temp_git_repo / "uncommitted.txt").write_text("dirty")

        assert read_audit_cache(str(temp_git_repo)) is None

    @pytest.mark.unit
    def test_stale_when_tree_becomes_clean(
        self, temp_git_repo: Path, sample_results, sample_summary
    ):
        # Make tree dirty, then write cache
        dirty_file = temp_git_repo / "dirty.txt"
        dirty_file.write_text("dirty")

        write_audit_cache(
            str(temp_git_repo), sample_results, sample_summary, 3, "test"
        )
        assert read_audit_cache(str(temp_git_repo)) is not None

        # Clean up the tree (add + commit)
        subprocess.run(
            ["git", "add", "."], cwd=temp_git_repo, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "clean up"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True,
        )

        # Cache is stale: both commit AND dirty state changed
        assert read_audit_cache(str(temp_git_repo)) is None


class TestNonGitRepo:
    """Tests for non-git repository handling."""

    @pytest.mark.unit
    def test_write_with_null_commit(
        self, temp_dir: Path, sample_results, sample_summary
    ):
        write_audit_cache(str(temp_dir), sample_results, sample_summary, 1, "test")

        cache_path = _get_cache_dir(str(temp_dir)) / CACHE_FILENAME
        with open(cache_path) as f:
            data = json.load(f)

        assert data["commit"] is None

    @pytest.mark.unit
    def test_null_commit_always_stale(
        self, temp_dir: Path, sample_results, sample_summary
    ):
        write_audit_cache(str(temp_dir), sample_results, sample_summary, 1, "test")
        assert read_audit_cache(str(temp_dir)) is None


class TestCorruptionHandling:
    """Tests for corrupt/invalid cache files."""

    @pytest.mark.unit
    def test_corrupt_json(self, temp_git_repo: Path):
        cache_dir = _get_cache_dir(str(temp_git_repo))
        cache_dir.mkdir(parents=True)
        (cache_dir / CACHE_FILENAME).write_text("not valid json {{{")

        assert read_audit_cache(str(temp_git_repo)) is None

    @pytest.mark.unit
    def test_unknown_version(
        self, temp_git_repo: Path, sample_results, sample_summary
    ):
        write_audit_cache(
            str(temp_git_repo), sample_results, sample_summary, 3, "test"
        )

        # Bump version beyond supported
        cache_path = _get_cache_dir(str(temp_git_repo)) / CACHE_FILENAME
        with open(cache_path) as f:
            data = json.load(f)
        data["version"] = CACHE_VERSION + 1
        with open(cache_path, "w") as f:
            json.dump(data, f)

        assert read_audit_cache(str(temp_git_repo)) is None

    @pytest.mark.unit
    def test_not_a_dict(self, temp_git_repo: Path):
        cache_dir = _get_cache_dir(str(temp_git_repo))
        cache_dir.mkdir(parents=True)
        (cache_dir / CACHE_FILENAME).write_text('"just a string"')

        assert read_audit_cache(str(temp_git_repo)) is None

    @pytest.mark.unit
    def test_missing_cache_file(self, temp_git_repo: Path):
        assert read_audit_cache(str(temp_git_repo)) is None


class TestInvalidateCache:
    """Tests for invalidate_audit_cache."""

    @pytest.mark.unit
    def test_invalidate_existing(
        self, temp_git_repo: Path, sample_results, sample_summary
    ):
        write_audit_cache(
            str(temp_git_repo), sample_results, sample_summary, 3, "test"
        )
        cache_path = _get_cache_dir(str(temp_git_repo)) / CACHE_FILENAME
        assert cache_path.exists()

        invalidate_audit_cache(str(temp_git_repo))
        assert not cache_path.exists()

    @pytest.mark.unit
    def test_invalidate_missing_noop(self, temp_git_repo: Path):
        # Should not raise
        invalidate_audit_cache(str(temp_git_repo))

    @pytest.mark.unit
    def test_read_after_invalidate_returns_none(
        self, temp_git_repo: Path, sample_results, sample_summary
    ):
        write_audit_cache(
            str(temp_git_repo), sample_results, sample_summary, 3, "test"
        )
        invalidate_audit_cache(str(temp_git_repo))
        assert read_audit_cache(str(temp_git_repo)) is None


class TestAtomicWrite:
    """Tests for atomic write behavior."""

    @pytest.mark.unit
    def test_no_partial_file_on_error(
        self, temp_git_repo: Path, sample_results, sample_summary
    ):
        """If json.dump raises, no cache file should be left behind."""
        with patch("darnit.core.audit_cache.json.dump", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                write_audit_cache(
                    str(temp_git_repo),
                    sample_results,
                    sample_summary,
                    3,
                    "test",
                )

        cache_path = _get_cache_dir(str(temp_git_repo)) / CACHE_FILENAME
        assert not cache_path.exists()

    @pytest.mark.unit
    def test_overwrite_existing_cache(
        self, temp_git_repo: Path, sample_results, sample_summary
    ):
        """Writing twice overwrites the first cache atomically."""
        write_audit_cache(
            str(temp_git_repo), sample_results, sample_summary, 1, "first"
        )
        write_audit_cache(
            str(temp_git_repo), sample_results, sample_summary, 2, "second"
        )

        cache = read_audit_cache(str(temp_git_repo))
        assert cache is not None
        assert cache["level"] == 2
        assert cache["framework"] == "second"


class TestRunSieveAuditCacheIntegration:
    """Test that run_sieve_audit() writes cache as a side effect."""

    @pytest.mark.unit
    def test_run_sieve_audit_writes_cache(self, temp_git_repo: Path):
        """Verify run_sieve_audit() produces a cache file with correct structure."""
        mock_result = MagicMock()
        mock_result.to_legacy_dict.return_value = {
            "id": "TEST-01",
            "status": "PASS",
            "details": "OK",
            "level": 1,
        }

        mock_spec = MagicMock()
        mock_spec.control_id = "TEST-01"
        mock_spec.name = "Test Control"
        mock_spec.description = "A test control"
        mock_spec.level = 1
        mock_spec.metadata = {"full": ""}
        mock_spec.locator_config = None

        mock_orchestrator = MagicMock()
        mock_orchestrator.verify.return_value = mock_result

        mock_registry = MagicMock()
        mock_registry.get_specs_by_level.return_value = [mock_spec]

        sieve_components = {
            "SieveOrchestrator": lambda **kw: mock_orchestrator,
            "get_control_registry": lambda: mock_registry,
            "CheckContext": MagicMock(),
        }

        with (
            patch("darnit.tools.audit._get_sieve_components", return_value=sieve_components),
            patch("darnit.tools.audit._register_toml_controls", return_value=0),
            patch("darnit.tools.audit.get_excluded_control_ids", return_value={}),
            patch("darnit.core.discovery.get_default_implementation", return_value=None),
        ):
            from darnit.tools.audit import run_sieve_audit

            results, summary = run_sieve_audit(
                owner="test-owner",
                repo="test-repo",
                local_path=str(temp_git_repo),
                default_branch="main",
                level=1,
            )

        # Verify the cache was written (in temp dir, not repo)
        cache_path = _get_cache_dir(str(temp_git_repo)) / CACHE_FILENAME
        assert cache_path.exists(), "run_sieve_audit should write audit cache"

        with open(cache_path) as f:
            data = json.load(f)

        assert data["version"] == CACHE_VERSION
        assert data["level"] == 1
        assert data["results"] == results
        assert data["summary"] == summary
        assert data["commit"] is not None
