"""Feature 036 SC-005: `_apply_cel_expr` must not drop `error_class`.

The CEL post-step constructs BRAND-NEW ``HandlerResult`` objects rather
than mutating the incoming one, so any field it does not explicitly
thread through is silently lost. Feature 026 hit this exact bug with
``authority`` (see the "Feature 026 bug fix" comment at the PASS-branch
constructor in ``orchestrator.py``).

The failure mode is a missing field, not an exception -- nothing crashes,
the verdict is still correct, and the only symptom is that downstream
reporting and attestations lose the environmental-failure cause. That is
precisely the kind of bug a test has to pin down, so these tests are
written before the fix.

Transition table (contracts/error-class.md section 4):

    Handler status | CEL result | Post-step status | error_class
    ---------------+------------+------------------+-------------
    PASS           | true       | PASS             | preserved
    PASS           | false      | INCONCLUSIVE     | preserved
    FAIL           | true       | INCONCLUSIVE     | preserved
    FAIL           | false      | FAIL             | preserved

Plus two trivially-safe pass-through paths (no ``expr`` configured;
handler returned ERROR/INCONCLUSIVE) which return the same object.

Note: a PASS result can never legitimately carry an ``error_class`` --
``HandlerResult.__post_init__`` rejects that shape. The two PASS rows
above are therefore exercised via a FAIL-status input whose CEL
evaluation drives the transition, plus a direct check that the
pass-through paths preserve the field.
"""

from __future__ import annotations

import pytest

from darnit.sieve.handler_registry import HandlerResult, HandlerResultStatus
from darnit.sieve.orchestrator import _apply_cel_expr


class TestCelPostStepPreservesErrorClass:
    """Every construction site in `_apply_cel_expr` must thread error_class."""

    @pytest.mark.unit
    def test_fail_plus_cel_false_preserves_error_class(self) -> None:
        """FAIL + CEL false -> FAIL (agreement branch). error_class survives."""
        incoming = HandlerResult(
            status=HandlerResultStatus.FAIL,
            message="command failed",
            confidence=1.0,
            evidence={"stdout": "", "exit_code": 1},
            error_class="timeout",
        )
        out = _apply_cel_expr({"expr": 'output.stdout != ""'}, incoming)

        assert out.status == HandlerResultStatus.FAIL
        assert out.error_class == "timeout", (
            "the FAIL+CEL-false agreement branch dropped error_class"
        )

    @pytest.mark.unit
    def test_fail_plus_cel_true_preserves_error_class(self) -> None:
        """FAIL + CEL true -> INCONCLUSIVE (disagreement branch)."""
        incoming = HandlerResult(
            status=HandlerResultStatus.FAIL,
            message="command failed",
            confidence=1.0,
            evidence={"stdout": "something", "exit_code": 1},
            error_class="rate_limit",
        )
        out = _apply_cel_expr({"expr": 'output.stdout != ""'}, incoming)

        assert out.status == HandlerResultStatus.INCONCLUSIVE
        assert out.error_class == "rate_limit", (
            "the disagreement branch dropped error_class"
        )

    @pytest.mark.unit
    def test_no_expr_configured_returns_same_object(self) -> None:
        """Pass-through path: no `expr` means the object is returned as-is."""
        incoming = HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="boom",
            error_class="crashed",
        )
        out = _apply_cel_expr({}, incoming)

        assert out is incoming
        assert out.error_class == "crashed"

    @pytest.mark.unit
    def test_error_status_bypasses_cel_entirely(self) -> None:
        """Pass-through path: ERROR/INCONCLUSIVE are not CEL-overridable."""
        incoming = HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="subprocess died",
            evidence={"stdout": ""},
            error_class="network",
        )
        out = _apply_cel_expr({"expr": 'output.stdout != ""'}, incoming)

        assert out is incoming
        assert out.error_class == "network"

    @pytest.mark.unit
    def test_inconclusive_status_bypasses_cel_entirely(self) -> None:
        incoming = HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message="could not determine",
            evidence={"stdout": ""},
            error_class="not_found",
        )
        out = _apply_cel_expr({"expr": 'output.stdout != ""'}, incoming)

        assert out is incoming
        assert out.error_class == "not_found"

    @pytest.mark.unit
    def test_cel_evaluation_failure_returns_original_object(self) -> None:
        """A malformed expr logs and returns the input unchanged."""
        incoming = HandlerResult(
            status=HandlerResultStatus.FAIL,
            message="command failed",
            evidence={"stdout": ""},
            error_class="auth",
        )
        out = _apply_cel_expr({"expr": "this is (not valid CEL"}, incoming)

        assert out.error_class == "auth"

    @pytest.mark.unit
    def test_authority_still_preserved_alongside_error_class(self) -> None:
        """Regression guard: adding error_class must not break feature 026's fix."""
        incoming = HandlerResult(
            status=HandlerResultStatus.FAIL,
            message="command failed",
            confidence=1.0,
            evidence={"stdout": "", "exit_code": 1},
            authority="dispositive",
            error_class="timeout",
        )
        out = _apply_cel_expr({"expr": 'output.stdout != ""'}, incoming)

        assert out.authority == "dispositive"
        assert out.error_class == "timeout"


