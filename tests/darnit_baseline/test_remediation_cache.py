"""Tests for remediate_audit_findings() cache integration.

Verifies that the orchestrator:
- Uses cached audit results when available (cache hit)
- Falls back to _run_baseline_checks when cache is missing (cache miss)
- Only remediates FAIL controls (WARN/PASS are excluded)
- Invalidates cache after applying changes (non-dry-run)
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def cached_results():
    """Cache envelope with mixed PASS/FAIL/WARN results."""
    return {
        "version": 1,
        "timestamp": "2026-02-16T12:00:00Z",
        "commit": "abc123",
        "commit_dirty": False,
        "level": 3,
        "framework": "openssf-baseline",
        "results": [
            {"id": "OSPS-AC-01.01", "status": "PASS", "details": "OK", "level": 1},
            {"id": "OSPS-DO-02.01", "status": "FAIL", "details": "Missing", "level": 1},
            {"id": "OSPS-DO-03.01", "status": "FAIL", "details": "Missing", "level": 1},
            {"id": "OSPS-VM-01.01", "status": "WARN", "details": "Manual", "level": 1},
        ],
        "summary": {"PASS": 1, "FAIL": 2, "WARN": 1, "N/A": 0, "ERROR": 0, "total": 4},
    }


class TestOrchestratorCacheHit:
    """When cache has valid results, skip _run_baseline_checks."""

    def test_cache_hit_skips_audit(self, tmp_path, cached_results):
        """With a cache hit, _run_baseline_checks should NOT be called."""
        run_checks_mock = MagicMock()
        apply_mock = MagicMock(
            return_value={"status": "would_apply", "category": "support_doc"},
        )

        with (
            patch(
                "darnit.core.audit_cache.read_audit_cache",
                return_value=cached_results,
            ),
            patch(
                "darnit_baseline.remediation.orchestrator.validate_local_path",
                return_value=(str(tmp_path), None),
            ),
            patch(
                "darnit.core.utils.detect_owner_repo",
                return_value=("testorg", "testrepo"),
            ),
            patch(
                "darnit_baseline.remediation.orchestrator._run_baseline_checks",
                run_checks_mock,
            ),
            patch(
                "darnit_baseline.remediation.orchestrator._preflight_context_check",
                return_value=(True, {}),
            ),
            patch(
                "darnit_baseline.remediation.orchestrator._apply_remediation",
                apply_mock,
            ),
        ):
            from darnit_baseline.remediation.orchestrator import remediate_audit_findings

            remediate_audit_findings(
                local_path=str(tmp_path),
                dry_run=True,
            )

            # _run_baseline_checks should NOT have been called
            run_checks_mock.assert_not_called()

    def test_cache_hit_passes_only_fail_ids(self, tmp_path, cached_results):
        """Cache hit should pass only FAIL IDs (not WARN) to _apply_remediation."""
        apply_mock = MagicMock(
            return_value={"status": "would_apply", "category": "test"},
        )

        with (
            patch(
                "darnit.core.audit_cache.read_audit_cache",
                return_value=cached_results,
            ),
            patch(
                "darnit_baseline.remediation.orchestrator.validate_local_path",
                return_value=(str(tmp_path), None),
            ),
            patch(
                "darnit.core.utils.detect_owner_repo",
                return_value=("testorg", "testrepo"),
            ),
            patch(
                "darnit_baseline.remediation.orchestrator._preflight_context_check",
                return_value=(True, {}),
            ),
            patch(
                "darnit_baseline.remediation.orchestrator._apply_remediation",
                apply_mock,
            ),
        ):
            from darnit_baseline.remediation.orchestrator import remediate_audit_findings

            remediate_audit_findings(
                local_path=str(tmp_path),
                dry_run=True,
            )

            # Every call to _apply_remediation should receive only FAIL IDs
            for call in apply_mock.call_args_list:
                passed_ids = call.kwargs.get("non_passing_ids") or call[1].get(
                    "non_passing_ids"
                )
                assert passed_ids == {"OSPS-DO-02.01", "OSPS-DO-03.01"}, (
                    f"Expected only FAIL IDs, got {passed_ids}"
                )
                # WARN control should NOT be included
                assert "OSPS-VM-01.01" not in passed_ids


class TestOrchestratorCacheMiss:
    """When no cache exists, fall back to _run_baseline_checks."""

    def test_cache_miss_runs_audit(self, tmp_path):
        """With no cache, _run_baseline_checks SHOULD be called."""
        mock_audit_result = MagicMock()
        mock_audit_result.all_results = [
            {"id": "OSPS-DO-02.01", "status": "FAIL", "details": "Missing"},
        ]

        with (
            patch(
                "darnit.core.audit_cache.read_audit_cache",
                return_value=None,
            ),
            patch(
                "darnit_baseline.remediation.orchestrator.validate_local_path",
                return_value=(str(tmp_path), None),
            ),
            patch(
                "darnit.core.utils.detect_owner_repo",
                return_value=("testorg", "testrepo"),
            ),
            patch(
                "darnit_baseline.remediation.orchestrator._run_baseline_checks",
                return_value=(mock_audit_result, None),
            ) as run_checks_mock,
            patch(
                "darnit_baseline.remediation.orchestrator._preflight_context_check",
                return_value=(True, {}),
            ),
            patch(
                "darnit_baseline.remediation.orchestrator._apply_remediation",
                return_value={"status": "would_apply", "category": "support_doc"},
            ),
        ):
            from darnit_baseline.remediation.orchestrator import remediate_audit_findings

            remediate_audit_findings(
                local_path=str(tmp_path),
                dry_run=True,
            )

            run_checks_mock.assert_called_once()

    def test_cache_miss_filters_to_fail_only(self, tmp_path):
        """Cache miss path should also filter to FAIL-only (not WARN)."""
        mock_audit_result = MagicMock()
        mock_audit_result.all_results = [
            {"id": "OSPS-DO-02.01", "status": "FAIL", "details": "Missing"},
            {"id": "OSPS-VM-01.01", "status": "WARN", "details": "Manual"},
            {"id": "OSPS-AC-01.01", "status": "PASS", "details": "OK"},
        ]

        apply_mock = MagicMock(
            return_value={"status": "would_apply", "category": "test"},
        )

        with (
            patch(
                "darnit.core.audit_cache.read_audit_cache",
                return_value=None,
            ),
            patch(
                "darnit_baseline.remediation.orchestrator.validate_local_path",
                return_value=(str(tmp_path), None),
            ),
            patch(
                "darnit.core.utils.detect_owner_repo",
                return_value=("testorg", "testrepo"),
            ),
            patch(
                "darnit_baseline.remediation.orchestrator._run_baseline_checks",
                return_value=(mock_audit_result, None),
            ),
            patch(
                "darnit_baseline.remediation.orchestrator._preflight_context_check",
                return_value=(True, {}),
            ),
            patch(
                "darnit_baseline.remediation.orchestrator._apply_remediation",
                apply_mock,
            ),
        ):
            from darnit_baseline.remediation.orchestrator import remediate_audit_findings

            remediate_audit_findings(
                local_path=str(tmp_path),
                dry_run=True,
            )

            for call in apply_mock.call_args_list:
                passed_ids = call.kwargs.get("non_passing_ids") or call[1].get(
                    "non_passing_ids"
                )
                assert passed_ids == {"OSPS-DO-02.01"}
                assert "OSPS-VM-01.01" not in passed_ids


class TestOrchestratorCacheInvalidation:
    """Cache invalidation after applying changes."""

    def test_invalidates_after_applied_changes(self, tmp_path, cached_results):
        """Non-dry-run with applied remediations should invalidate cache."""
        invalidate_mock = MagicMock()

        with (
            patch(
                "darnit.core.audit_cache.read_audit_cache",
                return_value=cached_results,
            ),
            patch(
                "darnit.core.audit_cache.invalidate_audit_cache",
                invalidate_mock,
            ),
            patch(
                "darnit_baseline.remediation.orchestrator.validate_local_path",
                return_value=(str(tmp_path), None),
            ),
            patch(
                "darnit.core.utils.detect_owner_repo",
                return_value=("testorg", "testrepo"),
            ),
            patch(
                "darnit_baseline.remediation.orchestrator._preflight_context_check",
                return_value=(True, {}),
            ),
            patch(
                "darnit_baseline.remediation.orchestrator._apply_remediation",
                return_value={"status": "applied", "category": "support_doc"},
            ),
        ):
            from darnit_baseline.remediation.orchestrator import remediate_audit_findings

            remediate_audit_findings(
                local_path=str(tmp_path),
                dry_run=False,
            )

            invalidate_mock.assert_called_once()

    def test_dry_run_preserves_cache(self, tmp_path, cached_results):
        """Dry run should NOT invalidate cache."""
        invalidate_mock = MagicMock()

        with (
            patch(
                "darnit.core.audit_cache.read_audit_cache",
                return_value=cached_results,
            ),
            patch(
                "darnit.core.audit_cache.invalidate_audit_cache",
                invalidate_mock,
            ),
            patch(
                "darnit_baseline.remediation.orchestrator.validate_local_path",
                return_value=(str(tmp_path), None),
            ),
            patch(
                "darnit.core.utils.detect_owner_repo",
                return_value=("testorg", "testrepo"),
            ),
            patch(
                "darnit_baseline.remediation.orchestrator._preflight_context_check",
                return_value=(True, {}),
            ),
            patch(
                "darnit_baseline.remediation.orchestrator._apply_remediation",
                return_value={"status": "would_apply", "category": "support_doc"},
            ),
        ):
            from darnit_baseline.remediation.orchestrator import remediate_audit_findings

            remediate_audit_findings(
                local_path=str(tmp_path),
                dry_run=True,
            )

            invalidate_mock.assert_not_called()
