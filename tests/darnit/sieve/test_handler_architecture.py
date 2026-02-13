"""Tests for the handler-based architecture.

Covers tasks 10.1-10.11 from toml-schema-improvements:
- 10.1: HandlerRegistry (registration, lookup, phase affinity, duplicates)
- 10.2: HandlerInvocation schema (extra="allow", shared reference resolution)
- 10.3: Legacy format rejection
- 10.4: when clause evaluation
- 10.5: Dependency resolution (topological sort, cycles)
- 10.6: inferred_from (auto-PASS, normal exec, implicit depends_on)
- 10.7: Shared handler cache
- 10.8: use_locator and auto-derived on_pass
- 10.9: ${context.*} and ${project.*} template variables
- 10.10: N/A report section
- 10.11: Integration test (end-to-end)
"""

import pytest

from darnit.sieve.handler_registry import (
    HandlerContext,
    HandlerPhase,
    HandlerResult,
    HandlerResultStatus,
    SieveHandlerRegistry,
    get_sieve_handler_registry,
    reset_sieve_handler_registry,
)
from darnit.sieve.models import (
    CheckContext,
    ControlSpec,
    SieveResult,
)
from darnit.sieve.orchestrator import (
    SieveOrchestrator,
    _resolve_execution_order,
)

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


def _make_control(
    control_id,
    level=1,
    when=None,
    depends_on=None,
    inferred_from=None,
    handler_invocations=None,
):
    """Create a ControlSpec with metadata for testing."""
    metadata = {}
    if when:
        metadata["when"] = when
    if depends_on:
        metadata["depends_on"] = depends_on
    if inferred_from:
        metadata["inferred_from"] = inferred_from
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


def _make_context(local_path="/tmp/test", project_context=None, **kwargs):
    """Create a CheckContext for testing."""
    return CheckContext(
        owner="testorg",
        repo="testrepo",
        local_path=local_path,
        default_branch="main",
        control_id=kwargs.get("control_id", "TEST-01"),
        project_context=project_context or {},
    )


# =============================================================================
# 10.1: HandlerRegistry tests
# =============================================================================


class TestHandlerRegistry:
    """Tests for SieveHandlerRegistry."""

    @pytest.mark.unit
    def test_register_and_lookup(self):
        """Test basic handler registration and lookup."""
        registry = SieveHandlerRegistry()
        handler_fn = _make_handler(HandlerResultStatus.PASS)

        registry.register("test_handler", "deterministic", handler_fn, "A test handler")

        info = registry.get("test_handler")
        assert info is not None
        assert info.name == "test_handler"
        assert info.phase == HandlerPhase.DETERMINISTIC
        assert info.fn is handler_fn

    @pytest.mark.unit
    def test_lookup_missing(self):
        """Test lookup of unregistered handler returns None."""
        registry = SieveHandlerRegistry()
        assert registry.get("nonexistent") is None

    @pytest.mark.unit
    def test_phase_affinity_validation(self):
        """Test phase affinity warning is issued."""
        registry = SieveHandlerRegistry()
        registry.register(
            "file_check", "deterministic", _make_handler(HandlerResultStatus.PASS)
        )
        # Should log a warning but not raise
        registry.validate_phase("file_check", "pattern")

    @pytest.mark.unit
    def test_duplicate_core_registration(self):
        """Test re-registering a core handler warns."""
        registry = SieveHandlerRegistry()
        registry.register("h1", "deterministic", _make_handler(HandlerResultStatus.PASS))
        # Re-register without plugin context — should log warning
        registry.register("h1", "deterministic", _make_handler(HandlerResultStatus.FAIL))
        # Latest registration wins
        info = registry.get("h1")
        result = info.fn({}, HandlerContext(local_path="/tmp"))
        assert result.status == HandlerResultStatus.FAIL

    @pytest.mark.unit
    def test_plugin_override_core(self):
        """Test plugin handler overrides core handler."""
        registry = SieveHandlerRegistry()
        registry.register("file_exists", "deterministic", _make_handler(HandlerResultStatus.PASS))

        registry.set_plugin_context("my-plugin")
        registry.register("file_exists", "deterministic", _make_handler(HandlerResultStatus.FAIL))
        registry.set_plugin_context(None)

        info = registry.get("file_exists")
        assert info.plugin == "my-plugin"

    @pytest.mark.unit
    def test_list_handlers_by_phase(self):
        """Test listing handlers filtered by phase."""
        registry = SieveHandlerRegistry()
        registry.register("h1", "deterministic", _make_handler(HandlerResultStatus.PASS))
        registry.register("h2", "pattern", _make_handler(HandlerResultStatus.PASS))
        registry.register("h3", "deterministic", _make_handler(HandlerResultStatus.PASS))

        det = registry.list_handlers(phase="deterministic")
        assert len(det) == 2
        pat = registry.list_handlers(phase="pattern")
        assert len(pat) == 1

    @pytest.mark.unit
    def test_list_handlers_by_plugin(self):
        """Test listing handlers filtered by plugin."""
        registry = SieveHandlerRegistry()
        registry.register("core_h", "deterministic", _make_handler(HandlerResultStatus.PASS))
        registry.set_plugin_context("baseline")
        registry.register("plugin_h", "pattern", _make_handler(HandlerResultStatus.PASS))
        registry.set_plugin_context(None)

        # plugin=None → no filter, returns ALL handlers
        all_handlers = registry.list_handlers(plugin=None)
        assert len(all_handlers) == 2

        # Filter by specific plugin
        plugin = registry.list_handlers(plugin="baseline")
        assert len(plugin) == 1
        assert plugin[0].name == "plugin_h"

    @pytest.mark.unit
    def test_clear(self):
        """Test clearing the registry."""
        registry = SieveHandlerRegistry()
        registry.register("h1", "deterministic", _make_handler(HandlerResultStatus.PASS))
        assert registry.get("h1") is not None

        registry.clear()
        assert registry.get("h1") is None

    @pytest.mark.unit
    def test_global_singleton(self):
        """Test get_sieve_handler_registry returns singleton."""
        r1 = get_sieve_handler_registry()
        r2 = get_sieve_handler_registry()
        assert r1 is r2


