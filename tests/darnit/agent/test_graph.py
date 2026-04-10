"""Tests for darnit.agent.graph — the audit/collect_context/remediate nodes.

These tests use mocking to isolate each node from its external dependencies
(prepare_audit, run_checks, RemediationExecutor, save_context_values) so they
run without a real repository or framework installation.
"""

from unittest.mock import MagicMock, patch

import pytest

from darnit.agent.graph import (
    _validate_context_answer,
    audit,
    collect_context,
    remediate,
    route,
)
from darnit.agent.state import AuditState, FeedbackQuestion

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**kwargs) -> AuditState:
    return AuditState(local_path="/repo", **kwargs)


def _make_pass_result(control_id: str, status: str) -> dict:
    return {"id": control_id, "status": status, "details": "test"}


# ---------------------------------------------------------------------------
# audit node
# ---------------------------------------------------------------------------


class TestAuditNode:
    def test_populates_audit_results_on_success(self):
        results = [
            _make_pass_result("CTRL-01", "PASS"),
            _make_pass_result("CTRL-02", "FAIL"),
        ]
        with (
            patch("darnit.agent.graph.prepare_audit") as mock_prepare,
            patch("darnit.agent.graph.run_checks") as mock_run,
        ):
            mock_prepare.return_value = ("org", "repo", "/repo", "main", None)
            mock_run.return_value = (results, {})

            state = audit(_make_state())

        assert state.audit_results == results
        assert state.error is None

    def test_sets_owner_repo_branch_from_prepare_audit(self):
        with (
            patch("darnit.agent.graph.prepare_audit") as mock_prepare,
            patch("darnit.agent.graph.run_checks") as mock_run,
        ):
            mock_prepare.return_value = ("my-org", "my-repo", "/repo", "develop", None)
            mock_run.return_value = ([], {})

            state = audit(_make_state())

        assert state.owner == "my-org"
        assert state.repo == "my-repo"
        assert state.default_branch == "develop"

    def test_sets_error_when_prepare_audit_fails(self):
        with patch("darnit.agent.graph.prepare_audit") as mock_prepare:
            mock_prepare.return_value = (None, None, "/repo", "main", "Could not detect repo")

            state = audit(_make_state())

        assert state.error == "Could not detect repo"
        assert state.audit_results == []

    def test_sets_error_when_run_checks_raises(self):
        with (
            patch("darnit.agent.graph.prepare_audit") as mock_prepare,
            patch("darnit.agent.graph.run_checks") as mock_run,
        ):
            mock_prepare.return_value = ("org", "repo", "/repo", "main", None)
            mock_run.side_effect = RuntimeError("sieve error")

            state = audit(_make_state())

        assert state.error is not None
        assert "sieve error" in state.error

    def test_passes_framework_name_to_run_checks(self):
        with (
            patch("darnit.agent.graph.prepare_audit") as mock_prepare,
            patch("darnit.agent.graph.run_checks") as mock_run,
        ):
            mock_prepare.return_value = ("org", "repo", "/repo", "main", None)
            mock_run.return_value = ([], {})

            audit(_make_state(framework_name="my-framework"))

        _, kwargs = mock_run.call_args
        assert kwargs.get("framework_name") == "my-framework"


# ---------------------------------------------------------------------------
# collect_context node — issue #145 and #146
# ---------------------------------------------------------------------------


