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
            return_value={"status": "would_apply", "control_id": "OSPS-DO-02.01"},
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
                "darnit_baseline.remediation.orchestrator._apply_control_remediation",
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

    def test_cache_hit_only_remediates_fail_controls(self, tmp_path, cached_results):
        """Cache hit should only call _apply_control_remediation for FAIL IDs."""
        apply_mock = MagicMock(
            return_value={"status": "would_apply", "control_id": "test"},
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
                "darnit_baseline.remediation.orchestrator._apply_control_remediation",
                apply_mock,
            ),
        ):
            from darnit_baseline.remediation.orchestrator import remediate_audit_findings

            remediate_audit_findings(
                local_path=str(tmp_path),
                dry_run=True,
            )

            # Only FAIL controls should have been remediated
            remediated_ids = {
                call.kwargs.get("control_id") or call[1].get("control_id")
                for call in apply_mock.call_args_list
            }
            # PASS control should NOT be included
            assert "OSPS-AC-01.01" not in remediated_ids
            # WARN control should NOT be included
            assert "OSPS-VM-01.01" not in remediated_ids
            # FAIL controls with remediation handlers should be included
            # (only if they have TOML remediation defined)
            for cid in remediated_ids:
                assert cid in {"OSPS-DO-02.01", "OSPS-DO-03.01"}, \
                    f"Unexpected control remediated: {cid}"


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
                "darnit_baseline.remediation.orchestrator._apply_control_remediation",
                return_value={"status": "would_apply", "control_id": "OSPS-DO-02.01"},
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
            return_value={"status": "would_apply", "control_id": "test"},
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
                "darnit_baseline.remediation.orchestrator._apply_control_remediation",
                apply_mock,
            ),
        ):
            from darnit_baseline.remediation.orchestrator import remediate_audit_findings

            remediate_audit_findings(
                local_path=str(tmp_path),
                dry_run=True,
            )

            remediated_ids = {
                call.kwargs.get("control_id") or call[1].get("control_id")
                for call in apply_mock.call_args_list
            }
            assert "OSPS-VM-01.01" not in remediated_ids
            assert "OSPS-AC-01.01" not in remediated_ids


class TestOrchestratorCacheTargetScope:
    """Issue #659: remediation passes its target to read_full_audit_cache."""

    def test_remediation_passes_target_to_cache_read(self, tmp_path):
        from darnit_baseline.remediation.orchestrator import run_remediation

        mock_read = MagicMock(return_value=None)
        mock_audit_result = MagicMock()
        mock_audit_result.all_results = []

        with (
            patch("darnit.tools.audit.read_full_audit_cache", mock_read),
            patch("darnit_baseline.remediation.orchestrator.validate_local_path", return_value=(str(tmp_path), None)),
            patch("darnit.core.utils.detect_owner_repo", return_value=("testorg", "testrepo")),
            patch("darnit_baseline.remediation.orchestrator._run_baseline_checks", return_value=(mock_audit_result, None)),
            patch("darnit_baseline.remediation.orchestrator._preflight_context_check", return_value=(True, {})),
        ):
            run_remediation(local_path=str(tmp_path), target="github.com/testorg/testrepo")
            mock_read.assert_called_once_with(str(tmp_path), "openssf-baseline", level=3, target="github.com/testorg/testrepo")


