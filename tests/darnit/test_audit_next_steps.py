"""Tests for _get_next_steps_section and _format_context_collection_step in audit.py.

Verifies the Next Steps section generation:
- Dynamic step numbering based on what's applicable
- Context collection with compound tool calls for auto-detected values
- Individual prompts for unknown values
- Re-audit directive after context collection
- Removal of legacy "Help Improve This Audit" section
"""

from unittest.mock import patch

from darnit.config.context_schema import (
    ContextDefinition,
    ContextPromptRequest,
    ContextType,
    ContextValue,
)
from darnit.tools.audit import _format_context_collection_step, _get_next_steps_section


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
        assert "get_pending_context(" in output
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

        assert "get_pending_context(" in output
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


class TestFormatContextCollectionStep:
    """Tests for _format_context_collection_step()."""

    def test_auto_detected_as_compound_call_unknown_as_individual(self):
        """3.4: Auto-detected values as single compound call;
        unknown values as individual prompts with definition text.
        """
        pending = [
            _make_pending(
                "ci_provider",
                "What CI provider?",
                auto_value="github",
                detection_method="detected from .github/workflows/",
            ),
            _make_pending(
                "maintainers",
                "Who maintains?",
                auto_value=["@alice", "@bob"],
                detection_method="detected from CODEOWNERS",
            ),
            _make_pending(
                "governance_model",
                "What governance model does this project use?",
                values=[
                    "bdfl", "meritocracy", "democracy",
                    "corporate", "foundation", "committee", "other",
                ],
            ),
        ]

        result = _format_context_collection_step(1, pending, "/repo")
        output = "\n".join(result)

        # Single compound call for auto-detected values
        assert output.count("confirm_project_context(") >= 2  # compound + individual
        assert 'ci_provider="github"' in output
        assert "maintainers=" in output
        assert '"@alice"' in output
        assert '"@bob"' in output

        # Auto-detection comments
        assert "detected from .github/workflows/" in output
        assert "detected from CODEOWNERS" in output

        # Unknown value as individual prompt
        assert (
            "**governance_model**: What governance model does this project use?"
            in output
        )
        assert "`bdfl`" in output
        assert "<ask user>" in output

    def test_only_auto_detected_no_unknown_section(self):
        """All auto-detected → compound call only, no 'needs your input' section."""
        pending = [
            _make_pending("ci_provider", "CI?", auto_value="github"),
        ]

        result = _format_context_collection_step(1, pending, "/repo")
        output = "\n".join(result)

        assert "Verify and correct" in output
        assert "needs your input" not in output

    def test_only_unknown_no_compound_call(self):
        """All unknown → individual prompts, no 'auto-detected' compound section."""
        pending = [
            _make_pending(
                "governance_model",
                "Governance model?",
                values=["bdfl", "corporate"],
            ),
        ]

        result = _format_context_collection_step(1, pending, "/repo")
        output = "\n".join(result)

        assert "needs your input" in output.lower()
        assert "Verify and correct" not in output

    def test_hint_shown_for_items_without_values(self):
        """Items with hint but no values show the hint text."""
        pending = [
            _make_pending(
                "security_contact",
                "Security contact email?",
                hint="Email for vulnerability reports",
            ),
        ]

        result = _format_context_collection_step(1, pending, "/repo")
        output = "\n".join(result)

        assert "Email for vulnerability reports" in output

    def test_boolean_auto_detected_value(self):
        """Boolean auto-detected values are formatted correctly."""
        pending = [
            _make_pending(
                "has_releases", "Does project have releases?", auto_value=True
            ),
        ]

        result = _format_context_collection_step(1, pending, "/repo")
        output = "\n".join(result)

        assert "has_releases=True" in output

    def test_reaudit_directive_present(self):
        """Re-audit directive always present in context collection step."""
        pending = [
            _make_pending("ci_provider", "CI?", auto_value="github"),
        ]

        result = _format_context_collection_step(1, pending, "/repo")
        output = "\n".join(result)

        assert 'audit_openssf_baseline(local_path="/repo")' in output

    def test_overflow_indicator_when_capped(self):
        """Shows overflow indicator when pending items exceed cap of 8."""
        # Create 12 auto-detected items (cap is 8)
        pending = [
            _make_pending(f"key_{i}", f"Prompt {i}?", auto_value=f"val_{i}")
            for i in range(12)
        ]

        result = _format_context_collection_step(1, pending, "/repo")
        output = "\n".join(result)

        # Should show 8 of 12 and indicate overflow
        assert "...and 4 more" in output
        assert "get_pending_context()" in output
