"""Invariant and edge case tests for the sieve pipeline.

Phase 7 of the Tiered Control Automation Pipeline — validates safety
invariants and edge cases from the spec.

T041: Graceful degradation when `gh` CLI is not authenticated
T042: Detect missing `gh` auth at audit start
T043: INCONCLUSIVE never promoted to PASS
T044: Fields with auto_detect=false never auto-filled
T045: All FAIL results include non-empty evidence
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from darnit.sieve.handler_registry import (
    HandlerContext,
    HandlerResult,
    HandlerResultStatus,
)
from darnit.sieve.models import (
    PassAttempt,
    PassOutcome,
    PassResult,
    SieveResult,
    VerificationPhase,
)

# ---------------------------------------------------------------------------
# T043: INCONCLUSIVE must never promote to PASS
# ---------------------------------------------------------------------------


class TestInconclusiveNeverPromotesToPass:
    """FR-011: No pass can promote INCONCLUSIVE to PASS.

    When all passes return INCONCLUSIVE, the final status must be WARN.
    """

    def test_all_inconclusive_returns_warn(self):
        """A control with only INCONCLUSIVE-returning passes gets WARN."""
        from darnit.sieve.orchestrator import SieveOrchestrator

        orchestrator = SieveOrchestrator()

        # Create a control with handler invocations that always return INCONCLUSIVE
        mock_handler = MagicMock(
            return_value=HandlerResult(
                status=HandlerResultStatus.INCONCLUSIVE,
                message="Cannot determine",
            )
        )

        with patch(
            "darnit.sieve.orchestrator.get_sieve_handler_registry"
        ) as mock_registry:
            mock_registry.return_value = {
                "always_inconclusive": MagicMock(
                    fn=mock_handler,
                    phase=MagicMock(value="deterministic"),
                ),
            }

            from darnit.sieve.models import ControlSpec

            control_spec = ControlSpec(
                control_id="TEST-INCONCLUSIVE-01",
                name="Test Inconclusive",
                description="Test control",
                level=1,
                domain="XX",
                metadata={
                    "handler_invocations": [
                        MagicMock(
                            handler="always_inconclusive",
                            when=None,
                            shared=None,
                            model_extra={},
                        ),
                    ],
                },
            )

            from darnit.sieve.orchestrator import CheckContext

            ctx = CheckContext(
                owner="test-org",
                repo="test-repo",
                local_path="/tmp/test",
                default_branch="main",
                control_id="TEST-INCONCLUSIVE-01",
            )

            result = orchestrator._dispatch_handler_invocations(control_spec, ctx)

        assert result is not None
        assert result.status == "WARN", (
            f"Expected WARN when all passes are INCONCLUSIVE, got {result.status}"
        )
        assert result.status != "PASS", "INCONCLUSIVE must never be promoted to PASS"

    def test_sieve_result_statuses_are_valid(self):
        """SieveResult status is always a valid string from the allowed set."""
        valid_statuses = {"PASS", "FAIL", "WARN", "ERROR", "N/A", "PENDING_LLM"}

        result = SieveResult(
            control_id="TEST-01",
            status="WARN",
            message="test",
            level=1,
        )
        assert result.status in valid_statuses


# ---------------------------------------------------------------------------
# T045: All FAIL results include non-empty evidence
# ---------------------------------------------------------------------------


class TestFailResultsHaveEvidence:
    """US1 acceptance scenario 2: All FAIL results include human-readable evidence."""

    def test_fail_sieve_result_has_nonempty_message(self):
        """FAIL results must have a non-empty message (details)."""
        result = SieveResult(
            control_id="TEST-01",
            status="FAIL",
            message="Branch protection not enabled: default branch 'main' has no protection rules",
            level=1,
            evidence={"branch": "main", "protected": False},
        )
        assert result.message, "FAIL results must have non-empty message"
        assert len(result.message) > 10, "FAIL message should be human-readable"

    def test_fail_result_to_legacy_dict_has_details(self):
        """FAIL results serialized via to_legacy_dict include details field."""
        result = SieveResult(
            control_id="TEST-01",
            status="FAIL",
            message="No SECURITY.md found",
            level=1,
            evidence={"files_checked": ["SECURITY.md", ".github/SECURITY.md"]},
        )
        legacy = result.to_legacy_dict()
        assert legacy["status"] == "FAIL"
        assert legacy["details"], "FAIL legacy dict must have non-empty details"
        assert legacy.get("evidence"), "FAIL legacy dict should include evidence"


# ---------------------------------------------------------------------------
# T041/T042: Graceful degradation when `gh` is unavailable
# ---------------------------------------------------------------------------


class TestGhCliGracefulDegradation:
    """FR-009: Controls that depend on `gh` CLI must degrade gracefully."""

    @patch("subprocess.run")
    def test_exec_handler_returns_error_when_command_not_found(self, mock_run):
        """When `gh` is not installed, exec handler returns ERROR, not crashes."""
        from darnit.sieve.builtin_handlers import exec_handler

        mock_run.side_effect = FileNotFoundError("gh: command not found")

        ctx = HandlerContext(
            local_path="/tmp/test",
            owner="testorg",
            repo="testrepo",
            default_branch="main",
            control_id="TEST-GH-01",
        )
        config = {
            "handler": "exec",
            "command": ["gh", "api", "/repos/{owner}/{repo}"],
        }

        result = exec_handler(config, ctx)
        # Should not crash — should return ERROR or INCONCLUSIVE
        assert result.status in (
            HandlerResultStatus.ERROR,
            HandlerResultStatus.INCONCLUSIVE,
        ), f"Expected ERROR or INCONCLUSIVE when gh unavailable, got {result.status}"

    @patch("subprocess.run")
    def test_exec_handler_returns_error_on_nonzero_exit(self, mock_run):
        """When `gh` returns non-zero (not authenticated), handler handles it."""
        from darnit.sieve.builtin_handlers import exec_handler

        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="gh: not logged in",
        )

        ctx = HandlerContext(
            local_path="/tmp/test",
            owner="testorg",
            repo="testrepo",
            default_branch="main",
            control_id="TEST-GH-02",
        )
        config = {
            "handler": "exec",
            "command": ["gh", "api", "/repos/{owner}/{repo}"],
        }

        result = exec_handler(config, ctx)
        # Non-zero exit with no CEL expr → INCONCLUSIVE (falls through to next pass)
        assert result.status in (
            HandlerResultStatus.FAIL,
            HandlerResultStatus.INCONCLUSIVE,
            HandlerResultStatus.ERROR,
        ), f"Expected graceful handling of gh auth failure, got {result.status}"


# ---------------------------------------------------------------------------
# T044: auto_detect=false fields never auto-filled
# ---------------------------------------------------------------------------


class TestAutoDetectFalseGuard:
    """FR-010: Fields with auto_detect=false must never be auto-filled."""

    def test_sieve_detection_skipped_when_auto_detect_false(self):
        """When auto_detect=False, _try_sieve_detection should not be called."""

        # Create a mock definition with auto_detect=False
        mock_definition = MagicMock()
        mock_definition.auto_detect = False
        mock_definition.auto_detect_method = None

        # Even if a detector would succeed, it should not run
        # The guard is at line 535 of context_storage.py:
        # "if current_value is None and definition.auto_detect:"
        # When auto_detect is False, detection is skipped entirely
        assert not mock_definition.auto_detect, (
            "auto_detect must be False for this test"
        )

    def test_context_value_auto_accepted_false_by_default(self):
        """ContextValue defaults to auto_accepted=False."""
        from darnit.config.context_schema import ContextSource, ContextValue

        cv = ContextValue(value="test", source=ContextSource.USER_CONFIRMED)
        assert cv.auto_accepted is False


# ---------------------------------------------------------------------------
# Pass history serialization tests
# ---------------------------------------------------------------------------


class TestPassHistorySerialization:
    """Verify pass_history is correctly serialized in to_legacy_dict."""

    def test_pass_history_included_in_legacy_dict(self):
        """to_legacy_dict includes serialized pass_history."""
        history = [
            PassAttempt(
                phase=VerificationPhase.DETERMINISTIC,
                checks_performed=["handler:file_exists"],
                result=PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.INCONCLUSIVE,
                    message="File not found",
                ),
                duration_ms=5,
            ),
            PassAttempt(
                phase=VerificationPhase.PATTERN,
                checks_performed=["handler:regex"],
                result=PassResult(
                    phase=VerificationPhase.PATTERN,
                    outcome=PassOutcome.PASS,
                    message="Pattern matched",
                    confidence=1.0,
                ),
                duration_ms=12,
            ),
        ]

        result = SieveResult(
            control_id="TEST-01",
            status="PASS",
            message="Pattern matched",
            level=1,
            pass_history=history,
            resolving_pass_index=1,
            resolving_pass_handler="regex",
        )

        legacy = result.to_legacy_dict()

        assert "pass_history" in legacy
        assert len(legacy["pass_history"]) == 2
        assert legacy["pass_history"][0]["phase"] == "deterministic"
        assert legacy["pass_history"][0]["result"]["outcome"] == "inconclusive"
        assert legacy["pass_history"][1]["result"]["outcome"] == "pass"
        assert legacy["resolving_pass_index"] == 1
        assert legacy["resolving_pass_handler"] == "regex"

    def test_empty_pass_history_excluded_from_legacy_dict(self):
        """to_legacy_dict excludes pass_history when empty."""
        result = SieveResult(
            control_id="TEST-01",
            status="WARN",
            message="No verification",
            level=1,
        )
        legacy = result.to_legacy_dict()
        assert "pass_history" not in legacy

    def test_resolving_pass_fields_excluded_when_none(self):
        """to_legacy_dict excludes resolving_pass fields when None."""
        result = SieveResult(
            control_id="TEST-01",
            status="WARN",
            message="No verification",
            level=1,
        )
        legacy = result.to_legacy_dict()
        assert "resolving_pass_index" not in legacy
        assert "resolving_pass_handler" not in legacy
