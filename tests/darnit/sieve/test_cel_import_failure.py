"""An import failure inside cel-python reports its real cause, not "not installed"."""

from __future__ import annotations

import builtins

import pytest

from darnit.sieve.cel_evaluator import CELCompilationError, evaluate_cel


def test_cel_import_failure_names_the_real_cause(monkeypatch) -> None:
    real_import = builtins.__import__

    def failing_import(name, *args, **kwargs):
        if name == "celpy" or name.startswith("celpy."):
            raise ImportError("No module named 'packaging.version'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing_import)

    with pytest.raises(CELCompilationError) as excinfo:
        evaluate_cel("1 == 1", {})

    message = str(excinfo.value)
    assert "packaging.version" in message
    assert "not installed" not in message