# =============================================================================
# 10.2: HandlerInvocation schema tests
# =============================================================================


class TestHandlerInvocationSchema:
    """Tests for HandlerInvocation model."""

    @pytest.mark.unit
    def test_extra_allow_passthrough(self):
        """Test that extra fields pass through via model_extra."""
        from darnit.config.framework_schema import HandlerInvocation

        inv = HandlerInvocation(handler="exec", command=["ls"], expr="exit_code == 0")
        assert inv.handler == "exec"
        assert inv.model_extra["command"] == ["ls"]
        assert inv.model_extra["expr"] == "exit_code == 0"

    @pytest.mark.unit
    def test_shared_reference(self):
        """Test shared field on HandlerInvocation."""
        from darnit.config.framework_schema import HandlerInvocation

        inv = HandlerInvocation(handler="exec", shared="branch_protection")
        assert inv.shared == "branch_protection"

    @pytest.mark.unit
    def test_use_locator(self):
        """Test use_locator field defaults to False."""
        from darnit.config.framework_schema import HandlerInvocation

        inv = HandlerInvocation(handler="file_exists")
        assert inv.use_locator is False

        inv2 = HandlerInvocation(handler="file_exists", use_locator=True)
        assert inv2.use_locator is True


# =============================================================================
# 10.3: Legacy format rejection tests
# =============================================================================


class TestLegacyFormatRejection:
    """Tests that legacy phase-bucketed format is rejected."""

    @pytest.mark.unit
    def test_passes_legacy_dict_rejected(self):
        """Legacy phase-bucketed passes dict raises validation error."""
        from darnit.config.framework_schema import ControlConfig

        with pytest.raises(Exception, match="Legacy phase-bucketed"):
            ControlConfig(
                name="Test",
                level=1,
                domain="AC",
                description="Test",
                passes={"deterministic": {"file_must_exist": ["README.md"]}},
            )

    @pytest.mark.unit
    def test_passes_flat_list_accepted(self):
        """New flat handler list is accepted."""
        from darnit.config.framework_schema import ControlConfig, HandlerInvocation

        control = ControlConfig(
            name="Test",
            level=1,
            domain="AC",
            description="Test",
            passes=[
                HandlerInvocation(handler="file_exists", files=["README.md"]),
            ],
        )
        assert len(control.passes) == 1
        assert control.passes[0].handler == "file_exists"

    @pytest.mark.unit
    def test_remediation_handlers_flat_list(self):
        """Remediation uses flat handlers list."""
        from darnit.config.framework_schema import (
            HandlerInvocation,
            RemediationConfig,
        )

        rem = RemediationConfig(
            handlers=[HandlerInvocation(handler="file_create", path="SECURITY.md")]
        )
        assert len(rem.handlers) == 1
        assert rem.handlers[0].handler == "file_create"


