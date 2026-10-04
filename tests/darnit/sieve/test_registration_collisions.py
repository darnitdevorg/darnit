"""Plugins cannot replace step types (feature 044, US2, FR-005, FR-006, framework-design 3.0.3).

A plugin registration under a name core or another plugin already uses is
refused, logged at WARNING naming both registrants, and recorded in
``refused_registrations``; the first registration is unchanged. The same
plugin registering its own name again is allowed.
"""

from __future__ import annotations

import logging

import pytest

import darnit.sieve.handler_registry as handler_registry
from darnit.config.framework_schema import HandlerInvocation
from darnit.sieve.handler_registry import (
    HandlerContext,
    HandlerResult,
    HandlerResultStatus,
    RefusedRegistration,
    SieveHandlerRegistry,
    get_sieve_handler_registry,
)
from darnit.sieve.models import CheckContext, ControlSpec
from darnit.sieve.orchestrator import SieveOrchestrator

CORE_STEP_TYPES = ("file_exists", "exec", "gh_api", "regex", "pattern", "llm_eval", "manual", "manual_steps", "mcp")
LOGGER = "darnit.sieve.handler_registry"


def _always_pass(config, context: HandlerContext) -> HandlerResult:  # noqa: ARG001
    return HandlerResult(status=HandlerResultStatus.PASS, message="plugin says pass", confidence=1.0)


def _register_as(registry: SieveHandlerRegistry, plugin: str | None, name: str, **kwargs) -> None:
    registry.set_plugin_context(plugin)
    try:
        registry.register(name, kwargs.pop("phase", "deterministic"), kwargs.pop("fn", _always_pass), **kwargs)
    finally:
        registry.set_plugin_context(None)


@pytest.mark.unit
class TestCoreNames:
    def test_plugin_cannot_replace_a_core_step_type(self, caplog: pytest.LogCaptureFixture) -> None:
        registry = SieveHandlerRegistry()
        _register_as(registry, None, "manual", phase="manual")
        core = registry.get("manual")

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            _register_as(registry, "evil-plugin", "manual", phase="manual", ceiling={"pass"})

        assert registry.get("manual") is core
        assert registry.get("manual").ceiling == frozenset()
        assert registry.refused_registrations == [
            RefusedRegistration(name="manual", attempted_by="evil-plugin", registered_by="core")
        ]
        warning = next(r for r in caplog.records if r.levelno >= logging.WARNING)
        assert "evil-plugin" in warning.getMessage()
        assert "core" in warning.getMessage()
        assert "'manual'" in warning.getMessage()

    def test_manual_only_control_still_does_not_pass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        registry = get_sieve_handler_registry()
        monkeypatch.setattr(registry, "refused_registrations", [])

        _register_as(registry, "evil-plugin", "manual", phase="manual", ceiling={"pass"})

        assert registry.get("manual").plugin is None
        assert registry.refused_registrations[0].attempted_by == "evil-plugin"
        spec = ControlSpec(
            control_id="TEST-MANUAL-01",
            level=1,
            domain="TEST",
            name="Manual only",
            description="A control whose only step is manual",
            metadata={"handler_invocations": [HandlerInvocation(handler="manual", steps=["Check it"])]},
        )
        context = CheckContext(
            owner="o", repo="r", local_path="/tmp", default_branch="main", control_id=spec.control_id
        )

        result = SieveOrchestrator(stop_on_llm=False).verify(spec, context)

        assert result.status != "PASS"
        assert result.concluded_by == "none"

    def test_core_step_types_register_before_any_plugin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(handler_registry, "_sieve_handler_registry", None)

        registry = get_sieve_handler_registry()

        for name in CORE_STEP_TYPES:
            assert registry.get(name).plugin is None, name
        _register_as(registry, "late-plugin", "exec", ceiling={"pass", "fail"})
        assert registry.get("exec").plugin is None


@pytest.mark.unit
class TestPluginNames:
    def test_second_plugin_is_refused_naming_both(self, caplog: pytest.LogCaptureFixture) -> None:
        registry = SieveHandlerRegistry()
        _register_as(registry, "first-plugin", "shared_check", ceiling={"fail"})
        first = registry.get("shared_check")

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            _register_as(registry, "second-plugin", "shared_check", ceiling={"pass", "fail"})

        assert registry.get("shared_check") is first
        assert registry.refused_registrations == [
            RefusedRegistration(name="shared_check", attempted_by="second-plugin", registered_by="first-plugin")
        ]
        message = next(r for r in caplog.records if r.levelno >= logging.WARNING).getMessage()
        assert "first-plugin" in message
        assert "second-plugin" in message

    def test_same_plugin_may_register_its_own_name_again(self) -> None:
        registry = SieveHandlerRegistry()
        _register_as(registry, "my-plugin", "my_check", ceiling={"fail"})
        _register_as(registry, "my-plugin", "my_check", ceiling={"fail"}, settings={"files"})

        assert registry.get("my_check").settings == frozenset({"files"})
        assert registry.refused_registrations == []

    def test_repeated_refusal_is_recorded_once(self) -> None:
        registry = SieveHandlerRegistry()
        _register_as(registry, None, "exec", ceiling={"pass", "fail"})
        _register_as(registry, "evil-plugin", "exec")
        _register_as(registry, "evil-plugin", "exec")

        assert len(registry.refused_registrations) == 1

    def test_clear_forgets_refusals(self) -> None:
        registry = SieveHandlerRegistry()
        _register_as(registry, None, "exec")
        _register_as(registry, "evil-plugin", "exec")

        registry.clear()

        assert registry.refused_registrations == []


@pytest.mark.unit
class TestReporting:
    REFUSAL = RefusedRegistration(name="manual", attempted_by="evil-plugin", registered_by="core")

    def test_refusal_is_an_audit_warning(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        from darnit.config.operator.loader import resolve_operator_config
        from darnit.tools.audit import audit_report_metadata

        monkeypatch.setattr(get_sieve_handler_registry(), "refused_registrations", [self.REFUSAL])

        metadata = audit_report_metadata(resolve_operator_config(tmp_path), str(tmp_path), None, None)

        assert any("evil-plugin" in w and "'manual'" in w for w in metadata["warnings"])

    def test_refusal_is_listed(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        import argparse

        from darnit.cli import cmd_list

        monkeypatch.setattr(get_sieve_handler_registry(), "refused_registrations", [self.REFUSAL])

        with caplog.at_level(logging.INFO):
            assert cmd_list(argparse.Namespace()) == 0

        assert any("evil-plugin" in r.getMessage() and "'manual'" in r.getMessage() for r in caplog.records)
