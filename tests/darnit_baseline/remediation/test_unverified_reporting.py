"""Tests for Issue #797: unverified controls reporting when no control fails.

Verifies that remediate_audit_findings and run_remediation never claim
"all controls are passing" when unverified controls (ERROR, WARN, PENDING)
exist in scope, upholding Darnit Constitution Principle II.
"""

from unittest.mock import MagicMock, patch

from darnit_baseline.remediation.orchestrator import (
    _format_no_failures_report,
    remediate_audit_findings,
    run_remediation,
)


class TestFormatNoFailuresReport:
    """Direct unit tests for _format_no_failures_report helper."""

    def test_empty_results_returns_all_passing(self):
        report = _format_no_failures_report([])
        assert report.markdown == "No remediations needed - all controls are passing."

    def test_all_pass_returns_all_passing(self):
        results = [
            {"id": "OSPS-AC-01.01", "status": "PASS"},
            {"id": "OSPS-AC-01.02", "status": "PASS"},
        ]
        report = _format_no_failures_report(results)
        assert report.markdown == "No remediations needed - all controls are passing."

    def test_honored_na_returns_all_passing(self):
        results = [
            {"id": "OSPS-AC-01.01", "status": "PASS"},
            {
                "id": "OSPS-DO-01.01",
                "status": "N/A",
                "assertion": {"outcome": "honored", "reason": "No releases"},
            },
        ]
        report = _format_no_failures_report(results)
        assert report.markdown == "No remediations needed - all controls are passing."

    def test_unhonored_na_pending_treated_as_unverified(self):
        results = [
            {"id": "OSPS-AC-01.01", "status": "PASS"},
            {
                "id": "OSPS-DO-01.01",
                "status": "N/A",
                "assertion": {"outcome": "pending", "reason": "Unreviewed claim"},
            },
        ]
        report = _format_no_failures_report(results)
        assert "all controls are passing" not in report.markdown
        assert "1 control(s) could not be verified (1 PENDING):" in report.markdown
        assert "- **PENDING (1):** Awaiting model judgment or confirmation" in report.markdown

    def test_unhonored_na_contradicted_treated_as_unverified(self):
        results = [
            {"id": "OSPS-AC-01.01", "status": "PASS"},
            {
                "id": "OSPS-DO-01.01",
                "status": "N/A",
                "assertion": {"outcome": "contradicted", "reason": "Evidence contradicts claim"},
            },
        ]
        report = _format_no_failures_report(results)
        assert "all controls are passing" not in report.markdown
        assert "1 control(s) could not be verified (1 PENDING):" in report.markdown

    def test_single_error_shows_cause(self):
        results = [
            {"id": "OSPS-AC-01.01", "status": "PASS"},
            {
                "id": "OSPS-AC-02.01",
                "status": "ERROR",
                "error_class": "PlatformError",
                "details": "API timeout",
            },
        ]
        report = _format_no_failures_report(results)
        assert "all controls are passing" not in report.markdown
        assert "1 control(s) could not be verified (1 ERROR):" in report.markdown
        assert "- **ERROR (1):** could not measure. 1 PlatformError, e.g. OSPS-AC-02.01: API timeout" in report.markdown

    def test_error_shows_details_and_actionable_fix(self):
        results = [
            {
                "id": "OSPS-AC-01.01",
                "status": "ERROR",
                "error_class": "unavailable",
                "details": (
                    "Platform API call /orgs/darnitdevorg could not be measured (unavailable): "
                    "To get started with GitHub CLI, please run: gh auth login"
                ),
            },
        ]
        report = _format_no_failures_report(results)
        assert (
            "- **ERROR (1):** could not measure. 1 unavailable, e.g. OSPS-AC-01.01: "
            "Platform API call /orgs/darnitdevorg could not be measured (unavailable): "
            "To get started with GitHub CLI, please run: gh auth login"
        ) in report.markdown

    def test_multiline_details_normalized_in_error_line(self):
        results = [
            {
                "id": "OSPS-AC-01.01",
                "status": "ERROR",
                "error_class": "unavailable",
                "details": "Line one.\nLine two.\n  Line three.",
            },
        ]
        report = _format_no_failures_report(results)
        assert "- **ERROR (1):** could not measure. 1 unavailable, e.g. OSPS-AC-01.01: Line one. Line two. Line three." in report.markdown

    def test_empty_details_formats_without_trailing_colon(self):
        results = [
            {
                "id": "OSPS-AC-01.01",
                "status": "ERROR",
                "error_class": "unavailable",
                "details": "",
            },
        ]
        report = _format_no_failures_report(results)
        assert "- **ERROR (1):** could not measure. 1 unavailable, e.g. OSPS-AC-01.01" in report.markdown
        assert "OSPS-AC-01.01:" not in report.markdown

    def test_multiple_error_causes_picks_most_common(self):
        results = [
            {"id": f"ERR-A-{i}", "status": "ERROR", "error_class": "AuthError", "details": "bad auth"}
            for i in range(5)
        ] + [
            {"id": f"ERR-B-{i}", "status": "ERROR", "error_class": "NetworkError", "details": "timeout"}
            for i in range(2)
        ]
        report = _format_no_failures_report(results)
        assert "- **ERROR (7):** could not measure. 5 AuthError, 2 NetworkError, e.g. ERR-A-0: bad auth" in report.markdown

    def test_warn_and_pending_only_no_errors(self):
        results = [
            {"id": "OSPS-AC-01.01", "status": "PASS"},
            {"id": "OSPS-VM-01.01", "status": "WARN"},
            {"id": "OSPS-SA-03.02", "status": "PENDING"},
        ]
        report = _format_no_failures_report(results)
        assert "2 control(s) could not be verified (1 WARN, 1 PENDING):" in report.markdown
        assert "ERROR" not in report.markdown
        assert "- **WARN (1):** Could not automatically verify - manual verification required" in report.markdown
        assert "- **PENDING (1):** Awaiting model judgment or confirmation" in report.markdown

    def test_exact_issue_797_reproduction(self):
        """Exact counts from Issue #797 filed by mlieberman85:

        5 PASS, 2 N/A, 18 ERROR, 14 WARN, 27 PENDING. Total: 66 controls, 59 unverified.
        """
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
            {"id": f"WARN-{i}", "status": "WARN"} for i in range(14)
        ] + [
            {"id": f"PENDING-{i}", "status": "PENDING"} for i in range(27)
        ]

        report = _format_no_failures_report(results)
        text = report.markdown

        assert "all controls are passing" not in text
        assert "Nothing to remediate: no control failed." in text
        assert "59 control(s) could not be verified (18 ERROR, 14 WARN, 27 PENDING):" in text
        assert (
            "- **ERROR (18):** could not measure. 18 unavailable, e.g. OSPS-AC-00.01: "
            "Platform API call /orgs/darnitdevorg could not be measured (unavailable): "
            "To get started with GitHub CLI, please run: gh auth login"
        ) in text
        assert "- **WARN (14):** Could not automatically verify - manual verification required" in text
        assert "- **PENDING (27):** Awaiting model judgment or confirmation" in text
        assert "Automated remediation applies only to failing controls. Unverified controls are non-compliant until verified." in text

    def test_allowed_ids_scoping(self):
        results = [
            {"id": "OSPS-AC-01.01", "status": "ERROR", "error_class": "evaluation"},
            {"id": "OSPS-DO-01.01", "status": "PASS"},
        ]
        # Scope to documentation only
        report = _format_no_failures_report(results, allowed_ids=["OSPS-DO-01.01"])
        assert report.markdown == "No remediations needed - all controls are passing."

        # Scope to access control only
        report_ac = _format_no_failures_report(results, allowed_ids=["OSPS-AC-01.01"])
        assert "1 control(s) could not be verified (1 ERROR):" in report_ac.markdown

    def test_profile_ids_scoping(self):
        results = [
            {"id": "OSPS-AC-01.01", "status": "ERROR", "error_class": "evaluation"},
            {"id": "OSPS-DO-01.01", "status": "PASS"},
        ]
        # Profile containing only PASS control
        report = _format_no_failures_report(results, profile_ids={"OSPS-DO-01.01"})
        assert report.markdown == "No remediations needed - all controls are passing."


