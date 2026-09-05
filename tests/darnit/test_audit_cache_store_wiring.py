"""Feature 035 driver-level integration for the audit-cache store wiring.

Locks the three properties that were broken before this feature:

* Operator's ``[stores.cache] backend = "local-fs" root = "..."`` config
  actually redirects the on-disk cache path (US1).
* Zero-config default still lands cache at
  ``<tempdir>/darnit/<hash>/audit-cache.json`` (US2, invariance).
* Staleness detection (TTL / commit / dirty) still fires through a
  configured store (US3).
* Public API keeps working with positional-only backward-compat call
  form (US4).
* Store write failures do not propagate to the audit's exit code (US3
  fault-injection).

The tests use a mocked SieveOrchestrator so they exercise the driver's
cache-write code path without needing a real framework registered.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from darnit.config.framework_schema import StoreBlock, StoresConfig
from darnit.core.audit_cache import (
    CACHE_FILENAME,
    CACHE_VERSION,
    _get_cache_dir,
    read_audit_cache,
    write_audit_cache,
)
from darnit.stores.defaults import FilesystemAuditCacheStore
from darnit.stores.defaults.local_fs import LocalFsAuditCacheStore

# ---------------------------------------------------------------------------
# Shared mocks for run_sieve_audit
# ---------------------------------------------------------------------------


def _mock_sieve_components() -> dict:
    """Return the minimum sieve components a mocked audit needs."""
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

    return {
        "SieveOrchestrator": lambda **kw: mock_orchestrator,
        "get_control_registry": lambda: mock_registry,
        "CheckContext": MagicMock(),
    }


def _run_audit_with_stores_config(repo: Path, stores_config: StoresConfig | None):
    """Invoke ``run_sieve_audit`` with a mocked orchestrator + injected stores.

    Patches ``_load_merged_stores`` to return ``stores_config`` (so we
    bypass the framework-registration step) and ``_register_toml_controls``
    plus ``get_excluded_control_ids`` per the existing test pattern.
    """
    with (
        patch(
            "darnit.tools.audit._get_sieve_components",
            return_value=_mock_sieve_components(),
        ),
        patch("darnit.tools.audit._register_toml_controls", return_value=0),
        patch("darnit.tools.audit.get_excluded_control_ids", return_value={}),
        patch(
            "darnit.tools.audit._load_merged_stores",
            return_value=stores_config,
        ),
        patch("darnit.config.load_user_config", return_value=None),
    ):
        from darnit.tools.audit import run_sieve_audit

        return run_sieve_audit(
            owner="test-owner",
            repo="test-repo",
            local_path=str(repo),
            default_branch="main",
            level=1,
        )


def _repo_hash(repo: Path) -> str:
    return hashlib.sha256(str(repo.resolve()).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# US1: local-fs backend routing
# ---------------------------------------------------------------------------


class TestLocalFsBackendRouting:
    """SC-001, SC-006 -- configured store redirects the cache path."""

    @pytest.mark.unit
    def test_config_moves_cache_to_configured_root(self, temp_git_repo: Path, tmp_path: Path):
        """Cache file lands under configured root, not the tempdir."""
        cache_root = tmp_path / "cache-out"
        stores_config = StoresConfig(cache=StoreBlock(backend="local-fs", root=str(cache_root)))

        _run_audit_with_stores_config(temp_git_repo, stores_config)

        expected_file = cache_root / f"{_repo_hash(temp_git_repo)}.json"
        assert expected_file.exists(), (
            f"cache file should land at {expected_file} "
            f"but did not. cache_root contents: "
            f"{list(cache_root.iterdir()) if cache_root.exists() else 'no dir'}"
        )
        # No fallback file in the default tempdir location.
        default_dir = _get_cache_dir(str(temp_git_repo))
        assert not (default_dir / CACHE_FILENAME).exists(), (
            "cache should NOT land in default tempdir when [stores.cache] is configured"
        )

    @pytest.mark.unit
    def test_second_run_reads_cache_via_configured_store(self, temp_git_repo: Path, tmp_path: Path):
        """Run 2 finds run 1's cache under the configured root (SC-001)."""
        cache_root = tmp_path / "cache-out"
        stores_config = StoresConfig(cache=StoreBlock(backend="local-fs", root=str(cache_root)))

        run1_results, run1_summary = _run_audit_with_stores_config(temp_git_repo, stores_config)

        # Read the cache the same way the remediate tool would: build a
        # matching store and pass the same cache_key the driver used.
        store = LocalFsAuditCacheStore(root=str(cache_root))
        cache_key = _repo_hash(temp_git_repo)
        envelope = read_audit_cache(str(temp_git_repo), store=store, cache_key=cache_key)
        assert envelope is not None, "read should HIT the configured-root cache written by run 1"
        assert envelope["results"] == run1_results
        assert envelope["summary"] == run1_summary

    @pytest.mark.unit
    def test_shared_root_does_not_collide(self, tmp_path: Path):
        """Two repos sharing one configured root do not overwrite (SC-006)."""
        shared_root = tmp_path / "shared-cache"

        # Two independent repos.
        repo_a = tmp_path / "repo-a"
        repo_b = tmp_path / "repo-b"
        for repo in (repo_a, repo_b):
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=repo,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo,
                capture_output=True,
                check=True,
            )
            (repo / "README.md").write_text("# " + repo.name + "\n")
            subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=repo,
                capture_output=True,
                check=True,
            )

        stores_config = StoresConfig(cache=StoreBlock(backend="local-fs", root=str(shared_root)))

        _run_audit_with_stores_config(repo_a, stores_config)
        _run_audit_with_stores_config(repo_b, stores_config)

        hash_a = _repo_hash(repo_a)
        hash_b = _repo_hash(repo_b)
        assert hash_a != hash_b, "distinct repos MUST hash to distinct keys"
        assert (shared_root / f"{hash_a}.json").exists()
        assert (shared_root / f"{hash_b}.json").exists()


