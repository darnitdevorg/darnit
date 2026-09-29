"""Tests for _get_next_steps_section in audit.py.

Verifies the Next Steps section generation:
- Dynamic step numbering based on what's applicable
- Context collection directed to the get_pending_data wizard
- Removal of legacy "Help Improve This Audit" section
"""

from unittest.mock import patch

from darnit.config.context_schema import (
    ContextDefinition,
    ContextPromptRequest,
    ContextType,
    ContextValue,
)
from darnit.tools.audit import _get_next_steps_section


def _make_pending(
    key: str,
    prompt: str,
    *,
    auto_value: object | None = None,
    detection_method: str | None = None,
    values: list[str] | None = None,
    hint: str | None = None,
) -> ContextPromptRequest:
    """Helper to create a ContextPromptRequest for testing."""
    current_value = None
    if auto_value is not None:
        current_value = ContextValue.auto_detected(
            value=auto_value,
            method=detection_method or "test_detection",
        )
    return ContextPromptRequest(
        key=key,
        definition=ContextDefinition(
            type=ContextType.STRING,
            prompt=prompt,
            values=values,
            hint=hint,
        ),
        control_ids=["TEST-01"],
        current_value=current_value,
        priority=1,
    )


class TestGetNextStepsSection:
    """Tests for _get_next_steps_section()."""

    @patch("darnit.config.context_storage.get_pending_context")
    def test_pending_context_and_failures_produces_context_then_remediation(
        self, mock_get_pending
    ):
        """3.1: Pending context + failures → context as step 1, remediation as step 2.
        Verify get_pending_context() directive appears. Verify 'Help Improve This Audit' absent.
        """
        pending = [
            _make_pending("ci_provider", "CI provider?", auto_value="github"),
        ]
        mock_get_pending.return_value = pending
        summary = {"PASS": 5, "FAIL": 3, "WARN": 0, "ERROR": 0}

        result = _get_next_steps_section("/repo", summary)
        output = "\n".join(result)

        # Step 1 is context collection
        assert "Step 1: Confirm project context" in output
        # Step 2 is remediation
        assert "Step 2: Remediate failures" in output
        # Directs to get_pending_context (not direct confirm_project_context dump)
        assert "get_pending_data(" in output
        # Legacy section is gone
        assert "Help Improve This Audit" not in output

    @patch("darnit.config.context_storage.get_pending_context")
    def test_failures_no_pending_context_starts_with_remediation(
        self, mock_get_pending
    ):
        """3.2: Failures but no pending context → starts with remediation."""
        mock_get_pending.return_value = []
        summary = {"PASS": 10, "FAIL": 5, "WARN": 0, "ERROR": 0}

        result = _get_next_steps_section("/repo", summary)
        output = "\n".join(result)

        # Step 1 is remediation (no context step)
        assert "Step 1: Remediate failures" in output
        assert "Confirm project context" not in output

    @patch("darnit.config.context_storage.get_pending_context")
    def test_all_passing_no_pending_context_produces_no_section(
        self, mock_get_pending
    ):
        """3.3: All passing + no pending context → no Next Steps section."""
        mock_get_pending.return_value = []
        summary = {"PASS": 20, "FAIL": 0, "WARN": 0, "ERROR": 0}

        result = _get_next_steps_section("/repo", summary)

        assert result == []

    @patch("darnit.config.context_storage.get_pending_context")
    def test_context_step_directs_to_get_pending_context(
        self, mock_get_pending
    ):
        """3.5: Context collection step directs to get_pending_context wizard."""
        pending = [
            _make_pending("maintainers", "Who maintains?", auto_value=["@alice"]),
        ]
        mock_get_pending.return_value = pending
        summary = {"PASS": 5, "FAIL": 2, "WARN": 0, "ERROR": 0}

        result = _get_next_steps_section("/repo", summary)
        output = "\n".join(result)

        assert "get_pending_data(" in output
        assert "one at a time" in output.lower()

    @patch("darnit.config.context_storage.get_pending_context")
    def test_warnings_only_produces_manual_review_step(self, mock_get_pending):
        """Warnings only → single manual review step."""
        mock_get_pending.return_value = []
        summary = {"PASS": 15, "FAIL": 0, "WARN": 3, "ERROR": 0}

        result = _get_next_steps_section("/repo", summary)
        output = "\n".join(result)

        assert "Step 1: Review manual controls" in output
        assert "3 controls need verification" in output

    @patch("darnit.config.context_storage.get_pending_context")
    def test_all_three_steps_present(self, mock_get_pending):
        """Context + failures + warnings → 3 numbered steps."""
        pending = [
            _make_pending("ci_provider", "CI?", auto_value="github"),
        ]
        mock_get_pending.return_value = pending
        summary = {"PASS": 5, "FAIL": 3, "WARN": 2, "ERROR": 0}

        result = _get_next_steps_section("/repo", summary)
        output = "\n".join(result)

        assert "Step 1: Confirm project context" in output
        assert "Step 2: Remediate failures" in output
        assert "Step 3: Review manual controls" in output

    def test_no_local_path_skips_context_check(self):
        """local_path=None → no context lookup, only failures/warnings."""
        summary = {"PASS": 5, "FAIL": 3, "WARN": 0, "ERROR": 0}

        result = _get_next_steps_section(None, summary)
        output = "\n".join(result)

        assert "Step 1: Remediate failures" in output
        assert "Confirm project context" not in output
