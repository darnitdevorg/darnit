"""Typed errors for the RFC-0001 Stage 1 ActionPlan protocol.

See specs/025-rfc0001-stage1/data-model.md section 7.

These errors are raised by the pure state-transition functions in
``darnit.core.action_plan`` (Slice B). Slice A pre-defines them so the
loader (``AuthorityViolation``) can use them at control-load time.
"""

from __future__ import annotations


class OutOfOrderSubmission(Exception):
    """Raised by ``submit_result`` when the caller submits a result for a
    step that is not the currently expected one.
    """

    def __init__(self, expected_step_id: str, submitted_step_id: str) -> None:
        self.expected_step_id = expected_step_id
        self.submitted_step_id = submitted_step_id
        super().__init__(f"Expected result for step {expected_step_id!r}, got {submitted_step_id!r}")


class ResultSchemaMismatch(Exception):
    """Raised by ``submit_result`` when the submitted result payload fails
    validation against the step's declared ``result_schema``.
    """

    def __init__(
        self,
        step_id: str,
        offending_fields: list[str],
        message: str,
    ) -> None:
        self.step_id = step_id
        self.offending_fields = offending_fields
        super().__init__(f"Step {step_id!r}: {message}")


class AuthorityViolation(Exception):
    """Raised at control-load time when a strategy step declares an
    impossible authority (for example, a Python handler claiming
    ``asserted``, or a step whose handler is ``manual`` but authority is
    not ``asserted``).

    The loader raises this during framework-config load rather than at
    audit-run time, so a broken control cannot silently ship.
    """

    def __init__(self, control_id: str, step_id: str, message: str) -> None:
        self.control_id = control_id
        self.step_id = step_id
        super().__init__(f"Control {control_id!r} step {step_id!r}: {message}")
