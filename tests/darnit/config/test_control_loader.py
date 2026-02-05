"""Tests for config-to-ControlSpec loading.

This module tests the TOML-based declarative control definition system.
"""

import pytest

from darnit.config.control_loader import (
    _convert_deterministic_pass,
    _convert_exec_pass,
    _convert_manual_pass,
    _convert_pattern_pass,
    _get_allowed_module_prefixes,
    _is_module_allowed,
    _resolve_check_function,
    control_from_framework,
    load_controls_from_framework,
)

# Test imports
from darnit.config.framework_schema import (
    ControlConfig,
    DeterministicPassConfig,
    ExecPassConfig,
    FrameworkConfig,
    FrameworkMetadata,
    ManualPassConfig,
    PassesConfig,
    PatternPassConfig,
)
from darnit.sieve.models import ControlSpec
from darnit.sieve.passes import (
    DeterministicPass,
    ExecPass,
    ManualPass,
    PatternPass,
)


class TestDeterministicPassConversion:
    """Test conversion of DeterministicPassConfig to DeterministicPass."""

    def test_file_must_exist(self):
        """Test file_must_exist conversion."""
        config = DeterministicPassConfig(
            file_must_exist=["README.md", "LICENSE"],
        )
        result = _convert_deterministic_pass(config)

        assert isinstance(result, DeterministicPass)
        assert result.file_must_exist == ["README.md", "LICENSE"]

    def test_file_must_not_exist(self):
        """Test file_must_not_exist conversion."""
        config = DeterministicPassConfig(
            file_must_not_exist=[".env", "secrets.json"],
        )
        result = _convert_deterministic_pass(config)

        assert isinstance(result, DeterministicPass)
        assert result.file_must_not_exist == [".env", "secrets.json"]

    def test_both_file_conditions(self):
        """Test both file conditions together."""
        config = DeterministicPassConfig(
            file_must_exist=["README.md"],
            file_must_not_exist=[".env"],
        )
        result = _convert_deterministic_pass(config)

        assert result.file_must_exist == ["README.md"]
        assert result.file_must_not_exist == [".env"]


class TestExecPassConversion:
    """Test conversion of ExecPassConfig to ExecPass."""

    def test_basic_command(self):
        """Test basic command conversion."""
        config = ExecPassConfig(
            command=["gh", "api", "/repos/owner/repo"],
            pass_exit_codes=[0],
            output_format="json",
            timeout=30,
        )
        result = _convert_exec_pass(config)

        assert isinstance(result, ExecPass)
        assert result.command == ["gh", "api", "/repos/owner/repo"]
        assert result.pass_exit_codes == [0]
        assert result.output_format == "json"
        assert result.timeout == 30

    def test_json_path_matching(self):
        """Test JSON path matching configuration."""
        config = ExecPassConfig(
            command=["gh", "api", "/orgs/testorg"],
            pass_exit_codes=[0],
            output_format="json",
            pass_if_json_path="two_factor_requirement_enabled",
            pass_if_json_value="true",
        )
        result = _convert_exec_pass(config)

        assert result.pass_if_json_path == "two_factor_requirement_enabled"
        assert result.pass_if_json_value == "true"

    def test_output_matching(self):
        """Test output pattern matching configuration."""
        config = ExecPassConfig(
            command=["cat", "README.md"],
            pass_exit_codes=[0],
            output_format="text",
            pass_if_output_matches=r"MIT License",
        )
        result = _convert_exec_pass(config)

        assert result.pass_if_output_matches == r"MIT License"

    def test_fail_exit_codes(self):
        """Test fail_exit_codes configuration."""
        config = ExecPassConfig(
            command=["gh", "api", "/some/endpoint"],
            pass_exit_codes=[0],
            fail_exit_codes=[1, 2],
        )
        result = _convert_exec_pass(config)

        assert result.fail_exit_codes == [1, 2]

    def test_environment_variables(self):
        """Test environment variable configuration."""
        config = ExecPassConfig(
            command=["custom-checker"],
            pass_exit_codes=[0],
            env={"CUSTOM_VAR": "value", "ANOTHER_VAR": "another"},
        )
        result = _convert_exec_pass(config)

        assert result.env == {"CUSTOM_VAR": "value", "ANOTHER_VAR": "another"}


class TestPatternPassConversion:
    """Test conversion of PatternPassConfig to PatternPass."""

    def test_file_patterns(self):
        """Test file pattern configuration."""
        config = PatternPassConfig(
            files=[".github/workflows/*.yml"],
        )
        result = _convert_pattern_pass(config)

        assert isinstance(result, PatternPass)
        assert result.file_patterns == [".github/workflows/*.yml"]

    def test_content_patterns(self):
        """Test content pattern matching."""
        config = PatternPassConfig(
            files=["SECURITY.md"],
            patterns={
                "email": r"[\w.-]+@[\w.-]+\.\w+",
                "reporting": r"report.*vulnerabilit",
            },
            pass_if_any_match=True,
        )
        result = _convert_pattern_pass(config)

        assert result.content_patterns == {
            "email": r"[\w.-]+@[\w.-]+\.\w+",
            "reporting": r"report.*vulnerabilit",
        }
        assert result.pass_if_any_match is True

    def test_fail_if_no_match(self):
        """Test fail_if_no_match configuration."""
        config = PatternPassConfig(
            files=["README.md"],
            fail_if_no_match=True,
        )
        result = _convert_pattern_pass(config)

        assert result.fail_if_no_match is True


class TestManualPassConversion:
    """Test conversion of ManualPassConfig to ManualPass."""

    def test_verification_steps(self):
        """Test verification steps conversion."""
        config = ManualPassConfig(
            steps=[
                "Check repository settings",
                "Verify branch protection is enabled",
            ],
        )
        result = _convert_manual_pass(config)

        assert isinstance(result, ManualPass)
        assert result.verification_steps == [
            "Check repository settings",
            "Verify branch protection is enabled",
        ]

    def test_docs_url(self):
        """Test docs_url configuration."""
        config = ManualPassConfig(
            steps=["Check settings"],
            docs_url="https://docs.example.com/verify",
        )
        result = _convert_manual_pass(config)

        assert result.verification_docs_url == "https://docs.example.com/verify"


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

    def test_control_with_passes(self):
        """Test control with passes configuration."""
        control_config = ControlConfig(
            name="FileCheck",
            level=1,
            domain="DO",
            description="Check files exist",
            passes=PassesConfig(
                deterministic=DeterministicPassConfig(
                    file_must_exist=["README.md"],
                ),
                manual=ManualPassConfig(
                    steps=["Verify README exists"],
                ),
            ),
        )

        result = control_from_framework("TEST-02.01", control_config)

        assert len(result.passes) == 2
        assert isinstance(result.passes[0], DeterministicPass)
        assert isinstance(result.passes[1], ManualPass)


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