# ---------------------------------------------------------------------------
# US2: zero-config default preserved
# ---------------------------------------------------------------------------


class TestZeroConfigInvariance:
    """FR-010, SC-002 -- no [stores.*] block means legacy tempdir path."""

    @pytest.mark.unit
    def test_no_baseline_toml_lands_at_legacy_tempdir_path(self, temp_git_repo: Path, tmp_path: Path):
        """Zero-config audit lands cache at pre-feature-035 path shape."""
        _run_audit_with_stores_config(temp_git_repo, stores_config=None)

        legacy_dir = _get_cache_dir(str(temp_git_repo))
        legacy_file = legacy_dir / CACHE_FILENAME
        assert legacy_file.exists(), (
            f"zero-config cache should land at {legacy_file}, "
            f"tempdir tree: {list(legacy_dir.iterdir()) if legacy_dir.exists() else 'no dir'}"
        )
        # Confirm no leakage into the operator's working area.
        assert not (temp_git_repo / ".darnit" / "audit-cache").exists(), (
            "zero-config MUST NOT write into <repo>/.darnit/audit-cache"
        )


# ---------------------------------------------------------------------------
# US3: staleness through a configured store
# ---------------------------------------------------------------------------


class TestStalenessThroughConfiguredStore:
    """SC-004, SC-005 -- HEAD change / dirty tree still invalidate cache."""

    @pytest.mark.unit
    def test_head_change_invalidates_configured_cache(self, temp_git_repo: Path, tmp_path: Path):
        """A new commit between runs forces a fresh envelope (SC-004)."""
        cache_root = tmp_path / "cache-out"
        stores_config = StoresConfig(cache=StoreBlock(backend="local-fs", root=str(cache_root)))

        _run_audit_with_stores_config(temp_git_repo, stores_config)

        store = LocalFsAuditCacheStore(root=str(cache_root))
        cache_key = _repo_hash(temp_git_repo)

        envelope_run1 = read_audit_cache(str(temp_git_repo), store=store, cache_key=cache_key)
        assert envelope_run1 is not None
        run1_commit = envelope_run1["commit"]

        # Advance HEAD.
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "advance HEAD"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True,
        )

        # Read via wrapper -- staleness fires, returns None.
        envelope_after_head = read_audit_cache(str(temp_git_repo), store=store, cache_key=cache_key)
        assert envelope_after_head is None, "cache MUST miss after HEAD change (SC-004)"

        # Run 2 rewrites the envelope with the new commit.
        _run_audit_with_stores_config(temp_git_repo, stores_config)
        envelope_run2 = read_audit_cache(str(temp_git_repo), store=store, cache_key=cache_key)
        assert envelope_run2 is not None
        assert envelope_run2["commit"] != run1_commit, "run 2 envelope MUST reflect the new HEAD"

    @pytest.mark.unit
    def test_dirty_state_change_invalidates_configured_cache(self, temp_git_repo: Path, tmp_path: Path):
        """Dirtying the tree between runs forces a fresh envelope (SC-005)."""
        cache_root = tmp_path / "cache-out"
        stores_config = StoresConfig(cache=StoreBlock(backend="local-fs", root=str(cache_root)))

        _run_audit_with_stores_config(temp_git_repo, stores_config)

        store = LocalFsAuditCacheStore(root=str(cache_root))
        cache_key = _repo_hash(temp_git_repo)

        envelope_run1 = read_audit_cache(str(temp_git_repo), store=store, cache_key=cache_key)
        assert envelope_run1 is not None
        assert envelope_run1["commit_dirty"] is False

        # Dirty the tree.
        (temp_git_repo / "uncommitted.txt").write_text("dirty\n")

        envelope_after_dirty = read_audit_cache(str(temp_git_repo), store=store, cache_key=cache_key)
        assert envelope_after_dirty is None, "cache MUST miss after tree becomes dirty (SC-005)"

        _run_audit_with_stores_config(temp_git_repo, stores_config)
        envelope_run2 = read_audit_cache(str(temp_git_repo), store=store, cache_key=cache_key)
        assert envelope_run2 is not None
        assert envelope_run2["commit_dirty"] is True


