"""Step registration metadata (feature 044, framework-design 3.0.3).

Each step type declares the settings it reads and the names its ``expr``
may use. Strict loading (US1, US2) checks steps against these, so every
core step type declares its settings, and the declarations cover every key
the shipped framework TOML uses.
"""

from __future__ import annotations

from darnit.sieve.handler_registry import SieveHandlerRegistry


def _noop(config, context):  # noqa: ARG001
    raise AssertionError("not called")


class TestRegister:
    def test_stores_settings_and_expression_names(self) -> None:
        reg = SieveHandlerRegistry()
        reg.register(
            "my_check",
            phase="deterministic",
            handler_fn=_noop,
            settings=frozenset({"files", "threshold"}),
            expression_names=frozenset({"output", "project"}),
        )
        info = reg.get("my_check")
        assert info.settings == frozenset({"files", "threshold"})
        assert info.expression_names == frozenset({"output", "project"})

    def test_defaults(self) -> None:
        reg = SieveHandlerRegistry()
        reg.register("my_check", phase="deterministic", handler_fn=_noop)
        info = reg.get("my_check")
        assert info.settings is None
        assert info.expression_names == frozenset()

    def test_accepts_any_iterable(self) -> None:
        reg = SieveHandlerRegistry()
        reg.register("my_check", phase="deterministic", handler_fn=_noop, settings=["a"], expression_names={"output"})
        info = reg.get("my_check")
        assert info.settings == frozenset({"a"})
        assert info.expression_names == frozenset({"output"})