class TestCollectContextNode:
    def test_records_answers_on_feedback_questions(self):
        state = _make_state()
        state.feedback_questions = [
            FeedbackQuestion("CTRL-01", "has_releases", "Has releases?"),
        ]

        with patch("darnit.agent.graph.save_context_values"):
            state = collect_context(state, answers={"has_releases": "yes"})

        assert state.feedback_questions[0].answered is True
        assert state.feedback_questions[0].answer == "yes"

    def test_builds_context_values_from_answers(self):
        """Issue #146: context_values must be populated so downstream nodes can read them."""
        state = _make_state()
        state.feedback_questions = [
            FeedbackQuestion("CTRL-01", "has_releases", "Q1?"),
            FeedbackQuestion("CTRL-02", "is_library", "Q2?"),
        ]

        with patch("darnit.agent.graph.save_context_values"):
            state = collect_context(
                state,
                answers={"has_releases": "yes", "is_library": "no"},
            )

        assert state.context_values == {"has_releases": "yes", "is_library": "no"}

    def test_clears_audit_results_to_trigger_reaudit(self):
        """Issue #145: audit_results must be cleared to signal a re-audit is needed."""
        state = _make_state()
        state.audit_results = [_make_pass_result("CTRL-01", "WARN")]
        state.feedback_questions = [
            FeedbackQuestion("CTRL-01", "has_releases", "Q?"),
        ]

        with patch("darnit.agent.graph.save_context_values"):
            state = collect_context(state, answers={"has_releases": "yes"})

        assert state.audit_results == []

    def test_calls_save_context_values_with_answers(self):
        """Issue #145: answers must be persisted so re-audit sees them."""
        state = _make_state()
        state.feedback_questions = [
            FeedbackQuestion("CTRL-01", "has_releases", "Q?"),
        ]

        with patch("darnit.agent.graph.save_context_values") as mock_save:
            collect_context(state, answers={"has_releases": "yes"})

        mock_save.assert_called_once_with(
            local_path="/repo",
            values={"has_releases": "yes"},
        )

    def test_noop_when_empty_answers(self):
        state = _make_state()
        state.feedback_questions = [
            FeedbackQuestion("CTRL-01", "has_releases", "Q?"),
        ]
        original_results = [_make_pass_result("CTRL-01", "WARN")]
        state.audit_results = original_results.copy()

        with patch("darnit.agent.graph.save_context_values") as mock_save:
            state = collect_context(state, answers={})

        # Nothing should change
        assert state.feedback_questions[0].answered is False
        assert state.audit_results == original_results
        mock_save.assert_not_called()

    def test_only_answered_questions_update_context_values(self):
        state = _make_state()
        q1 = FeedbackQuestion("CTRL-01", "has_releases", "Q1?")
        q2 = FeedbackQuestion("CTRL-02", "maintainers", "Q2?")
        state.feedback_questions = [q1, q2]

        with patch("darnit.agent.graph.save_context_values"):
            state = collect_context(state, answers={"has_releases": "yes"})

        assert "has_releases" in state.context_values
        assert "maintainers" not in state.context_values

    def test_does_not_crash_when_save_context_values_raises(self):
        """save_context_values failure should be non-fatal."""
        state = _make_state()
        state.feedback_questions = [
            FeedbackQuestion("CTRL-01", "has_releases", "Q?"),
        ]

        with patch("darnit.agent.graph.save_context_values", side_effect=ValueError("bad key")):
            # Should not raise
            state = collect_context(state, answers={"has_releases": "yes"})

        # context_values still set in memory even if persist failed
        assert state.context_values == {"has_releases": "yes"}

    def test_rejects_answer_with_null_byte(self):
        """Security: null bytes in answers must be rejected."""
        state = _make_state()
        state.feedback_questions = [FeedbackQuestion("CTRL-01", "path", "Q?")]

        with pytest.raises(ValueError, match="disallowed character"):
            collect_context(state, answers={"path": "safe\x00injection"})

    def test_rejects_answer_with_newline(self):
        """Security: newlines in answers must be rejected."""
        state = _make_state()
        state.feedback_questions = [FeedbackQuestion("CTRL-01", "path", "Q?")]

        with pytest.raises(ValueError, match="disallowed character"):
            collect_context(state, answers={"path": "first\nsecond"})

    def test_rejects_answer_with_shell_metacharacter(self):
        """Security: shell metacharacters in answers must be rejected."""
        state = _make_state()
        state.feedback_questions = [FeedbackQuestion("CTRL-01", "cmd", "Q?")]

        with pytest.raises(ValueError, match="disallowed character"):
            collect_context(state, answers={"cmd": "value; rm -rf /"})

    def test_accepts_safe_answer(self):
        """Paths and plain strings that are legitimately safe must be accepted."""
        state = _make_state()
        state.feedback_questions = [FeedbackQuestion("CTRL-01", "policy_path", "Q?")]

        with patch("darnit.agent.graph.save_context_values"):
            state = collect_context(state, answers={"policy_path": "docs/SECURITY.md"})

        assert state.context_values["policy_path"] == "docs/SECURITY.md"


