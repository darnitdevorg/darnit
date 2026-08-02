"""Unit tests for the sieve orchestrator's CEL post-step (`_apply_cel_expr`).

Covers all cells of the transition table documented at
`specs/020-definitive-fail-verdict/contracts/cel-post-step.md`.

Feature 020 (issue #343) changes two cells of this table:
- Handler FAIL + CEL truthy: was PASS, now INCONCLUSIVE
- Handler FAIL + CEL falsy: was INCONCLUSIVE, now FAIL (the fix)

These changes preserve the constitution's Principle V ("orchestrator stops
at first conclusive result") by keeping the handler's conclusive FAIL when
CEL agrees, and by deferring to INCONCLUSIVE when handler and CEL disagree.
"""

from __future__ import annotations

import pytest

from darnit.sieve.handler_registry import (
    HandlerResult,
    HandlerResultStatus,
)
from darnit.sieve.orchestrator import _apply_cel_expr


def _mk(status: HandlerResultStatus, evidence: dict | None = None, message: str = "") -> HandlerResult:
    """Build a minimal HandlerResult for transition-table testing."""
    return HandlerResult(
        status=status,
        message=message or f"handler returned {status.value}",
        evidence=evidence or {"any_match": False, "files_checked": 1},
    )


# ---------------------------------------------------------------------------
# Transition table: eight cells from contracts/cel-post-step.md
# ---------------------------------------------------------------------------


class TestTransitionTable:
    """Exhaustive coverage of the CEL post-step transition table."""

    @pytest.mark.unit
    def test_pass_and_cel_true_stays_pass(self):
        original = _mk(HandlerResultStatus.PASS, {"any_match": True})
        result = _apply_cel_expr({"expr": "output.any_match"}, original)
        assert result.status == HandlerResultStatus.PASS

    @pytest.mark.unit
    def test_pass_and_cel_false_becomes_inconclusive(self):
        original = _mk(HandlerResultStatus.PASS, {"any_match": False})
        result = _apply_cel_expr({"expr": "output.any_match"}, original)
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    @pytest.mark.unit
    def test_fail_and_cel_true_becomes_inconclusive(self):
        """Feature 020 change: handler+CEL disagree -> defer, not PASS.

        See specs/020-definitive-fail-verdict/contracts/cel-post-step.md.
        """
        original = _mk(HandlerResultStatus.FAIL, {"any_match": False})
        result = _apply_cel_expr({"expr": "!(output.any_match)"}, original)
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    @pytest.mark.unit
    def test_fail_and_cel_false_preserves_fail(self):
        """Feature 020 fix (issue #343): handler+CEL agree on fail -> preserve FAIL.

        Previously this was demoted to INCONCLUSIVE, causing the pipeline
        to fall through to manual and report WARN. See spec FR-001.
        """
        original = _mk(
            HandlerResultStatus.FAIL,
            {
                "exit_code": 1,
                "json": {"message": "Branch not protected", "status": "404"},
            },
            message="Command failed (exit code 1)",
        )
        result = _apply_cel_expr(
            {"expr": "has(output.json.required_pull_request_reviews)"},
            original,
        )
        assert result.status == HandlerResultStatus.FAIL


# ---------------------------------------------------------------------------
# Invariants: pass-through cases (FR-004, FR-005, FR-006, FR-008)
# ---------------------------------------------------------------------------


class TestPassThroughInvariants:
    """Cases where _apply_cel_expr must return the handler result unchanged."""

    @pytest.mark.unit
    def test_inconclusive_passes_through(self):
        """FR-004: handler INCONCLUSIVE -> CEL is not evaluated."""
        original = _mk(HandlerResultStatus.INCONCLUSIVE, {})
        result = _apply_cel_expr({"expr": "true"}, original)
        assert result is original
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    @pytest.mark.unit
    def test_error_passes_through(self):
        """FR-004: handler ERROR -> CEL is not evaluated."""
        original = _mk(HandlerResultStatus.ERROR, {})
        result = _apply_cel_expr({"expr": "true"}, original)
        assert result is original
        assert result.status == HandlerResultStatus.ERROR

    @pytest.mark.unit
    def test_no_expr_passes_through(self):
        """FR-005: config without an expr -> handler result unchanged."""
        original = _mk(HandlerResultStatus.PASS, {"any_match": True})
        result = _apply_cel_expr({"handler": "pattern"}, original)
        assert result is original

    @pytest.mark.unit
    def test_cel_syntax_error_passes_through(self):
        """FR-006: CEL evaluation error -> handler result unchanged."""
        original = _mk(HandlerResultStatus.PASS, {"any_match": True})
        result = _apply_cel_expr({"expr": "not valid CEL !!"}, original)
        assert result.status == HandlerResultStatus.PASS
        assert result is original

    @pytest.mark.unit
    def test_unknown_exec_exit_code_returns_inconclusive_and_passes_through(self):
        """FR-008: WARN preservation for network/auth errors.

        When the exec handler encounters an exit code that is neither in
        `pass_exit_codes` nor `fail_exit_codes` (e.g., 127 for command not
        found, or 2 for a network-adjacent failure), the handler returns
        INCONCLUSIVE. The CEL post-step must pass that through unchanged,
        preserving WARN semantics downstream.
        """
        from darnit.sieve.builtin_handlers import exec_handler
        from darnit.sieve.handler_registry import HandlerContext

        ctx = HandlerContext(
            local_path="/tmp",
            owner="testorg",
            repo="testrepo",
            default_branch="main",
            gathered_evidence={},
            project_context={},
        )
        # exit code 42 matches neither pass_exit_codes=[0] nor fail_exit_codes=[1]
        config = {
            "command": ["sh", "-c", "exit 42"],
            "pass_exit_codes": [0],
            "fail_exit_codes": [1],
            "expr": "true",  # would flip to PASS if the CEL step ran on non-INCONCLUSIVE
        }
        handler_result = exec_handler(config, ctx)
        assert handler_result.status == HandlerResultStatus.INCONCLUSIVE
        result = _apply_cel_expr(config, handler_result)
        assert result is handler_result
        assert result.status == HandlerResultStatus.INCONCLUSIVE
