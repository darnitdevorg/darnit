"""Integration tests for handler-dispatch migration.

Verifies that:
1. All controls in openssf-baseline.toml load with handler invocation format
2. Handler aliases ("pattern" → regex_handler, "manual" → manual_steps_handler) resolve correctly
3. The orchestrator dispatches through the handler registry for every control
4. Controls without handler invocations return WARN gracefully
5. Flat list ordering is respected (stop at first conclusive result)
"""

import pytest

from darnit.config.framework_schema import HandlerInvocation
from darnit.sieve.handler_registry import (
    HandlerResult,
    HandlerResultStatus,
    get_sieve_handler_registry,
    reset_sieve_handler_registry,
)
from darnit.sieve.models import CheckContext, ControlSpec
from darnit.sieve.orchestrator import SieveOrchestrator

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset the global handler registry before each test."""
    reset_sieve_handler_registry()
    yield
    reset_sieve_handler_registry()


def _make_handler(status, message="ok", evidence=None, confidence=1.0):
    """Create a simple handler function that returns a fixed result."""
    def handler(config, context):
        return HandlerResult(
            status=status,
            message=message,
            confidence=confidence,
            evidence=evidence or {},
        )
    return handler


def _make_control(control_id, handler_invocations=None, level=1):
    """Create a ControlSpec with handler invocations."""
    metadata = {}
    if handler_invocations is not None:
        metadata["handler_invocations"] = handler_invocations
    return ControlSpec(
        control_id=control_id,
        name=f"Test {control_id}",
        description=f"Test control {control_id}",
        level=level,
        domain="TEST",
        metadata=metadata,
    )


def _make_context(control_id="TEST-01"):
    """Create a CheckContext for testing."""
    return CheckContext(
        owner="testorg",
        repo="testrepo",
        local_path="/tmp/test",
        default_branch="main",
        control_id=control_id,
        project_context={},
    )


# =============================================================================
# Task 5.1: Handler aliases resolve correctly
# =============================================================================


class TestHandlerAliases:
    """Verify handler aliases registered for TOML compatibility."""

    @pytest.mark.unit
    def test_pattern_alias_resolves_to_regex_handler(self):
        """'pattern' alias resolves to the same handler as 'regex'."""
        registry = get_sieve_handler_registry()
        regex_info = registry.get("regex")
        pattern_info = registry.get("pattern")

        assert regex_info is not None, "regex handler not registered"
        assert pattern_info is not None, "pattern alias not registered"
        assert regex_info.fn is pattern_info.fn, (
            "pattern alias should resolve to same handler function as regex"
        )

    @pytest.mark.unit
    def test_manual_alias_resolves_to_manual_steps_handler(self):
        """'manual' alias resolves to the same handler as 'manual_steps'."""
        registry = get_sieve_handler_registry()
        manual_steps_info = registry.get("manual_steps")
        manual_info = registry.get("manual")

        assert manual_steps_info is not None, "manual_steps handler not registered"
        assert manual_info is not None, "manual alias not registered"
        assert manual_steps_info.fn is manual_info.fn, (
            "manual alias should resolve to same handler function as manual_steps"
        )

    @pytest.mark.unit
    def test_all_toml_handler_names_resolvable(self):
        """Every handler name used in TOML resolves in the registry."""
        registry = get_sieve_handler_registry()
        # Handler names used in openssf-baseline.toml passes and remediation
        toml_handler_names = [
            "exec",
            "file_exists",
            "pattern",       # alias for regex
            "manual",        # alias for manual_steps
            "file_create",
            "api_call",
            # Canonical names should also work
            "regex",
            "manual_steps",
        ]
        for name in toml_handler_names:
            info = registry.get(name)
            assert info is not None, f"Handler '{name}' not found in registry"


# =============================================================================
# Task 5.1: All controls load with handler format
# =============================================================================


class TestTomlControlsLoadAsHandlerFormat:
    """Verify all controls in openssf-baseline.toml use handler invocation format."""

    @pytest.mark.unit
    def test_all_controls_have_handler_invocations(self):
        """Every control with passes uses [[passes]] array-of-tables format."""
        from pathlib import Path

        from darnit.config.control_loader import load_controls_from_toml
        from darnit.core.discovery import get_implementation

        impl = get_implementation("openssf-baseline")
        assert impl is not None, "openssf-baseline implementation not found"

        toml_path = impl.get_framework_config_path()
        assert toml_path is not None and Path(toml_path).exists(), (
            f"Framework TOML not found at {toml_path}"
        )

        controls = load_controls_from_toml(toml_path)
        assert len(controls) > 0, "No controls loaded from TOML"

        controls_with_handlers = 0
        controls_without_handlers = 0

        for spec in controls:
            invocations = spec.metadata.get("handler_invocations")
            if invocations:
                controls_with_handlers += 1
                for inv in invocations:
                    assert hasattr(inv, "handler"), (
                        f"Control {spec.control_id}: invocation missing 'handler' field"
                    )
                    # Verify handler name is resolvable
                    registry = get_sieve_handler_registry()
                    handler_name = inv.handler
                    info = registry.get(handler_name)
                    assert info is not None, (
                        f"Control {spec.control_id}: handler '{handler_name}' "
                        f"not found in registry"
                    )
            else:
                controls_without_handlers += 1

        # Most controls should have handler invocations
        assert controls_with_handlers > 50, (
            f"Expected >50 controls with handlers, got {controls_with_handlers}"
        )


# =============================================================================
# Task 5.3: WARN on empty passes
# =============================================================================


class TestWarnOnEmptyPasses:
    """Verify graceful WARN when control has no handler invocations."""

    @pytest.mark.unit
    def test_no_handler_invocations_returns_warn(self):
        """Control with no handler_invocations in metadata returns WARN."""
        orchestrator = SieveOrchestrator()
        control = _make_control("T-01", handler_invocations=None)
        context = _make_context()
        result = orchestrator.verify(control, context)

        assert result.status == "WARN"
        assert "No handler invocations" in result.message

    @pytest.mark.unit
    def test_empty_handler_invocations_returns_warn(self):
        """Control with empty handler_invocations list returns WARN."""
        orchestrator = SieveOrchestrator()
        control = _make_control("T-01", handler_invocations=[])
        context = _make_context()
        result = orchestrator.verify(control, context)

        assert result.status == "WARN"
        assert "No handler invocations" in result.message


# =============================================================================
# Task 5.4: Flat list ordering
# =============================================================================


class TestFlatListOrdering:
    """Verify orchestrator respects flat list ordering and stops at first conclusive."""

    @pytest.mark.unit
    def test_stops_at_first_pass(self):
        """Orchestrator stops at first PASS, doesn't execute remaining handlers."""
        registry = get_sieve_handler_registry()
        call_log = []

        def first_handler(config, context):
            call_log.append("first")
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message="First passes",
                confidence=1.0,
            )

        def second_handler(config, context):
            call_log.append("second")
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message="Second passes",
                confidence=1.0,
            )

        registry.register("h_first", "deterministic", first_handler)
        registry.register("h_second", "manual", second_handler)

        orchestrator = SieveOrchestrator()
        invocations = [
            HandlerInvocation(handler="h_first"),
            HandlerInvocation(handler="h_second"),
        ]
        control = _make_control("T-01", handler_invocations=invocations)
        result = orchestrator.verify(control, _make_context())

        assert result.status == "PASS"
        assert call_log == ["first"], "Second handler should not have been called"

    @pytest.mark.unit
    def test_continues_through_inconclusive(self):
        """Orchestrator continues past INCONCLUSIVE to next handler."""
        registry = get_sieve_handler_registry()
        call_log = []

        def inconclusive_handler(config, context):
            call_log.append("inconclusive")
            return HandlerResult(
                status=HandlerResultStatus.INCONCLUSIVE,
                message="Cannot determine",
            )

        def pass_handler(config, context):
            call_log.append("pass")
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message="Found it",
                confidence=0.8,
            )

        registry.register("h_inconclusive", "deterministic", inconclusive_handler)
        registry.register("h_pass", "pattern", pass_handler)

        orchestrator = SieveOrchestrator()
        invocations = [
            HandlerInvocation(handler="h_inconclusive"),
            HandlerInvocation(handler="h_pass"),
        ]
        control = _make_control("T-01", handler_invocations=invocations)
        result = orchestrator.verify(control, _make_context())

        assert result.status == "PASS"
        assert call_log == ["inconclusive", "pass"], "Both handlers should have been called"

    @pytest.mark.unit
    def test_stops_at_first_fail(self):
        """Orchestrator stops at first FAIL."""
        registry = get_sieve_handler_registry()
        call_log = []

        def fail_handler(config, context):
            call_log.append("fail")
            return HandlerResult(
                status=HandlerResultStatus.FAIL,
                message="Not found",
                confidence=1.0,
            )

        def manual_handler(config, context):
            call_log.append("manual")
            return HandlerResult(
                status=HandlerResultStatus.INCONCLUSIVE,
                message="Manual steps",
            )

        registry.register("h_fail", "deterministic", fail_handler)
        registry.register("h_manual", "manual", manual_handler)

        orchestrator = SieveOrchestrator()
        invocations = [
            HandlerInvocation(handler="h_fail"),
            HandlerInvocation(handler="h_manual"),
        ]
        control = _make_control("T-01", handler_invocations=invocations)
        result = orchestrator.verify(control, _make_context())

        assert result.status == "FAIL"
        assert call_log == ["fail"], "Manual handler should not have been called after FAIL"

    @pytest.mark.unit
    def test_manual_only_reached_if_preceding_inconclusive(self):
        """Manual handler is reached only when all preceding handlers are INCONCLUSIVE."""
        registry = get_sieve_handler_registry()
        call_log = []

        def exec_handler(config, context):
            call_log.append("exec")
            return HandlerResult(
                status=HandlerResultStatus.INCONCLUSIVE,
                message="Command not available",
            )

        def pattern_handler(config, context):
            call_log.append("pattern")
            return HandlerResult(
                status=HandlerResultStatus.INCONCLUSIVE,
                message="File not found",
            )

        def manual_handler(config, context):
            call_log.append("manual")
            return HandlerResult(
                status=HandlerResultStatus.INCONCLUSIVE,
                message="Manual verification required",
                evidence={"verification_steps": ["Check settings"]},
            )

        registry.register("h_exec", "deterministic", exec_handler)
        registry.register("h_pattern", "pattern", pattern_handler)
        registry.register("h_manual", "manual", manual_handler)

        orchestrator = SieveOrchestrator()
        invocations = [
            HandlerInvocation(handler="h_exec"),
            HandlerInvocation(handler="h_pattern"),
            HandlerInvocation(handler="h_manual"),
        ]
        control = _make_control("T-01", handler_invocations=invocations)
        result = orchestrator.verify(control, _make_context())

        # All three called since all returned INCONCLUSIVE
        assert call_log == ["exec", "pattern", "manual"]
        # Result is WARN (all inconclusive → no conclusive result)
        assert result.status == "WARN"

    @pytest.mark.unit
    def test_evidence_accumulates_across_handlers(self):
        """Evidence from earlier handlers is available to later ones."""
        registry = get_sieve_handler_registry()

        def file_handler(config, context):
            return HandlerResult(
                status=HandlerResultStatus.INCONCLUSIVE,
                message="File found but need content check",
                evidence={"found_file": "/path/to/SECURITY.md"},
            )

        def pattern_handler(config, context):
            # Should have access to evidence from file_handler
            found = context.gathered_evidence.get("found_file")
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message=f"Pattern matched in {found}",
                confidence=0.8,
                evidence={"checked_file": found},
            )

        registry.register("h_file", "deterministic", file_handler)
        registry.register("h_pattern", "pattern", pattern_handler)

        orchestrator = SieveOrchestrator()
        invocations = [
            HandlerInvocation(handler="h_file"),
            HandlerInvocation(handler="h_pattern"),
        ]
        control = _make_control("T-01", handler_invocations=invocations)
        result = orchestrator.verify(control, _make_context())

        assert result.status == "PASS"
        assert result.evidence.get("found_file") == "/path/to/SECURITY.md"
        assert result.evidence.get("checked_file") == "/path/to/SECURITY.md"


