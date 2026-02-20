"""Tests for config-to-ControlSpec loading.

This module tests the TOML-based declarative control definition system.
"""

import pytest

from darnit.config.control_loader import (
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