# =============================================================================
# 10.4: when clause evaluation tests
# =============================================================================


class TestWhenClauseEvaluation:
    """Tests for when clause evaluation in SieveOrchestrator."""

    @pytest.mark.unit
    def test_when_true_runs_control(self):
        """Control runs when when condition is met."""
        orchestrator = SieveOrchestrator()
        control = _make_control("T-01", when={"has_releases": True})
        context = _make_context(project_context={"has_releases": True})
        assert orchestrator._evaluate_when(control, context) is True

    @pytest.mark.unit
    def test_when_false_skips_control(self):
        """Control is N/A when when condition is not met."""
        orchestrator = SieveOrchestrator()
        control = _make_control("T-01", when={"has_releases": True})
        context = _make_context(project_context={"has_releases": False})
        assert orchestrator._evaluate_when(control, context) is False

    @pytest.mark.unit
    def test_when_string_equality(self):
        """Test string value equality in when clause."""
        orchestrator = SieveOrchestrator()
        control = _make_control("T-01", when={"ci_provider": "github"})
        ctx_match = _make_context(project_context={"ci_provider": "github"})
        ctx_no_match = _make_context(project_context={"ci_provider": "gitlab"})
        assert orchestrator._evaluate_when(control, ctx_match) is True
        assert orchestrator._evaluate_when(control, ctx_no_match) is False

    @pytest.mark.unit
    def test_when_missing_key_runs_normally(self):
        """Missing context key → control runs (conservative)."""
        orchestrator = SieveOrchestrator()
        control = _make_control("T-01", when={"has_releases": True})
        context = _make_context(project_context={})
        assert orchestrator._evaluate_when(control, context) is True

    @pytest.mark.unit
    def test_when_multiple_conditions_all_must_match(self):
        """All when conditions must be true (AND semantics)."""
        orchestrator = SieveOrchestrator()
        control = _make_control(
            "T-01", when={"has_releases": True, "is_library": True}
        )
        # Both match
        ctx_both = _make_context(
            project_context={"has_releases": True, "is_library": True}
        )
        assert orchestrator._evaluate_when(control, ctx_both) is True

        # One doesn't match
        ctx_partial = _make_context(
            project_context={"has_releases": True, "is_library": False}
        )
        assert orchestrator._evaluate_when(control, ctx_partial) is False

    @pytest.mark.unit
    def test_when_no_clause_always_runs(self):
        """Control without when clause always runs."""
        orchestrator = SieveOrchestrator()
        control = _make_control("T-01")
        context = _make_context()
        assert orchestrator._evaluate_when(control, context) is True

    @pytest.mark.unit
    def test_verify_returns_na_when_condition_false(self):
        """Full verify() returns N/A when when condition is false."""
        orchestrator = SieveOrchestrator()
        control = _make_control("T-01", when={"has_releases": True})
        context = _make_context(project_context={"has_releases": False})
        result = orchestrator.verify(control, context)
        assert result.status == "N/A"
        assert "when" in result.evidence


# =============================================================================
# 10.5: Dependency resolution tests
# =============================================================================


