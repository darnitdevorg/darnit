"""Unit tests for the Check-phase execution rule.

Feature 025 T015 introduced ``resolve_step_result`` (FR-003 + FR-004); feature
041 changed its input from a scalar authority to the step's effective set,
the outcomes the step may conclude for its control. Tests every (effective
set, HandlerResultStatus, is_last_step) combination that determines a
``StepDisposition``.
"""

from __future__ import annotations

import pytest

from darnit.sieve.handler_registry import HandlerResultStatus
from darnit.sieve.orchestrator import StepDisposition, resolve_step_result

BOTH = frozenset({"pass", "fail"})
FAIL_ONLY = frozenset({"fail"})
PASS_ONLY = frozenset({"pass"})
NOTHING = frozenset()
ALL_SETS = [BOTH, FAIL_ONLY, PASS_ONLY, NOTHING]


class TestResolveStepResult:
    """resolve_step_result: pure Check-phase execution rule."""

    # -----------------------------------------------------------------
    # ERROR is terminal regardless of the effective set (FR-003 (c))
    # -----------------------------------------------------------------

    @pytest.mark.parametrize("allowed", ALL_SETS)
    @pytest.mark.parametrize("is_last", [True, False])
    def test_error_terminates_regardless_of_effective_set(self, allowed, is_last):
        d = resolve_step_result(
            handler_status=HandlerResultStatus.ERROR,
            allowed=allowed,
            is_last_step=is_last,
        )
        assert d == StepDisposition.TERMINATE_ERROR

    # -----------------------------------------------------------------
    # An outcome in the effective set concludes
    # -----------------------------------------------------------------

    def test_pass_in_set_concludes(self):
        assert resolve_step_result(HandlerResultStatus.PASS, BOTH, is_last_step=False) == StepDisposition.CONCLUDE_PASS

    def test_fail_in_set_concludes(self):
        assert resolve_step_result(HandlerResultStatus.FAIL, BOTH, is_last_step=False) == StepDisposition.CONCLUDE_FAIL

    def test_fail_only_step_concludes_fail(self):
        d = resolve_step_result(HandlerResultStatus.FAIL, FAIL_ONLY, is_last_step=False)
        assert d == StepDisposition.CONCLUDE_FAIL

    def test_pass_only_step_concludes_pass(self):
        d = resolve_step_result(HandlerResultStatus.PASS, PASS_ONLY, is_last_step=False)
        assert d == StepDisposition.CONCLUDE_PASS

    # -----------------------------------------------------------------
    # An outcome outside the effective set is evidence (FR-003, feature 041)
    # -----------------------------------------------------------------

    def test_pass_outside_set_attaches_and_continues(self):
        """Load-bearing: a presence or pattern step's PASS never concludes."""
        d = resolve_step_result(HandlerResultStatus.PASS, FAIL_ONLY, is_last_step=False)
        assert d == StepDisposition.ATTACH_EVIDENCE_AND_CONTINUE

    def test_pass_outside_set_on_last_step_is_inconclusive_not_pass(self):
        d = resolve_step_result(HandlerResultStatus.PASS, FAIL_ONLY, is_last_step=True)
        assert d == StepDisposition.TERMINATE_INCONCLUSIVE

    def test_fail_outside_set_attaches_and_continues(self):
        d = resolve_step_result(HandlerResultStatus.FAIL, PASS_ONLY, is_last_step=False)
        assert d == StepDisposition.ATTACH_EVIDENCE_AND_CONTINUE

    @pytest.mark.parametrize("status", [HandlerResultStatus.PASS, HandlerResultStatus.FAIL])
    def test_empty_set_never_concludes(self, status):
        """FR-001 safety: an evidence-only step (model, manual) never concludes."""
        assert resolve_step_result(status, NOTHING, is_last_step=False) == StepDisposition.ATTACH_EVIDENCE_AND_CONTINUE
        assert resolve_step_result(status, NOTHING, is_last_step=True) == StepDisposition.TERMINATE_INCONCLUSIVE

    # -----------------------------------------------------------------
    # INCONCLUSIVE handler status (FR-003 (b), tail case)
    # -----------------------------------------------------------------

    @pytest.mark.parametrize("allowed", ALL_SETS)
    def test_inconclusive_attaches_when_more_steps(self, allowed):
        d = resolve_step_result(HandlerResultStatus.INCONCLUSIVE, allowed, is_last_step=False)
        assert d == StepDisposition.ATTACH_EVIDENCE_AND_CONTINUE

    @pytest.mark.parametrize("allowed", ALL_SETS)
    def test_inconclusive_on_last_step_terminates_inconclusive(self, allowed):
        d = resolve_step_result(HandlerResultStatus.INCONCLUSIVE, allowed, is_last_step=True)
        assert d == StepDisposition.TERMINATE_INCONCLUSIVE