# ---------------------------------------------------------------------------
# US3 (bonus): fault injection
# ---------------------------------------------------------------------------


class TestFaultInjection:
    """SC-007 -- store.write failures MUST NOT propagate."""

    @pytest.mark.unit
    def test_store_write_failure_does_not_propagate(self, temp_git_repo: Path, caplog):
        """A raising store.write is swallowed with a warning log."""
        import logging

        class RaisingStore:
            def read(self, cache_key: str):
                return None

            def write(self, cache_key: str, envelope: dict) -> None:
                raise OSError("simulated disk full")

            def close(self) -> None:
                return None

        # Must not raise. Wrap in try/except to also verify no OSError
        # leaks through.
        raised: Exception | None = None
        with caplog.at_level(logging.WARNING, logger="darnit.core.audit_cache"):
            try:
                write_audit_cache(
                    str(temp_git_repo),
                    [{"id": "TEST", "status": "PASS", "details": "OK", "level": 1}],
                    {"PASS": 1, "FAIL": 0, "WARN": 0, "N/A": 0, "ERROR": 0, "total": 1},
                    1,
                    "test-fw",
                    store=RaisingStore(),
                    cache_key="audit-cache",
                )
            except Exception as exc:  # pragma: no cover -- assertion below
                raised = exc

        assert raised is None, f"write_audit_cache MUST NOT propagate store errors, got {raised!r}"
        # Warning line captured.
        assert any("audit cache write failed" in rec.message for rec in caplog.records), (
            "expected a warning log line about the cache write failure"
        )


# ---------------------------------------------------------------------------
# US4: backward-compat call form (positional-only)
# ---------------------------------------------------------------------------


class TestBackwardCompatCallForm:
    """FR-002, FR-011 -- external positional callers keep working."""

    @pytest.mark.unit
    def test_positional_write_uses_legacy_tempdir_path(self, temp_git_repo: Path):
        write_audit_cache(
            str(temp_git_repo),
            [{"id": "T", "status": "PASS", "details": "OK", "level": 1}],
            {"PASS": 1, "FAIL": 0, "WARN": 0, "N/A": 0, "ERROR": 0, "total": 1},
            1,
            "test-fw",
        )
        expected = _get_cache_dir(str(temp_git_repo)) / CACHE_FILENAME
        assert expected.exists(), "positional write MUST land at the legacy tempdir path"

    @pytest.mark.unit
    def test_positional_read_after_positional_write_hits(self, temp_git_repo: Path):
        results = [{"id": "T", "status": "PASS", "details": "OK", "level": 1}]
        summary = {"PASS": 1, "FAIL": 0, "WARN": 0, "N/A": 0, "ERROR": 0, "total": 1}
        write_audit_cache(str(temp_git_repo), results, summary, 1, "test-fw")
        envelope = read_audit_cache(str(temp_git_repo))
        assert envelope is not None
        assert envelope["version"] == CACHE_VERSION
        assert envelope["results"] == results
        assert envelope["summary"] == summary

    @pytest.mark.unit
    def test_partial_kwarg_store_only_raises_type_error(self, temp_git_repo: Path, tmp_path: Path):
        store = FilesystemAuditCacheStore(root=tmp_path / "root")
        with pytest.raises(TypeError, match="store and cache_key"):
            write_audit_cache(
                str(temp_git_repo),
                [],
                {"PASS": 0, "FAIL": 0, "WARN": 0, "N/A": 0, "ERROR": 0, "total": 0},
                1,
                "test-fw",
                store=store,
                cache_key=None,
            )

    @pytest.mark.unit
    def test_partial_kwarg_cache_key_only_raises_type_error(self, temp_git_repo: Path):
        with pytest.raises(TypeError, match="store and cache_key"):
            write_audit_cache(
                str(temp_git_repo),
                [],
                {"PASS": 0, "FAIL": 0, "WARN": 0, "N/A": 0, "ERROR": 0, "total": 0},
                1,
                "test-fw",
                store=None,
                cache_key="foo",
            )