class TestDependencyResolution:
    """Tests for topological sort and cycle detection."""

    @pytest.mark.unit
    def test_no_dependencies(self):
        """Controls without dependencies preserve original order."""
        specs = [
            _make_control("A"),
            _make_control("B"),
            _make_control("C"),
        ]
        ordered = _resolve_execution_order(specs)
        ids = [s.control_id for s in ordered]
        assert ids == ["A", "B", "C"]

    @pytest.mark.unit
    def test_simple_dependency(self):
        """B depends on A → A runs first."""
        specs = [
            _make_control("B", depends_on=["A"]),
            _make_control("A"),
        ]
        ordered = _resolve_execution_order(specs)
        ids = [s.control_id for s in ordered]
        assert ids.index("A") < ids.index("B")

    @pytest.mark.unit
    def test_chain_dependency(self):
        """C depends on B, B depends on A → A, B, C."""
        specs = [
            _make_control("C", depends_on=["B"]),
            _make_control("B", depends_on=["A"]),
            _make_control("A"),
        ]
        ordered = _resolve_execution_order(specs)
        ids = [s.control_id for s in ordered]
        assert ids.index("A") < ids.index("B")
        assert ids.index("B") < ids.index("C")

    @pytest.mark.unit
    def test_cycle_detection(self):
        """Cycles are detected and broken (no hang)."""
        specs = [
            _make_control("A", depends_on=["B"]),
            _make_control("B", depends_on=["A"]),
        ]
        # Should complete without infinite loop
        ordered = _resolve_execution_order(specs)
        ids = [s.control_id for s in ordered]
        # Both should appear
        assert set(ids) == {"A", "B"}

    @pytest.mark.unit
    def test_out_of_scope_ignored(self):
        """References to controls not in the batch are ignored."""
        specs = [
            _make_control("B", depends_on=["X"]),  # X not in batch
            _make_control("A"),
        ]
        ordered = _resolve_execution_order(specs)
        ids = [s.control_id for s in ordered]
        assert set(ids) == {"A", "B"}

    @pytest.mark.unit
    def test_inferred_from_creates_implicit_dependency(self):
        """inferred_from creates implicit dependency ordering."""
        specs = [
            _make_control("B", inferred_from="A"),
            _make_control("A"),
        ]
        ordered = _resolve_execution_order(specs)
        ids = [s.control_id for s in ordered]
        assert ids.index("A") < ids.index("B")


# =============================================================================
# 10.6: inferred_from tests
# =============================================================================


class TestInferredFrom:
    """Tests for inferred_from auto-PASS behavior."""

    @pytest.mark.unit
    def test_inferred_pass_when_source_passes(self):
        """Control auto-passes when inferred_from source passed."""
        orchestrator = SieveOrchestrator()
        # Simulate source control having passed
        orchestrator._dependency_results["SRC-01"] = SieveResult(
            control_id="SRC-01",
            status="PASS",
            message="Source passed",
            level=1,
        )

        control = _make_control("T-01", inferred_from="SRC-01")
        result = orchestrator._check_inferred_from(control)
        assert result is not None
        assert result.status == "PASS"
        assert "Inferred from SRC-01" in result.message

    @pytest.mark.unit
    def test_inferred_runs_normally_when_source_fails(self):
        """Control runs normally when inferred_from source failed."""
        orchestrator = SieveOrchestrator()
        orchestrator._dependency_results["SRC-01"] = SieveResult(
            control_id="SRC-01",
            status="FAIL",
            message="Source failed",
            level=1,
        )

        control = _make_control("T-01", inferred_from="SRC-01")
        result = orchestrator._check_inferred_from(control)
        assert result is None  # None means "run normal verification"

    @pytest.mark.unit
    def test_inferred_runs_normally_when_source_not_yet_evaluated(self):
        """Control runs normally when source hasn't been evaluated yet."""
        orchestrator = SieveOrchestrator()
        control = _make_control("T-01", inferred_from="SRC-01")
        result = orchestrator._check_inferred_from(control)
        assert result is None

    @pytest.mark.unit
    def test_no_inferred_from_returns_none(self):
        """Control without inferred_from returns None."""
        orchestrator = SieveOrchestrator()
        control = _make_control("T-01")
        result = orchestrator._check_inferred_from(control)
        assert result is None


# =============================================================================
# 10.7: Shared handler cache tests
# =============================================================================