class TestOrchestratorCacheInvalidation:
    """Cache invalidation after applying changes."""

    def test_invalidates_after_applied_changes(self, tmp_path, cached_results):
        """An apply that wrote a file invalidates the cache.

        Feature 043 FR-019: the decision comes from the applied file changes,
        not from an "applied" status (which a remediation that changed
        nothing also reports).
        """
        invalidate_mock = MagicMock()
        written = {"path": "SECURITY.md", "action": "create", "content": "# Security\n"}

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
                "darnit_baseline.remediation.orchestrator._apply_control_remediation",
                return_value={"status": "applied", "control_id": "OSPS-DO-02.01", "file_changes": [written]},
            ),
            patch("darnit_baseline.remediation.orchestrator._recheck", return_value={}),
        ):
            from darnit_baseline.remediation.orchestrator import remediate_audit_findings

            remediate_audit_findings(
                local_path=str(tmp_path),
                dry_run=False,
            )

            invalidate_mock.assert_called_once()

    def test_apply_that_changed_nothing_keeps_cache(self, tmp_path, cached_results):
        """An "applied" status with no written file is not a change (feature 043 FR-019)."""
        invalidate_mock = MagicMock()
        unchanged = {"path": "SECURITY.md", "action": "none", "reason": "already_exists"}

        with (
            patch("darnit.core.audit_cache.read_audit_cache", return_value=cached_results),
            patch("darnit.core.audit_cache.invalidate_audit_cache", invalidate_mock),
            patch(
                "darnit_baseline.remediation.orchestrator.validate_local_path",
                return_value=(str(tmp_path), None),
            ),
            patch("darnit.core.utils.detect_owner_repo", return_value=("testorg", "testrepo")),
            patch(
                "darnit_baseline.remediation.orchestrator._preflight_context_check",
                return_value=(True, {}),
            ),
            patch(
                "darnit_baseline.remediation.orchestrator._apply_control_remediation",
                return_value={"status": "applied", "control_id": "OSPS-DO-02.01", "file_changes": [unchanged]},
            ),
        ):
            from darnit_baseline.remediation.orchestrator import remediate_audit_findings

            remediate_audit_findings(local_path=str(tmp_path), dry_run=False)

            invalidate_mock.assert_not_called()

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
                "darnit_baseline.remediation.orchestrator._apply_control_remediation",
                return_value={"status": "would_apply", "control_id": "OSPS-DO-02.01"},
            ),
        ):
            from darnit_baseline.remediation.orchestrator import remediate_audit_findings

            remediate_audit_findings(
                local_path=str(tmp_path),
                dry_run=True,
            )

            invalidate_mock.assert_not_called()


class TestOneCreationPerPathAcrossControls:
    """The orchestrator builds one executor per control; the run's claim map is shared between them (#755)."""

    def test_every_control_gets_the_same_claim_map(self, tmp_path, cached_results):
        apply_mock = MagicMock(return_value={"status": "would_apply", "control_id": "test"})
        with (
            patch("darnit.core.audit_cache.read_audit_cache", return_value=cached_results),
            patch(
                "darnit_baseline.remediation.orchestrator.validate_local_path",
                return_value=(str(tmp_path), None),
            ),
            patch("darnit.core.utils.detect_owner_repo", return_value=("testorg", "testrepo")),
            patch("darnit_baseline.remediation.orchestrator._preflight_context_check", return_value=(True, {})),
            patch("darnit_baseline.remediation.orchestrator._apply_control_remediation", apply_mock),
        ):
            from darnit_baseline.remediation.orchestrator import remediate_audit_findings

            remediate_audit_findings(local_path=str(tmp_path), dry_run=True)
        maps = [call.kwargs["claimed_paths"] for call in apply_mock.call_args_list]
        assert len(maps) >= 2 and all(m is maps[0] for m in maps), "one dict for the whole run"

    def test_the_map_reaches_the_executor(self, tmp_path):
        """_apply_control_remediation hands the run's map to the executor it builds."""
        from darnit.remediation.executor import RemediationExecutor
        from darnit_baseline.remediation import orchestrator

        claims: dict[str, str] = {}
        seen: dict[str, object] = {}
        real_init = RemediationExecutor.__init__

        def spy_init(self, *args, **kwargs):
            seen["claimed_paths"] = kwargs.get("claimed_paths")
            real_init(self, *args, **kwargs)

        with patch.object(RemediationExecutor, "__init__", spy_init):
            orchestrator._apply_control_remediation(
                "OSPS-DO-03.01", str(tmp_path), owner="o", repo="r", dry_run=True, claimed_paths=claims
            )
        assert seen.get("claimed_paths") is claims


