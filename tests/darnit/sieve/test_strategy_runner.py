"""Unit tests for the RFC-0001 Stage 1 Check-phase execution rule.

Feature 025 T015. Covers ``resolve_step_result``: the pure function encoding
FR-003 + FR-004. Tests every (authority, HandlerResultStatus, is_last_step)
combination that determines a ``StepDisposition``.
"""

from __future__ import annotations

import pytest

from darnit.sieve.handler_registry import HandlerResultStatus
from darnit.sieve.orchestrator import StepDisposition, resolve_step_result


class TestResolveStepResult:
    """resolve_step_result: pure Check-phase execution rule."""

    # -----------------------------------------------------------------
    # ERROR is terminal regardless of authority (FR-003 (c))
    # -----------------------------------------------------------------

    @pytest.mark.parametrize("authority", ["dispositive", "suggestive", "asserted", None])
    @pytest.mark.parametrize("is_last", [True, False])
    def test_error_terminates_regardless_of_authority(self, authority, is_last):
        d = resolve_step_result(
            handler_status=HandlerResultStatus.ERROR,
            effective_authority=authority,
            is_last_step=is_last,
        )
        assert d == StepDisposition.TERMINATE_ERROR

    # -----------------------------------------------------------------
    # Dispositive PASS/FAIL is terminal (FR-003 (a))
    # -----------------------------------------------------------------

    def test_dispositive_pass_concludes(self):
        d = resolve_step_result(HandlerResultStatus.PASS, "dispositive", is_last_step=False)
        assert d == StepDisposition.CONCLUDE_PASS

    def test_dispositive_fail_concludes(self):
        d = resolve_step_result(HandlerResultStatus.FAIL, "dispositive", is_last_step=False)
        assert d == StepDisposition.CONCLUDE_FAIL

    def test_asserted_pass_concludes(self):
        d = resolve_step_result(HandlerResultStatus.PASS, "asserted", is_last_step=False)
        assert d == StepDisposition.CONCLUDE_PASS

    def test_asserted_fail_concludes(self):
        d = resolve_step_result(HandlerResultStatus.FAIL, "asserted", is_last_step=False)
        assert d == StepDisposition.CONCLUDE_FAIL

    # -----------------------------------------------------------------
    # Suggestive PASS/FAIL is NOT terminal (FR-003 (b), FR-004)
    # -----------------------------------------------------------------

    def test_suggestive_pass_attaches_and_continues_when_more_steps(self):
        d = resolve_step_result(HandlerResultStatus.PASS, "suggestive", is_last_step=False)
        assert d == StepDisposition.ATTACH_EVIDENCE_AND_CONTINUE

    def test_suggestive_fail_attaches_and_continues_when_more_steps(self):
        d = resolve_step_result(HandlerResultStatus.FAIL, "suggestive", is_last_step=False)
        assert d == StepDisposition.ATTACH_EVIDENCE_AND_CONTINUE

    def test_suggestive_pass_on_last_step_terminates_inconclusive(self):
        d = resolve_step_result(HandlerResultStatus.PASS, "suggestive", is_last_step=True)
        assert d == StepDisposition.TERMINATE_INCONCLUSIVE

    def test_suggestive_fail_on_last_step_terminates_inconclusive(self):
        d = resolve_step_result(HandlerResultStatus.FAIL, "suggestive", is_last_step=True)
        assert d == StepDisposition.TERMINATE_INCONCLUSIVE

    # -----------------------------------------------------------------
    # None (authority-less) is treated as suggestive (FR-001 safety)
    # -----------------------------------------------------------------

    def test_none_authority_pass_never_concludes(self):
        """Load-bearing safety property: FR-001."""
        d = resolve_step_result(HandlerResultStatus.PASS, None, is_last_step=False)
        assert d == StepDisposition.ATTACH_EVIDENCE_AND_CONTINUE

    def test_none_authority_pass_on_last_step_is_inconclusive_not_pass(self):
        """FR-001: even at end of list, authority-less cannot conclude PASS."""
        d = resolve_step_result(HandlerResultStatus.PASS, None, is_last_step=True)
        assert d == StepDisposition.TERMINATE_INCONCLUSIVE

    def test_none_authority_fail_never_concludes(self):
        d = resolve_step_result(HandlerResultStatus.FAIL, None, is_last_step=True)
        assert d == StepDisposition.TERMINATE_INCONCLUSIVE

    # -----------------------------------------------------------------
    # INCONCLUSIVE handler status (FR-003 (b), tail case)
    # -----------------------------------------------------------------

    @pytest.mark.parametrize("authority", ["dispositive", "suggestive", "asserted", None])
    def test_inconclusive_attaches_when_more_steps(self, authority):
        d = resolve_step_result(HandlerResultStatus.INCONCLUSIVE, authority, is_last_step=False)
        assert d == StepDisposition.ATTACH_EVIDENCE_AND_CONTINUE

    @pytest.mark.parametrize("authority", ["dispositive", "suggestive", "asserted", None])
    def test_inconclusive_on_last_step_terminates_inconclusive(self, authority):
        d = resolve_step_result(HandlerResultStatus.INCONCLUSIVE, authority, is_last_step=True)
        assert d == StepDisposition.TERMINATE_INCONCLUSIVE