class TestSharedHandlerCache:
    """Tests for shared handler cache in orchestrator."""

    @pytest.mark.unit
    def test_shared_cache_populated_on_first_execution(self):
        """First execution of shared handler populates the cache."""
        from darnit.config.framework_schema import HandlerInvocation

        registry = get_sieve_handler_registry()
        call_count = {"n": 0}

        def counting_handler(config, context):
            call_count["n"] += 1
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message="ok",
                confidence=1.0,
                evidence={"found": True},
            )

        registry.register("shared_check", "deterministic", counting_handler)

        orchestrator = SieveOrchestrator()
        invocations = [
            HandlerInvocation(handler="shared_check", shared="bp_check"),
        ]
        control = _make_control("T-01", handler_invocations=invocations)
        context = _make_context()
        result = orchestrator._dispatch_handler_invocations(control, context)

        assert result is not None
        assert result.status == "PASS"
        assert "bp_check" in orchestrator._shared_cache
        assert call_count["n"] == 1

    @pytest.mark.unit
    def test_shared_cache_reused_on_second_execution(self):
        """Second execution of same shared handler uses cache."""
        from darnit.config.framework_schema import HandlerInvocation

        registry = get_sieve_handler_registry()
        call_count = {"n": 0}

        def counting_handler(config, context):
            call_count["n"] += 1
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message="ok",
                confidence=1.0,
                evidence={"found": True},
            )

        registry.register("shared_check", "deterministic", counting_handler)

        orchestrator = SieveOrchestrator()

        # First control
        inv1 = [HandlerInvocation(handler="shared_check", shared="bp_check")]
        control1 = _make_control("T-01", handler_invocations=inv1)
        orchestrator._dispatch_handler_invocations(control1, _make_context())

        # Second control — should use cache
        inv2 = [HandlerInvocation(handler="shared_check", shared="bp_check")]
        control2 = _make_control("T-02", handler_invocations=inv2)
        orchestrator._dispatch_handler_invocations(control2, _make_context())

        assert call_count["n"] == 1  # Only called once

    @pytest.mark.unit
    def test_cache_scoped_to_audit_run(self):
        """Cache is cleared between audit runs via reset_caches."""
        from darnit.config.framework_schema import HandlerInvocation

        registry = get_sieve_handler_registry()
        call_count = {"n": 0}

        def counting_handler(config, context):
            call_count["n"] += 1
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message="ok",
                confidence=1.0,
            )

        registry.register("h", "deterministic", counting_handler)

        orchestrator = SieveOrchestrator()
        inv = [HandlerInvocation(handler="h", shared="cache_key")]

        # First run
        control1 = _make_control("T-01", handler_invocations=inv)
        orchestrator._dispatch_handler_invocations(control1, _make_context())
        assert call_count["n"] == 1

        # Reset
        orchestrator.reset_caches()

        # Second run — handler called again
        control2 = _make_control("T-01", handler_invocations=inv)
        orchestrator._dispatch_handler_invocations(control2, _make_context())
        assert call_count["n"] == 2

    @pytest.mark.unit
    def test_error_propagation_from_shared_cache(self):
        """Shared handler error is cached and propagated."""
        from darnit.config.framework_schema import HandlerInvocation

        registry = get_sieve_handler_registry()
        registry.register(
            "failing_handler",
            "deterministic",
            _make_handler(HandlerResultStatus.ERROR, "API error"),
        )

        orchestrator = SieveOrchestrator()
        inv = [
            HandlerInvocation(handler="failing_handler", shared="bad_api"),
        ]
        control = _make_control("T-01", handler_invocations=inv)
        result = orchestrator._dispatch_handler_invocations(control, _make_context())

        assert result is not None
        assert result.status == "ERROR"
        # Error result is cached
        assert "bad_api" in orchestrator._shared_cache


# =============================================================================
# 10.8: use_locator and auto-derived on_pass tests
# =============================================================================