class TestRunRemediationUnverifiedIntegration:
    """Integration unit tests through run_remediation and remediate_audit_findings."""

    def test_cache_hit_unverified_returns_breakdown(self, tmp_path):
        cache_data = {
            "version": 1,
            "timestamp": "2026-02-16T12:00:00Z",
            "commit": "abc123",
            "commit_dirty": False,
            "level": 3,
            "framework": "openssf-baseline",
            "results": [
                {"id": "OSPS-AC-01.01", "status": "PASS"},
                {"id": "OSPS-VM-01.01", "status": "WARN"},
            ],
            "summary": {"PASS": 1, "FAIL": 0, "WARN": 1, "N/A": 0, "ERROR": 0, "total": 2},
        }

        with (
            patch("darnit.core.audit_cache.read_audit_cache", return_value=cache_data),
            patch("darnit_baseline.remediation.orchestrator.validate_local_path", return_value=(str(tmp_path), None)),
            patch("darnit.core.utils.detect_owner_repo", return_value=("testorg", "testrepo")),
        ):
            report = run_remediation(local_path=str(tmp_path), dry_run=True)
            assert "all controls are passing" not in report.markdown
            assert "1 control(s) could not be verified (1 WARN):" in report.markdown

    def test_cache_miss_unverified_returns_breakdown(self, tmp_path):
        mock_audit = MagicMock()
        mock_audit.all_results = [
            {"id": "OSPS-AC-01.01", "status": "PASS"},
            {
                "id": "OSPS-AC-02.01",
                "status": "ERROR",
                "error_class": "evaluation",
                "message": "Token missing",
            },
        ]

        with (
            patch("darnit.core.audit_cache.read_audit_cache", return_value=None),
            patch("darnit_baseline.remediation.orchestrator.validate_local_path", return_value=(str(tmp_path), None)),
            patch("darnit.core.utils.detect_owner_repo", return_value=("testorg", "testrepo")),
            patch("darnit_baseline.remediation.orchestrator._run_baseline_checks", return_value=(mock_audit, None)),
        ):
            report_str = remediate_audit_findings(local_path=str(tmp_path), dry_run=True)
            assert "all controls are passing" not in report_str
            assert "1 control(s) could not be verified (1 ERROR):" in report_str
            assert "- **ERROR (1):** could not measure. 1 evaluation, e.g. OSPS-AC-02.01: Token missing" in report_str
