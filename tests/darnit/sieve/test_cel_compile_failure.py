"""A compile failure that is not a parse error reports the failure itself.

``compile`` once caught ``celpy.CELSyntaxError``, which cel-python does not
define: evaluating that except clause raised AttributeError and hid the real
error.
"""

from __future__ import annotations

import celpy
import pytest

from darnit.sieve.cel_evaluator import CELCompilationError, evaluate_cel, validate_cel


@pytest.fixture
def failing_program(monkeypatch) -> None:
    def program(self, *args, **kwargs):
        raise RuntimeError("runner rejected the expression")

    monkeypatch.setattr(celpy.Environment, "program", program)


def test_non_parse_compile_failure_is_a_compilation_error(failing_program) -> None:
    with pytest.raises(CELCompilationError, match="runner rejected the expression"):
        evaluate_cel("1 == 1", {})


def test_validate_cel_reports_non_parse_compile_failure(failing_program) -> None:
    valid, error = validate_cel("1 == 1")

    assert valid is False
    assert error is not None and "runner rejected the expression" in error