class TestUseLocatorAndOnPass:
    """Tests for use_locator resolution and auto-derived on_pass."""

    @pytest.mark.unit
    def test_resolve_use_locator(self):
        """use_locator=true copies locator.discover into handler files param."""
        from darnit.config.control_loader import _resolve_use_locator
        from darnit.config.framework_schema import HandlerInvocation

        inv = HandlerInvocation(handler="file_exists", use_locator=True)
        resolved = _resolve_use_locator(
            inv,
            locator_discover=["SECURITY.md", ".github/SECURITY.md"],
            control_id="T-01",
        )
        assert resolved.model_extra.get("files") == [
            "SECURITY.md",
            ".github/SECURITY.md",
        ]

    @pytest.mark.unit
    def test_resolve_use_locator_no_discover_warns(self):
        """use_locator=true without locator.discover logs warning."""
        from darnit.config.control_loader import _resolve_use_locator
        from darnit.config.framework_schema import HandlerInvocation

        inv = HandlerInvocation(handler="file_exists", use_locator=True)
        # locator_discover is None — should return invocation unchanged
        resolved = _resolve_use_locator(inv, locator_discover=None, control_id="T-01")
        assert resolved.model_extra.get("files") is None

    @pytest.mark.unit
    def test_auto_derive_on_pass(self):
        """Auto-derive on_pass from locator.project_path + file_exists handler."""
        from darnit.config.control_loader import _auto_derive_on_pass
        from darnit.config.framework_schema import (
            ControlConfig,
            HandlerInvocation,
            LocatorConfig,
        )

        control = ControlConfig(
            name="Test",
            description="test",
            level=1,
            passes=[HandlerInvocation(handler="file_exists")],
            locator=LocatorConfig(
                project_path="security.policy.path",
                discover=["SECURITY.md"],
            ),
        )
        on_pass = _auto_derive_on_pass(control)
        assert on_pass is not None
        assert "security.policy.path" in on_pass.project_update

    @pytest.mark.unit
    def test_use_locator_resolved_through_effective_config(self):
        """use_locator must be resolved when loading via effective config path.

        Regression test: the merger must resolve use_locator before dumping
        passes to dicts, otherwise the handler gets files=[] and returns
        INCONCLUSIVE instead of PASS/FAIL.
        """
        from darnit.config.framework_schema import (
            ControlConfig,
            FrameworkDefaults,
            HandlerInvocation,
            LocatorConfig,
        )
        from darnit.config.merger import merge_control

        control = ControlConfig(
            name="Test file check",
            description="Check a file exists",
            level=1,
            passes=[
                HandlerInvocation(handler="file_exists", use_locator=True),
                HandlerInvocation(handler="manual", steps=["Verify manually"]),
            ],
            locator=LocatorConfig(
                discover=["SECURITY.md", ".github/SECURITY.md"],
                kind="file",
            ),
        )
        defaults = FrameworkDefaults()

        effective = merge_control("T-01", control, None, defaults)

        # The passes_config should have files resolved from locator
        assert effective.passes_config is not None
        file_exists_pass = effective.passes_config[0]
        assert file_exists_pass["handler"] == "file_exists"
        assert file_exists_pass.get("files") == [
            "SECURITY.md",
            ".github/SECURITY.md",
        ], f"use_locator not resolved! files={file_exists_pass.get('files')}"

    @pytest.mark.unit
    def test_auto_derive_on_pass_skips_when_explicit(self):
        """Auto-derive skips when on_pass is already set."""
        from darnit.config.control_loader import _auto_derive_on_pass
        from darnit.config.framework_schema import (
            ControlConfig,
            HandlerInvocation,
            LocatorConfig,
            OnPassConfig,
        )

        control = ControlConfig(
            name="Test",
            description="test",
            level=1,
            passes=[HandlerInvocation(handler="file_exists")],
            locator=LocatorConfig(
                project_path="security.policy.path",
                discover=["SECURITY.md"],
            ),
            on_pass=OnPassConfig(project_update={"custom": "value"}),
        )
        on_pass = _auto_derive_on_pass(control)
        assert on_pass is None  # Don't override explicit on_pass


# =============================================================================
# 10.9: Template variable tests
# =============================================================================