# =============================================================================
# Regression: use_locator must resolve through effective config path
# =============================================================================


class TestUseLocatorEffectivePath:
    """Regression test: use_locator must be resolved when loading via effective config.

    The effective config path (merger → control_from_effective) must resolve
    use_locator=true before passing handler invocations to the orchestrator.
    Without this, file_exists handlers get files=[] and return INCONCLUSIVE.
    """

    @pytest.mark.unit
    def test_use_locator_controls_have_files_in_effective_config(self):
        """All use_locator=true controls must have files populated after effective loading."""
        from pathlib import Path

        from darnit.config import load_controls_from_effective, load_effective_config_by_name

        config = load_effective_config_by_name("openssf-baseline", Path("."))
        controls = load_controls_from_effective(config)

        # Known controls that use use_locator=true
        use_locator_controls = {
            "OSPS-BR-07.01", "OSPS-DO-01.01", "OSPS-DO-02.01", "OSPS-GV-03.01",
            "OSPS-LE-01.01", "OSPS-LE-03.01", "OSPS-QA-02.01", "OSPS-VM-02.01",
            "OSPS-GV-01.01", "OSPS-VM-05.03", "OSPS-DO-03.01", "OSPS-SA-03.02",
        }

        for ctrl in controls:
            if ctrl.control_id not in use_locator_controls:
                continue

            invocations = ctrl.metadata.get("handler_invocations", [])
            assert invocations, f"{ctrl.control_id}: no handler_invocations in metadata"

            # Find file_exists handler
            for inv in invocations:
                inv_dict = inv if isinstance(inv, dict) else inv.model_dump()
                if inv_dict.get("handler") == "file_exists":
                    files = inv_dict.get("files")
                    assert files and len(files) > 0, (
                        f"{ctrl.control_id}: file_exists handler has no files - "
                        f"use_locator not resolved! Got: {inv_dict}"
                    )
                    break
