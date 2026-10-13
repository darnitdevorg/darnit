"""Tests for darnit.core.audit_cache module."""

import concurrent.futures
import json
import subprocess
from datetime import UTC, datetime, timedelta
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
    def test_write_then_read(self, temp_git_repo: Path, sample_results, sample_summary):
        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 3, "openssf-baseline")

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
    def test_creates_cache_directory(self, temp_git_repo: Path, sample_results, sample_summary):
        cache_dir = _get_cache_dir(str(temp_git_repo))
        assert not cache_dir.exists()

        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 1, "test")

        assert cache_dir.is_dir()
        assert (cache_dir / CACHE_FILENAME).is_file()

    @pytest.mark.unit
    def test_no_files_in_repo_dir(self, temp_git_repo: Path, sample_results, sample_summary):
        """Cache should be written to temp dir, not the repo itself."""
        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 1, "test")
        assert not (temp_git_repo / ".darnit").exists()

    @pytest.mark.unit
    def test_envelope_structure(self, temp_git_repo: Path, sample_results, sample_summary):
        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 2, "test-fw")
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
    def test_stale_after_new_commit(self, temp_git_repo: Path, sample_results, sample_summary):
        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 3, "test")

        # Make a new commit
        (temp_git_repo / "change.txt").write_text("change")
        subprocess.run(["git", "add", "."], cwd=temp_git_repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "new commit"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True,
        )

        assert read_audit_cache(str(temp_git_repo)) is None

    @pytest.mark.unit
    def test_stale_when_tree_becomes_dirty(self, temp_git_repo: Path, sample_results, sample_summary):
        # Write cache with clean tree
        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 3, "test")
        assert read_audit_cache(str(temp_git_repo)) is not None

        # Make tree dirty
        (temp_git_repo / "uncommitted.txt").write_text("dirty")

        assert read_audit_cache(str(temp_git_repo)) is None

    @pytest.mark.unit
    def test_stale_when_tree_becomes_clean(self, temp_git_repo: Path, sample_results, sample_summary):
        # Make tree dirty, then write cache
        dirty_file = temp_git_repo / "dirty.txt"
        dirty_file.write_text("dirty")

        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 3, "test")
        assert read_audit_cache(str(temp_git_repo)) is not None

        # Clean up the tree (add + commit)
        subprocess.run(["git", "add", "."], cwd=temp_git_repo, capture_output=True, check=True)
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
    def test_write_with_null_commit(self, temp_dir: Path, sample_results, sample_summary):
        write_audit_cache(str(temp_dir), sample_results, sample_summary, 1, "test")

        cache_path = _get_cache_dir(str(temp_dir)) / CACHE_FILENAME
        with open(cache_path) as f:
            data = json.load(f)

        assert data["commit"] is None

    @pytest.mark.unit
    def test_null_commit_always_stale(self, temp_dir: Path, sample_results, sample_summary):
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
    def test_unknown_version(self, temp_git_repo: Path, sample_results, sample_summary):
        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 3, "test")

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
    def test_invalidate_existing(self, temp_git_repo: Path, sample_results, sample_summary):
        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 3, "test")
        cache_path = _get_cache_dir(str(temp_git_repo)) / CACHE_FILENAME
        assert cache_path.exists()

        invalidate_audit_cache(str(temp_git_repo))
        # Feature 035 clarify Q3: invalidation writes an expired envelope
        # rather than deleting the file (AuditCacheStore has no delete()).
        # The file remains on disk with a 1970-01-01 timestamp; the
        # observable behavior is that the next read misses on TTL.
        assert cache_path.exists()
        assert read_audit_cache(str(temp_git_repo)) is None

    @pytest.mark.unit
    def test_invalidate_missing_noop(self, temp_git_repo: Path):
        # Should not raise
        invalidate_audit_cache(str(temp_git_repo))

    @pytest.mark.unit
    def test_read_after_invalidate_returns_none(self, temp_git_repo: Path, sample_results, sample_summary):
        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 3, "test")
        invalidate_audit_cache(str(temp_git_repo))
        assert read_audit_cache(str(temp_git_repo)) is None


class TestAtomicWrite:
    """Tests for atomic write behavior."""

    @pytest.mark.unit
    def test_no_partial_file_on_error(self, temp_git_repo: Path, sample_results, sample_summary):
        """A failing store.write is swallowed with a warning; no partial file.

        Feature 035 FR-007 relaxed the pre-feature "raises on tempfile/rename
        failure" behavior to feature-033 FR-011's best-effort semantics: log
        and continue. The 'no partial file' invariant is now enforced by
        FilesystemAuditCacheStore's tempfile-then-rename + tempfile cleanup.
        """
        # Patch the underlying store's write to raise. The wrapper MUST
        # swallow it (no raise) and no cache file should exist afterwards.
        with patch(
            "darnit.stores.defaults.cache.FilesystemAuditCacheStore.write",
            side_effect=OSError("disk full"),
        ):
            # Must NOT raise (FR-007).
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
    def test_overwrite_existing_cache(self, temp_git_repo: Path, sample_results, sample_summary):
        """Writing twice overwrites the first cache atomically."""
        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 1, "first")
        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 2, "second")

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