# ---------------------------------------------------------------------------
# _validate_context_answer helper
# ---------------------------------------------------------------------------


class TestValidateContextAnswer:
    @pytest.mark.parametrize("bad_char,value", [
        ("null byte", "a\x00b"),
        ("newline", "a\nb"),
        ("carriage return", "a\rb"),
        ("semicolon", "a;b"),
        ("pipe", "a|b"),
        ("ampersand", "a&b"),
        ("dollar", "a$b"),
        ("backtick", "a`b"),
    ])
    def test_raises_on_dangerous_character(self, bad_char, value):
        with pytest.raises(ValueError, match="disallowed character"):
            _validate_context_answer("key", value)

    def test_accepts_typical_path(self):
        _validate_context_answer("policy_path", "docs/SECURITY.md")

    def test_accepts_maintainer_handle(self):
        _validate_context_answer("maintainer", "@alice")

    def test_accepts_email(self):
        _validate_context_answer("contact", "security@example.com")


# ---------------------------------------------------------------------------
# remediate node — issue #144 and #146
# ---------------------------------------------------------------------------


class TestRemediateNode:
    def _make_framework(self, control_ids_with_remediation=None):
        """Build a minimal mock FrameworkConfig."""
        framework = MagicMock()
        framework.templates = {}
        framework.controls = {}
        for ctrl_id in (control_ids_with_remediation or []):
            ctrl = MagicMock()
            ctrl.remediation = MagicMock()  # non-None remediation
            framework.controls[ctrl_id] = ctrl
        return framework

    def test_no_op_when_no_failing_controls(self):
        state = _make_state(audit_results=[_make_pass_result("CTRL-01", "PASS")])

        with patch("darnit.agent.graph._load_framework_config") as mock_fw:
            state = remediate(state)

        mock_fw.assert_not_called()
        assert state.remediation_results == []

    def test_calls_executor_for_each_failing_control(self):
        """Issue #144: RemediationExecutor.execute() must actually be called."""
        state = _make_state(
            owner="org",
            repo="repo",
            audit_results=[
                _make_pass_result("CTRL-01", "FAIL"),
                _make_pass_result("CTRL-02", "FAIL"),
            ],
        )

        framework = self._make_framework(["CTRL-01", "CTRL-02"])
        mock_result = MagicMock(success=True, message="done", dry_run=False, details={})

        with (
            patch("darnit.agent.graph._load_framework_config", return_value=framework),
            patch("darnit.agent.graph._get_framework_path", return_value=None),
            patch("darnit.agent.graph.RemediationExecutor") as MockExecutor,
        ):
            executor_instance = MockExecutor.return_value
            executor_instance.execute.return_value = mock_result

            state = remediate(state)

        assert executor_instance.execute.call_count == 2
        called_ids = [c.kwargs["control_id"] for c in executor_instance.execute.call_args_list]
        assert "CTRL-01" in called_ids
        assert "CTRL-02" in called_ids

    def test_passes_context_values_to_executor(self):
        """Issue #146: context_values from feedback must reach RemediationExecutor."""
        state = _make_state(
            owner="org",
            repo="repo",
            audit_results=[_make_pass_result("CTRL-01", "FAIL")],
            context_values={"has_releases": "yes", "is_library": "no"},
        )

        framework = self._make_framework(["CTRL-01"])
        mock_result = MagicMock(success=True, message="done", dry_run=False, details={})

        with (
            patch("darnit.agent.graph._load_framework_config", return_value=framework),
            patch("darnit.agent.graph._get_framework_path", return_value=None),
            patch("darnit.agent.graph.RemediationExecutor") as MockExecutor,
        ):
            MockExecutor.return_value.execute.return_value = mock_result
            state = remediate(state)

        _, init_kwargs = MockExecutor.call_args
        assert init_kwargs["context_values"] == {"has_releases": "yes", "is_library": "no"}

    def test_records_skipped_when_no_remediation_defined(self):
        state = _make_state(
            owner="org",
            repo="repo",
            audit_results=[_make_pass_result("CTRL-NO-REMED", "FAIL")],
        )

        framework = MagicMock()
        framework.templates = {}
        ctrl = MagicMock()
        ctrl.remediation = None  # No remediation
        framework.controls = {"CTRL-NO-REMED": ctrl}

        with (
            patch("darnit.agent.graph._load_framework_config", return_value=framework),
            patch("darnit.agent.graph._get_framework_path", return_value=None),
            patch("darnit.agent.graph.RemediationExecutor") as MockExecutor,
        ):
            state = remediate(state)

        # Execute should NOT be called
        MockExecutor.return_value.execute.assert_not_called()
        assert state.remediation_results[0]["status"] == "skipped"

    def test_handles_executor_exception_gracefully(self):
        state = _make_state(
            owner="org",
            repo="repo",
            audit_results=[_make_pass_result("CTRL-01", "FAIL")],
        )

        framework = self._make_framework(["CTRL-01"])

        with (
            patch("darnit.agent.graph._load_framework_config", return_value=framework),
            patch("darnit.agent.graph._get_framework_path", return_value=None),
            patch("darnit.agent.graph.RemediationExecutor") as MockExecutor,
        ):
            MockExecutor.return_value.execute.side_effect = RuntimeError("boom")
            state = remediate(state)

        assert state.remediation_results[0]["success"] is False
        assert "boom" in state.remediation_results[0]["message"]

    def test_skips_when_framework_not_found(self):
        state = _make_state(
            owner="org",
            repo="repo",
            audit_results=[_make_pass_result("CTRL-01", "FAIL")],
        )

        with (
            patch("darnit.agent.graph._load_framework_config", return_value=None),
            patch("darnit.agent.graph.RemediationExecutor") as MockExecutor,
        ):
            state = remediate(state)

        MockExecutor.assert_not_called()
        assert state.remediation_results == []

    def test_dry_run_passed_to_executor(self):
        state = _make_state(
            owner="org",
            repo="repo",
            audit_results=[_make_pass_result("CTRL-01", "FAIL")],
        )

        framework = self._make_framework(["CTRL-01"])
        mock_result = MagicMock(success=True, message="dry", dry_run=True, details={})

        with (
            patch("darnit.agent.graph._load_framework_config", return_value=framework),
            patch("darnit.agent.graph._get_framework_path", return_value=None),
            patch("darnit.agent.graph.RemediationExecutor") as MockExecutor,
        ):
            MockExecutor.return_value.execute.return_value = mock_result
            remediate(state, dry_run=True)

        _, call_kwargs = MockExecutor.return_value.execute.call_args
        assert call_kwargs["dry_run"] is True