class TestPassResultsCannotCarryErrorClass:
    """A PASS + error_class shape is rejected before CEL ever sees it."""

    @pytest.mark.unit
    def test_constructing_pass_with_error_class_raises(self) -> None:
        with pytest.raises(ValueError, match="incompatible with status=PASS"):
            HandlerResult(
                status=HandlerResultStatus.PASS,
                message="ok",
                error_class="timeout",
            )


class TestAllInconclusiveWarnFallback:
    """The WARN fallthrough must not lose the environmental cause.

    FR-009a says error_class comes from the RESOLVING pass. When every
    pass is inconclusive there IS no resolving pass, so a strict reading
    leaves error_class None -- and a fully degraded audit then reports a
    bare "manual verification required" with no hint that the operator's
    token expired. That defeats US1.

    The fallback: with no conclusion to supersede it, the most recent
    environmental classification is the best available explanation.

    Last NON-NONE rather than simply last, because nearly every baseline
    control ends with a `manual` pass -- an "ask a human" placeholder that
    always returns INCONCLUSIVE and can never conclude anything. Treating
    it as "the final attempt ran cleanly" would wipe the real failure that
    preceded it, which is precisely the common degraded-audit shape.
    """

    def _run(self, handler_specs: list[tuple[str, HandlerResult]]):
        from darnit.config.framework_schema import HandlerInvocation
        from darnit.core.plugin import ControlSpec
        from darnit.sieve.handler_registry import get_sieve_handler_registry
        from darnit.sieve.models import CheckContext
        from darnit.sieve.orchestrator import SieveOrchestrator

        registry = get_sieve_handler_registry()
        invocations = []
        for name, result in handler_specs:
            registry.register(
                name,
                "deterministic",
                lambda config, ctx, _r=result: _r,
                default_authority="suggestive",
            )
            invocations.append(HandlerInvocation(handler=name))

        control = ControlSpec(
            control_id="TEST-WARN.01",
            name="t",
            description="d",
            level=1,
            domain="TEST",
            metadata={"handler_invocations": invocations},
        )
        context = CheckContext(
            owner="o",
            repo="r",
            local_path="/tmp/test",
            default_branch="main",
            control_id="TEST-WARN.01",
            project_context={},
        )
        return SieveOrchestrator(stop_on_llm=True)._dispatch_handler_invocations(
            control, context
        )

    @pytest.mark.unit
    def test_env_failure_then_manual_placeholder_keeps_the_cause(self) -> None:
        """The dominant real-world shape: exec fails, manual pass follows."""
        result = self._run(
            [
                (
                    "wfb_exec_036",
                    HandlerResult(
                        status=HandlerResultStatus.INCONCLUSIVE,
                        message="Command exited with unexpected code 1",
                        error_class="auth",
                    ),
                ),
                (
                    "wfb_manual_036",
                    HandlerResult(
                        status=HandlerResultStatus.INCONCLUSIVE,
                        message="Manual verification required",
                    ),
                ),
            ]
        )
        assert result is not None
        assert result.status == "WARN"
        assert result.error_class == "auth", (
            "a trailing manual placeholder must not erase the exec failure "
            "that actually caused this control to be unverifiable"
        )

    @pytest.mark.unit
    def test_all_clean_inconclusive_carries_no_error_class(self) -> None:
        """No environmental failure anywhere means no annotation."""
        result = self._run(
            [
                (
                    "wfb_clean_a_036",
                    HandlerResult(
                        status=HandlerResultStatus.INCONCLUSIVE,
                        message="could not determine",
                    ),
                ),
                (
                    "wfb_clean_b_036",
                    HandlerResult(
                        status=HandlerResultStatus.INCONCLUSIVE,
                        message="also could not determine",
                    ),
                ),
            ]
        )
        assert result is not None
        assert result.status == "WARN"
        assert result.error_class is None

    @pytest.mark.unit
    def test_later_env_failure_supersedes_earlier_one(self) -> None:
        result = self._run(
            [
                (
                    "wfb_first_036",
                    HandlerResult(
                        status=HandlerResultStatus.INCONCLUSIVE,
                        message="a",
                        error_class="network",
                    ),
                ),
                (
                    "wfb_second_036",
                    HandlerResult(
                        status=HandlerResultStatus.INCONCLUSIVE,
                        message="b",
                        error_class="rate_limit",
                    ),
                ),
            ]
        )
        assert result is not None
        assert result.error_class == "rate_limit"