class TestTTL:
    """Tests for TTL expiry functionality."""

    @pytest.mark.unit
    def test_cache_hit_within_ttl(self, temp_git_repo: Path, sample_results, sample_summary):
        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 1, "test")
        assert read_audit_cache(str(temp_git_repo), ttl_seconds=3600) is not None

    @pytest.mark.unit
    def test_cache_miss_after_ttl_expires(self, temp_git_repo: Path, sample_results, sample_summary):
        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 1, "test")

        # Manually alter the timestamp to be expired
        cache_path = _get_cache_dir(str(temp_git_repo)) / CACHE_FILENAME
        with open(cache_path) as f:
            data = json.load(f)

        old_time = datetime.now(UTC) - timedelta(seconds=4000)
        data["timestamp"] = old_time.isoformat()

        with open(cache_path, "w") as f:
            json.dump(data, f)

        assert read_audit_cache(str(temp_git_repo), ttl_seconds=3600) is None

    @pytest.mark.unit
    def test_invalid_timestamp_format(self, temp_git_repo: Path, sample_results, sample_summary):
        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 1, "test")

        cache_path = _get_cache_dir(str(temp_git_repo)) / CACHE_FILENAME
        with open(cache_path) as f:
            data = json.load(f)

        data["timestamp"] = "not-a-timestamp"

        with open(cache_path, "w") as f:
            json.dump(data, f)

        assert read_audit_cache(str(temp_git_repo), ttl_seconds=3600) is None

    @pytest.mark.unit
    def test_missing_timestamp(self, temp_git_repo: Path, sample_results, sample_summary):
        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 1, "test")

        cache_path = _get_cache_dir(str(temp_git_repo)) / CACHE_FILENAME
        with open(cache_path) as f:
            data = json.load(f)

        del data["timestamp"]

        with open(cache_path, "w") as f:
            json.dump(data, f)

        assert read_audit_cache(str(temp_git_repo), ttl_seconds=3600) is None


class TestConcurrency:
    """Tests for thread safety and concurrency edge cases."""

    @pytest.mark.unit
    def test_concurrent_writes_and_reads(self, temp_git_repo: Path, sample_results, sample_summary):
        """Simulate heavy parallel execution to guarantee atomic swap boundaries and catch json corruption."""
        repo_path_str = str(temp_git_repo)

        def worker(thread_id):
            # Sometimes read, sometimes write
            if thread_id % 3 == 0:
                write_audit_cache(repo_path_str, sample_results, sample_summary, thread_id, f"test-{thread_id}")
            else:
                data = read_audit_cache(repo_path_str)
                # It's okay if data is None because of our tight timing,
                # but if data is returned, it should NOT crash parsing JSON
                if data is not None:
                    assert "version" in data
            return True

        # Initial write to establish cache
        write_audit_cache(repo_path_str, sample_results, sample_summary, 0, "test-0")

        num_threads = 30
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, i) for i in range(num_threads)]
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())

        assert len(results) == num_threads
        assert all(results)

        # Final read works
        final_data = read_audit_cache(repo_path_str)
        assert final_data is not None
        assert final_data["version"] == CACHE_VERSION


class TestScopeMismatch:
    """Issue #542: a cache from a narrower audit must not satisfy a wider read."""

    def test_framework_mismatch_is_a_miss(self, temp_git_repo, sample_results, sample_summary):
        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 3, "openssf-baseline")
        assert read_audit_cache(str(temp_git_repo), expected_framework="openssf-baseline") is not None
        assert read_audit_cache(str(temp_git_repo), expected_framework="amber") is None

    def test_level_mismatch_is_a_miss(self, temp_git_repo, sample_results, sample_summary):
        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 1, "openssf-baseline")
        assert read_audit_cache(str(temp_git_repo), expected_level=1) is not None
        assert read_audit_cache(str(temp_git_repo), expected_level=3) is None

    def test_unscoped_read_still_hits(self, temp_git_repo, sample_results, sample_summary):
        """Existing callers that pass no expectations are unaffected."""
        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 1, "amber")
        assert read_audit_cache(str(temp_git_repo)) is not None


class TestCacheVersion:
    """Review on #549: an envelope written before the scope fix must miss.

    Version 1 envelopes could hold a filtered audit under the full-audit key.
    """

    def test_old_version_envelope_is_a_miss(self, temp_git_repo, sample_results, sample_summary):
        write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 3, "openssf-baseline")
        cache_path = _get_cache_dir(str(temp_git_repo)) / CACHE_FILENAME
        data = json.loads(cache_path.read_text())
        data["version"] = 1
        cache_path.write_text(json.dumps(data))
        assert read_audit_cache(str(temp_git_repo)) is None


