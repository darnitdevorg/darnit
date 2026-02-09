"""Tests for config-to-ControlSpec loading.

This module tests the TOML-based declarative control definition system.
"""

import pytest

from darnit.config.control_loader import (
    _get_allowed_module_prefixes,
    _is_module_allowed,
    _resolve_check_function,
    control_from_framework,
    load_controls_from_framework,
)

# Test imports
from darnit.config.framework_schema import (
    ControlConfig,
    FrameworkConfig,
    FrameworkMetadata,
    HandlerInvocation,
)
from darnit.sieve.models import ControlSpec


class TestControlFromFramework:
    """Test control_from_framework conversion."""

    def test_basic_control(self):
        """Test basic control conversion."""
        control_config = ControlConfig(
            name="TestControl",
            level=1,
            domain="AC",
            description="A test control",
            tags={"category": "test", "type": "access-control"},
            security_severity=8.0,  # Must be float
            docs_url="https://example.com/docs",
        )

        result = control_from_framework("TEST-01.01", control_config)

        assert isinstance(result, ControlSpec)
        assert result.control_id == "TEST-01.01"
        assert result.name == "TestControl"
        assert result.level == 1
        assert result.domain == "AC"
        assert result.description == "A test control"

    def test_control_with_handler_invocations(self):
        """Test control with flat handler invocation list."""
        control_config = ControlConfig(
            name="FileCheck",
            level=1,
            domain="DO",
            description="Check files exist",
            passes=[
                HandlerInvocation(
                    handler="file_exists",
                    path="README.md",
                ),
                HandlerInvocation(
                    handler="manual",
                    steps=["Verify README exists"],
                ),
            ],
        )

        result = control_from_framework("TEST-02.01", control_config)

        # Handler invocations are stored in metadata, not as legacy pass objects
        assert result.control_id == "TEST-02.01"
        handler_invocations = result.metadata.get("handler_invocations", [])
        assert len(handler_invocations) == 2
        assert handler_invocations[0].handler == "file_exists"
        assert handler_invocations[1].handler == "manual"


class TestLoadControlsFromFramework:
    """Test loading controls from a complete FrameworkConfig."""

    def test_load_multiple_controls(self):
        """Test loading multiple controls from framework."""
        framework = FrameworkConfig(
            metadata=FrameworkMetadata(
                name="test-framework",
                display_name="Test Framework",
                version="1.0.0",
            ),
            controls={
                "TEST-01.01": ControlConfig(
                    name="Control1",
                    level=1,
                    domain="AC",
                    description="First control",
                ),
                "TEST-02.01": ControlConfig(
                    name="Control2",
                    level=2,
                    domain="BR",
                    description="Second control",
                ),
            },
        )

        controls = load_controls_from_framework(framework)

        assert len(controls) == 2
        control_ids = {c.control_id for c in controls}
        assert control_ids == {"TEST-01.01", "TEST-02.01"}

    def test_preserves_levels(self):
        """Test that control levels are preserved."""
        framework = FrameworkConfig(
            metadata=FrameworkMetadata(
                name="test-framework",
                display_name="Test Framework",
                version="1.0.0",
            ),
            controls={
                "TEST-L1": ControlConfig(name="L1", level=1, domain="AC", description="Level 1"),
                "TEST-L2": ControlConfig(name="L2", level=2, domain="AC", description="Level 2"),
                "TEST-L3": ControlConfig(name="L3", level=3, domain="AC", description="Level 3"),
            },
        )

        controls = load_controls_from_framework(framework)
        levels = {c.control_id: c.level for c in controls}

        assert levels["TEST-L1"] == 1
        assert levels["TEST-L2"] == 2
        assert levels["TEST-L3"] == 3


class TestExecPassVariableSubstitution:
    """Test variable substitution in ExecPass."""

    def test_whole_element_substitution(self):
        """Test that ExecPass substitutes whole-element variables correctly."""
        from darnit.sieve.models import CheckContext
        from darnit.sieve.passes import ExecPass

        # Whole-element variables (should be substituted)
        exec_pass = ExecPass(
            command=["gh", "api", "$OWNER", "$REPO"],
            pass_exit_codes=[0],
        )

        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/test",
            default_branch="main",
            control_id="TEST-01",
        )

        # Access the internal method for testing
        substituted = exec_pass._substitute_variables(context)

        assert substituted == ["gh", "api", "test-org", "test-repo"]

    def test_partial_substitution_allowed(self):
        """Test that partial matches ARE substituted (needed for API paths)."""
        from darnit.sieve.models import CheckContext
        from darnit.sieve.passes import ExecPass

        exec_pass = ExecPass(
            command=["gh", "api", "/repos/$OWNER/$REPO"],  # Partial match in path
            pass_exit_codes=[0],
        )

        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/test",
            default_branch="main",
            control_id="TEST-01",
        )

        substituted = exec_pass._substitute_variables(context)

        # Should substitute partial matches (needed for gh api paths)
        assert substituted == ["gh", "api", "/repos/test-org/test-repo"]

    def test_path_substitution(self):
        """Test $PATH variable substitution."""
        from darnit.sieve.models import CheckContext
        from darnit.sieve.passes import ExecPass

        exec_pass = ExecPass(
            command=["ls", "$PATH"],
            pass_exit_codes=[0],
        )

        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/test-repo",
            default_branch="main",
            control_id="TEST-01",
        )

        substituted = exec_pass._substitute_variables(context)

        assert substituted == ["ls", "/tmp/test-repo"]