# ---------------------------------------------------------------------------
# route helper
# ---------------------------------------------------------------------------


class TestRoute:
    def test_returns_end_on_error(self):
        state = _make_state(error="something went wrong")
        assert route(state) == "end"

    def test_returns_audit_when_results_cleared(self):
        """After collect_context clears results, route should go back to audit."""
        state = _make_state(audit_results=[])
        state.feedback_questions = [
            FeedbackQuestion("CTRL-01", "has_releases", "Q?", answer="yes", answered=True)
        ]
        assert route(state) == "audit"

    def test_returns_collect_context_when_warn_and_unanswered(self):
        state = _make_state(
            audit_results=[_make_pass_result("CTRL-01", "WARN")]
        )
        state.feedback_questions = [
            FeedbackQuestion("CTRL-01", "has_releases", "Q?")
        ]
        assert route(state) == "collect_context"

    def test_returns_remediate_when_fail_and_no_pending_questions(self):
        state = _make_state(
            audit_results=[_make_pass_result("CTRL-01", "FAIL")]
        )
        assert route(state) == "remediate"

    def test_returns_end_when_all_pass(self):
        state = _make_state(
            audit_results=[
                _make_pass_result("CTRL-01", "PASS"),
                _make_pass_result("CTRL-02", "PASS"),
            ]
        )
        assert route(state) == "end"

    def test_returns_remediate_when_warn_questions_already_answered(self):
        """Answered questions should not block progress to remediation."""
        state = _make_state(
            audit_results=[
                _make_pass_result("CTRL-01", "FAIL"),
                _make_pass_result("CTRL-02", "WARN"),
            ]
        )
        q = FeedbackQuestion("CTRL-02", "has_releases", "Q?", answer="yes", answered=True)
        state.feedback_questions = [q]
        assert route(state) == "remediate"