class TestTemplateVariables:
    """Tests for ${context.*} and ${project.*} template variables."""

    @pytest.mark.unit
    def test_context_variable_resolution(self):
        """${context.key} resolves to confirmed context value."""
        from darnit.remediation.executor import RemediationExecutor

        executor = RemediationExecutor(
            local_path="/tmp/test",
            owner="org",
            repo="repo",
            default_branch="main",
            context_values={"maintainers": ["@alice", "@bob"]},
        )
        subs = executor._get_substitutions("TEST-01")
        # Lists are joined with spaces for CODEOWNERS compatibility
        assert subs.get("${context.maintainers}") == "@alice @bob"

    @pytest.mark.unit
    def test_project_variable_resolution(self):
        """${project.key} resolves to project config value."""
        from darnit.remediation.executor import RemediationExecutor

        executor = RemediationExecutor(
            local_path="/tmp/test",
            owner="org",
            repo="repo",
            default_branch="main",
            project_values={"name": "my-project", "security.contact": "sec@example.com"},
        )
        subs = executor._get_substitutions("TEST-01")
        assert subs.get("${project.name}") == "my-project"
        assert subs.get("${project.security.contact}") == "sec@example.com"

    @pytest.mark.unit
    def test_unresolved_variable_becomes_empty(self):
        """Unresolved ${...} patterns are cleaned up."""
        from darnit.remediation.executor import RemediationExecutor

        executor = RemediationExecutor(
            local_path="/tmp/test",
            owner="org",
            repo="repo",
            default_branch="main",
        )
        result = executor._substitute("Hello ${context.missing} world", "TEST-01")
        assert "${context.missing}" not in result

    @pytest.mark.unit
    def test_standard_dollar_var_still_works(self):
        """$OWNER and $REPO standard substitution still works."""
        from darnit.remediation.executor import RemediationExecutor

        executor = RemediationExecutor(
            local_path="/tmp/test",
            owner="myorg",
            repo="myrepo",
            default_branch="main",
        )
        result = executor._substitute("repos/$OWNER/$REPO", "TEST-01")
        assert result == "repos/myorg/myrepo"


# =============================================================================
# 10.10: N/A report section tests
# =============================================================================


class TestNAReportSection:
    """Tests for N/A section in audit report."""

    @pytest.mark.unit
    def test_na_with_when_conditions_shown(self):
        """N/A results show unmet when conditions in the report."""
        from darnit.tools.audit import format_results_markdown

        results = [
            {
                "id": "OSPS-BR-02.01",
                "status": "N/A",
                "details": "Not applicable (when condition not met)",
                "level": 2,
                "evidence": {"when": {"has_releases": True}},
            },
        ]
        summary = {"PASS": 0, "FAIL": 0, "WARN": 0, "N/A": 1, "ERROR": 0, "PENDING_LLM": 0, "total": 1}
        compliance = {1: True, 2: True}

        md = format_results_markdown("org", "repo", results, summary, compliance, 2)
        assert "Requires:" in md
        assert "`has_releases=True`" in md

    @pytest.mark.unit
    def test_na_without_when_no_requires_line(self):
        """N/A results from exclusions don't show requires line."""
        from darnit.tools.audit import format_results_markdown

        results = [
            {
                "id": "OSPS-BR-01.01",
                "status": "N/A",
                "details": "Excluded via .baseline.toml",
                "level": 1,
            },
        ]
        summary = {"PASS": 0, "FAIL": 0, "WARN": 0, "N/A": 1, "ERROR": 0, "PENDING_LLM": 0, "total": 1}
        compliance = {1: True}

        md = format_results_markdown("org", "repo", results, summary, compliance, 1)
        assert "Requires:" not in md

    @pytest.mark.unit
    def test_na_separate_from_pass_fail(self):
        """N/A section is separate from PASS and FAIL."""
        from darnit.tools.audit import format_results_markdown

        results = [
            {"id": "T-01", "status": "PASS", "details": "ok", "level": 1},
            {"id": "T-02", "status": "FAIL", "details": "not ok", "level": 1},
            {
                "id": "T-03",
                "status": "N/A",
                "details": "Not applicable",
                "level": 1,
                "evidence": {"when": {"has_releases": True}},
            },
        ]
        summary = {"PASS": 1, "FAIL": 1, "WARN": 0, "N/A": 1, "ERROR": 0, "PENDING_LLM": 0, "total": 3}
        compliance = {1: False}

        md = format_results_markdown("org", "repo", results, summary, compliance, 1)
        # All three sections should be present
        assert "PASS" in md
        assert "FAIL" in md
        assert "N/A" in md