class TestFrameworkSchemaValidation:
    """Test framework schema validation."""

    def test_valid_framework(self):
        """Test that valid framework configs pass validation."""
        framework = FrameworkConfig(
            metadata=FrameworkMetadata(
                name="valid-framework",
                display_name="Valid Framework",
                version="1.0.0",
            ),
            controls={
                "VALID-01": ControlConfig(
                    name="ValidControl",
                    level=1,
                    domain="AC",
                    description="A valid control",
                ),
            },
        )

        # Should not raise
        assert framework.metadata.name == "valid-framework"

    def test_valid_levels(self):
        """Test that levels 1, 2, 3 are all valid."""
        for level in [1, 2, 3]:
            control = ControlConfig(
                name=f"Level{level}",
                level=level,
                domain="AC",
                description=f"Level {level} control",
            )
            assert control.level == level

    def test_security_severity_float(self):
        """Test that security_severity must be a float."""
        control = ControlConfig(
            name="Test",
            level=1,
            domain="AC",
            description="Test",
            security_severity=7.5,
        )
        assert control.security_severity == 7.5

    def test_legacy_passes_format_rejected(self):
        """Test that legacy phase-bucketed passes format is rejected."""
        with pytest.raises(Exception, match="Legacy phase-bucketed"):
            ControlConfig(
                name="Test",
                level=1,
                domain="AC",
                description="Test",
                passes={
                    "deterministic": {"file_must_exist": ["README.md"]},
                },
            )


class TestModuleImportSecurity:
    """Test security allowlist for dynamic module imports."""

    def test_base_prefixes_always_allowed(self):
        """Test that base darnit prefixes are always allowed."""
        assert _is_module_allowed("darnit.core.plugin")
        assert _is_module_allowed("darnit_baseline.controls.level1")
        assert _is_module_allowed("darnit_plugins.custom")
        assert _is_module_allowed("darnit_testchecks.fixtures")

    def test_blocks_standard_library(self):
        """Test that standard library modules are blocked."""
        assert not _is_module_allowed("os")
        assert not _is_module_allowed("subprocess")
        assert not _is_module_allowed("sys")
        assert not _is_module_allowed("importlib")

    def test_blocks_arbitrary_packages(self):
        """Test that arbitrary third-party packages are blocked."""
        assert not _is_module_allowed("requests")
        assert not _is_module_allowed("flask.app")
        assert not _is_module_allowed("malicious_package.evil")

    def test_resolve_blocks_unauthorized_modules(self):
        """Test that _resolve_check_function blocks unauthorized modules."""
        # These should return None and log a warning
        assert _resolve_check_function("os:system") is None
        assert _resolve_check_function("subprocess:run") is None
        assert _resolve_check_function("malicious:payload") is None

    def test_resolve_allows_registered_modules(self):
        """Test that _resolve_check_function allows registered modules."""
        # This test requires darnit_baseline to be installed
        result = _resolve_check_function(
            "darnit_baseline.controls.level2:_create_changelog_check"
        )
        # Should be callable (the factory returns a check function)
        assert callable(result)

    def test_resolve_invalid_reference_format(self):
        """Test that invalid references are rejected."""
        assert _resolve_check_function("") is None
        assert _resolve_check_function(None) is None  # type: ignore

    def test_resolve_short_name_not_found_without_colon(self):
        """Test helpful error for unregistered short name."""
        # Short name without colon should suggest registration
        assert _resolve_check_function("unknown_handler") is None

    def test_get_allowed_prefixes_includes_base(self):
        """Test that base prefixes are in allowed list."""
        prefixes = _get_allowed_module_prefixes()
        assert "darnit." in prefixes
        assert "darnit_baseline." in prefixes
        assert "darnit_plugins." in prefixes
        assert "darnit_testchecks." in prefixes

    def test_prefix_matching_is_strict(self):
        """Test that prefix matching requires the dot."""
        # These should be blocked - they look similar but aren't valid prefixes
        assert not _is_module_allowed("darnit_malicious.evil")
        assert not _is_module_allowed("darnitfake.payload")


class TestHandlerRegistryResolution:
    """Test handler registry integration with _resolve_check_function."""

    def test_resolve_from_registry_short_name(self):
        """Test that registered handlers are resolved by short name."""
        from darnit.core.handlers import get_handler_registry

        registry = get_handler_registry()

        # Register a test handler
        def test_handler(context):
            return True

        registry.register_handler("test_check_handler", test_handler, plugin="test")

        try:
            # Should resolve from registry
            resolved = _resolve_check_function("test_check_handler")
            assert resolved is test_handler
        finally:
            # Cleanup
            registry._handlers.pop("test_check_handler", None)

    def test_resolve_fallback_to_module_path(self):
        """Test that module:function paths work when not in registry."""
        # This should fall back to module path resolution
        result = _resolve_check_function(
            "darnit_baseline.controls.level2:_create_changelog_check"
        )
        assert callable(result)

    def test_resolve_registry_takes_precedence(self):
        """Test that registry lookup happens before module path parsing."""
        from darnit.core.handlers import get_handler_registry

        registry = get_handler_registry()

        # Register a handler with a name that looks like a module path
        def custom_handler(context):
            return "custom"

        registry.register_handler("my_custom_check", custom_handler, plugin="test")

        try:
            # Should find in registry, not try to parse as module:function
            resolved = _resolve_check_function("my_custom_check")
            assert resolved is custom_handler
        finally:
            registry._handlers.pop("my_custom_check", None)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