class TestFilteredDecision:
    """Whether run_sieve_audit treats an audit as filtered, and so does not cache it (#542)."""

    @pytest.mark.parametrize(
        ("tags", "controls", "cache_filtered", "expected"),
        [
            (None, None, None, False),  # darnit loads the controls: a full audit
            (["domain=VM"], None, None, True),
            (None, ["c"], None, True),  # caller's own list, not declared: fail closed
            (None, ["c"], False, False),  # caller says it is the full set
            (None, ["c"], True, True),  # caller says it narrowed, e.g. a profile
            (["level=1"], ["c"], False, True),  # tags win over "not filtered"
        ],
    )
    def test_is_filtered(self, tags, controls, cache_filtered, expected):
        from darnit.tools.audit import _is_filtered

        assert _is_filtered(tags, controls, cache_filtered) is expected

    def test_one_key_per_repository(self):
        from darnit.tools.audit import audit_cache_key

        assert audit_cache_key("/repo", None) == "audit-cache"


def _write_full_audit(repo, results, summary, *, level=3, framework="openssf-baseline"):
    """Write the way run_sieve_audit does: through the resolved store, under the shared key."""
    from darnit.stores.selection import resolve_stores
    from darnit.tools.audit import audit_cache_key

    bundle = resolve_stores(None, repo_path=Path(repo))
    try:
        write_audit_cache(
            str(repo),
            results,
            summary,
            level,
            framework,
            store=bundle.cache,
            cache_key=audit_cache_key(str(repo), None),
        )
    finally:
        bundle.close_all()


def _read_full_audit(repo):
    from darnit.tools.audit import read_full_audit_cache

    return read_full_audit_cache(str(repo), "openssf-baseline", level=3)


class TestFullAuditCacheRead:
    """read_full_audit_cache is what remediation reads (#542)."""

    def test_full_audit_is_a_hit(self, temp_git_repo, sample_results, sample_summary):
        _write_full_audit(temp_git_repo, sample_results, sample_summary)
        assert _read_full_audit(temp_git_repo) is not None

    def test_level_1_audit_is_a_miss(self, temp_git_repo, sample_results, sample_summary):
        _write_full_audit(temp_git_repo, sample_results, sample_summary, level=1)
        assert _read_full_audit(temp_git_repo) is None

    def test_other_framework_is_a_miss(self, temp_git_repo, sample_results, sample_summary):
        _write_full_audit(temp_git_repo, sample_results, sample_summary, framework="gittuf")
        assert _read_full_audit(temp_git_repo) is None


class TestFullAuditCacheInvalidation:
    """invalidate_full_audit_cache expires what read_full_audit_cache reads (review on #549)."""

    def test_invalidated_cache_is_a_miss(self, temp_git_repo, sample_results, sample_summary):
        from darnit.tools.audit import invalidate_full_audit_cache

        _write_full_audit(temp_git_repo, sample_results, sample_summary)
        assert _read_full_audit(temp_git_repo) is not None
        invalidate_full_audit_cache(str(temp_git_repo), "openssf-baseline")
        assert _read_full_audit(temp_git_repo) is None

    def test_configured_store_is_invalidated(
        self, temp_git_repo, tmp_path_factory, monkeypatch, sample_results, sample_summary
    ):
        """Review on #549: with ``[stores.cache]`` set, the configured entry must expire.

        The plain ``invalidate_audit_cache(path)`` expires the default store's
        entry and leaves the configured one, so remediation kept reading the
        audit from before its own change.
        """
        from darnit.config.framework_schema import StoreBlock, StoresConfig
        from darnit.core.audit_cache import invalidate_audit_cache
        from darnit.stores.selection import resolve_stores
        from darnit.tools.audit import audit_cache_key, invalidate_full_audit_cache

        root = tmp_path_factory.mktemp("configured-cache")
        stores = StoresConfig(cache=StoreBlock(backend="local-fs", root=str(root)))
        monkeypatch.setattr("darnit.tools.audit._load_merged_stores", lambda *args, **kwargs: stores)

        bundle = resolve_stores(stores, repo_path=Path(temp_git_repo))
        try:
            write_audit_cache(
                str(temp_git_repo),
                sample_results,
                sample_summary,
                3,
                "openssf-baseline",
                store=bundle.cache,
                cache_key=audit_cache_key(str(temp_git_repo), stores),
            )
        finally:
            bundle.close_all()
        assert list(root.glob("*.json")), "the audit should be cached in the configured store"
        assert _read_full_audit(temp_git_repo) is not None

        invalidate_audit_cache(str(temp_git_repo))
        assert _read_full_audit(temp_git_repo) is not None, "the default-store call does not reach it"

        invalidate_full_audit_cache(str(temp_git_repo), "openssf-baseline")
        assert _read_full_audit(temp_git_repo) is None