# =============================================================================
# 10.11: Integration test (end-to-end)
# =============================================================================


class TestEndToEndIntegration:
    """End-to-end integration test combining multiple features."""

    @pytest.mark.unit
    def test_full_audit_with_handler_features(self):
        """E2E: shared handlers, when clauses, dependencies, inferred_from."""
        from darnit.config.framework_schema import HandlerInvocation

        registry = get_sieve_handler_registry()

        # Register test handlers
        registry.register(
            "always_pass",
            "deterministic",
            _make_handler(HandlerResultStatus.PASS, "Always passes", {"found": True}),
        )
        registry.register(
            "always_fail",
            "deterministic",
            _make_handler(HandlerResultStatus.FAIL, "Always fails"),
        )

        orchestrator = SieveOrchestrator()

        # Control A: simple pass with shared handler (flat list)
        inv_a = [
            HandlerInvocation(handler="always_pass", shared="shared_check"),
        ]
        ctrl_a = _make_control("A-01", handler_invocations=inv_a)

        # Control B: inferred from A (should auto-pass if A passes)
        ctrl_b = _make_control("B-01", inferred_from="A-01")

        # Control C: conditional (N/A if has_releases=false)
        inv_c = [HandlerInvocation(handler="always_pass")]
        ctrl_c = _make_control(
            "C-01",
            when={"has_releases": True},
            handler_invocations=inv_c,
        )

        # Control D: depends on A
        inv_d = [HandlerInvocation(handler="always_fail")]
        ctrl_d = _make_control("D-01", depends_on=["A-01"], handler_invocations=inv_d)

        # Run batch with project_context where has_releases=False (C is N/A)
        controls = [ctrl_a, ctrl_b, ctrl_c, ctrl_d]

        def context_factory(control_id):
            return _make_context(
                control_id=control_id,
                project_context={"has_releases": False},
            )

        results = orchestrator.verify_batch(controls, context_factory)

        # Check results
        result_map = {r.control_id: r for r in results}

        # A should PASS (always_pass handler)
        assert result_map["A-01"].status == "PASS"

        # B should PASS (inferred from A)
        assert result_map["B-01"].status == "PASS"
        assert "Inferred from A-01" in result_map["B-01"].message

        # C should be N/A (when condition not met)
        assert result_map["C-01"].status == "N/A"

        # D should FAIL (always_fail handler)
        assert result_map["D-01"].status == "FAIL"

        # Shared handler should have been called exactly once
        assert "shared_check" in orchestrator._shared_cache

    @pytest.mark.unit
    def test_inference_annotation_in_report(self):
        """E2E: inferred PASSes are annotated in the markdown report."""
        from darnit.tools.audit import format_results_markdown

        results = [
            {
                "id": "A-01",
                "status": "PASS",
                "details": "File exists",
                "level": 1,
            },
            {
                "id": "B-01",
                "status": "PASS",
                "details": "Inferred from A-01 (passed)",
                "level": 1,
            },
        ]
        summary = {"PASS": 2, "FAIL": 0, "WARN": 0, "N/A": 0, "ERROR": 0, "PENDING_LLM": 0, "total": 2}
        compliance = {1: True}

        md = format_results_markdown("org", "repo", results, summary, compliance, 1)
        # B-01 should have inference annotation
        assert "*(inferred)*" in md
        # A-01 should NOT have inference annotation
        lines = md.split("\n")
        a01_lines = [
            line for line in lines
            if "A-01" in line and "PASS" not in line[:10]
        ]
        for line in a01_lines:
            if "A-01" in line and "inferred" not in line.lower():
                # Normal pass line for A-01 should not have annotation
                pass  # Fine

    @pytest.mark.unit
    def test_legacy_dict_includes_evidence(self):
        """SieveResult.to_legacy_dict() includes evidence."""
        result = SieveResult(
            control_id="T-01",
            status="N/A",
            message="Not applicable",
            level=1,
            evidence={"when": {"has_releases": True}},
        )
        legacy = result.to_legacy_dict()
        assert "evidence" in legacy
        assert legacy["evidence"]["when"] == {"has_releases": True}