class TestOrchestratorNoFailuresReporting:
    """Issue #797: report unverified controls instead of 'all passing' when no control fails."""

    def test_all_passing_reports_all_controls_are_passing(self, tmp_path):
        """When every control in scope is PASS or honored N/A, report all passing."""
        cache_data = {
            "version": 1,
            "timestamp": "2026-02-16T12:00:00Z",
            "commit": "abc123",
            "commit_dirty": False,
            "level": 3,
            "framework": "openssf-baseline",
            "results": [
                {"id": "OSPS-AC-01.01", "status": "PASS", "details": "OK"},
                {"id": "OSPS-AC-01.02", "status": "PASS", "details": "OK"},
                {
                    "id": "OSPS-DO-01.01",
                    "status": "N/A",
                    "assertion": {"outcome": "honored", "reason": "No releases"},
                },
            ],
            "summary": {"PASS": 2, "FAIL": 0, "WARN": 0, "N/A": 1, "ERROR": 0, "total": 3},
        }

        with (
            patch("darnit.core.audit_cache.read_audit_cache", return_value=cache_data),
            patch("darnit_baseline.remediation.orchestrator.validate_local_path", return_value=(str(tmp_path), None)),
            patch("darnit.core.utils.detect_owner_repo", return_value=("testorg", "testrepo")),
        ):
            from darnit_baseline.remediation.orchestrator import remediate_audit_findings

            report = remediate_audit_findings(local_path=str(tmp_path), dry_run=True)
            assert "No remediations needed - all controls are passing." in report

    def test_unverified_controls_without_failures_reports_breakdown(self, tmp_path):
        """When 0 controls fail but unverified controls exist, report accurate breakdown."""
        # Exact reproduction of Issue #797:
        # 5 PASS, 2 N/A (honored), 18 ERROR, 14 WARN, 27 PENDING = 66 controls
        results = [
            {"id": f"PASS-{i}", "status": "PASS"} for i in range(5)
        ] + [
            {"id": f"NA-{i}", "status": "N/A", "assertion": {"outcome": "honored"}} for i in range(2)
        ] + [
            {
                "id": f"OSPS-AC-0{i}.01",
                "status": "ERROR",
                "error_class": "unavailable",
                "details": (
                    "Platform API call /orgs/darnitdevorg could not be measured (unavailable): "
                    "To get started with GitHub CLI, please run: gh auth login"
                ),
            }
            for i in range(18)
        ] + [
            {"id": f"WARN-{i}", "status": "WARN", "details": "Manual review needed"} for i in range(14)
        ] + [
            {"id": f"PENDING-{i}", "status": "PENDING", "details": "Awaiting model"} for i in range(27)
        ]

        cache_data = {
            "version": 1,
            "timestamp": "2026-02-16T12:00:00Z",
            "commit": "abc123",
            "commit_dirty": False,
            "level": 3,
            "framework": "openssf-baseline",
            "results": results,
            "summary": {"PASS": 5, "FAIL": 0, "WARN": 14, "N/A": 2, "ERROR": 18, "PENDING": 27, "total": 66},
        }

        with (
            patch("darnit.core.audit_cache.read_audit_cache", return_value=cache_data),
            patch("darnit_baseline.remediation.orchestrator.validate_local_path", return_value=(str(tmp_path), None)),
            patch("darnit.core.utils.detect_owner_repo", return_value=("testorg", "testrepo")),
        ):
            from darnit_baseline.remediation.orchestrator import remediate_audit_findings

            report = remediate_audit_findings(local_path=str(tmp_path), dry_run=True)

            # Must NOT claim all controls are passing
            assert "all controls are passing" not in report
            # Must state no controls failed
            assert "Nothing to remediate: no control failed." in report
            # Must report total unverified count and breakdown
            assert "59 control(s) could not be verified (18 ERROR, 14 WARN, 27 PENDING):" in report
            assert (
                "- **ERROR (18):** could not measure. 18 unavailable, e.g. OSPS-AC-00.01: "
                "Platform API call /orgs/darnitdevorg could not be measured (unavailable): "
                "To get started with GitHub CLI, please run: gh auth login"
            ) in report
            assert "- **WARN (14):** Could not automatically verify - manual verification required" in report
            assert "- **PENDING (27):** Awaiting model judgment or confirmation" in report
            # Must state Principle II notice
            assert "Automated remediation applies only to failing controls. Unverified controls are non-compliant until verified." in report

    def test_unhonored_na_claim_counted_as_unverified(self, tmp_path):
        """Pending or contradicted N/A assertions are treated as unverified (Feature 040)."""
        cache_data = {
            "version": 1,
            "timestamp": "2026-02-16T12:00:00Z",
            "commit": "abc123",
            "commit_dirty": False,
            "level": 3,
            "framework": "openssf-baseline",
            "results": [
                {"id": "OSPS-AC-01.01", "status": "PASS"},
                {
                    "id": "OSPS-DO-01.01",
                    "status": "N/A",
                    "assertion": {"outcome": "pending", "reason": "Self-assertion unreviewed"},
                },
            ],
            "summary": {"PASS": 1, "FAIL": 0, "WARN": 0, "N/A": 1, "ERROR": 0, "total": 2},
        }

        with (
            patch("darnit.core.audit_cache.read_audit_cache", return_value=cache_data),
            patch("darnit_baseline.remediation.orchestrator.validate_local_path", return_value=(str(tmp_path), None)),
            patch("darnit.core.utils.detect_owner_repo", return_value=("testorg", "testrepo")),
        ):
            from darnit_baseline.remediation.orchestrator import remediate_audit_findings

            report = remediate_audit_findings(local_path=str(tmp_path), dry_run=True)

            assert "all controls are passing" not in report
            assert "1 control(s) could not be verified (1 PENDING):" in report
            assert "- **PENDING (1):** Awaiting model judgment or confirmation" in report

    def test_category_filter_scopes_unverified_reporting(self, tmp_path):
        """Category filtering should restrict unverified checks to in-scope controls."""
        cache_data = {
            "version": 1,
            "timestamp": "2026-02-16T12:00:00Z",
            "commit": "abc123",
            "commit_dirty": False,
            "level": 3,
            "framework": "openssf-baseline",
            "results": [
                # Access control: 1 ERROR
                {"id": "OSPS-AC-01.01", "status": "ERROR", "error_class": "evaluation", "message": "No token"},
                # Documentation: 1 PASS
                {"id": "OSPS-DO-01.01", "status": "PASS"},
            ],
            "summary": {"PASS": 1, "FAIL": 0, "WARN": 0, "N/A": 0, "ERROR": 1, "total": 2},
        }

        with (
            patch("darnit.core.audit_cache.read_audit_cache", return_value=cache_data),
            patch("darnit_baseline.remediation.orchestrator.validate_local_path", return_value=(str(tmp_path), None)),
            patch("darnit.core.utils.detect_owner_repo", return_value=("testorg", "testrepo")),
        ):
            from darnit_baseline.remediation.orchestrator import remediate_audit_findings

            # When filtering to documentation (which is PASS), it reports all passing for that scope
            report_doc = remediate_audit_findings(
                local_path=str(tmp_path),
                categories=["documentation"],
                dry_run=True,
            )
            assert "No remediations needed - all controls are passing." in report_doc

            # When filtering to access_control (which has ERROR), it reports unverified for that scope
            report_ac = remediate_audit_findings(
                local_path=str(tmp_path),
                categories=["access_control"],
                dry_run=True,
            )
            assert "all controls are passing" not in report_ac
            assert "1 control(s) could not be verified (1 ERROR):" in report_ac
            assert "- **ERROR (1):** could not measure. 1 evaluation, e.g. OSPS-AC-01.01: No token" in report_ac
