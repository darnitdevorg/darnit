"""Tests for config merging functionality.

This module tests the framework + user config merging system.
"""

import pytest
from pathlib import Path
import tempfile
import os

from darnit.config.framework_schema import (
    FrameworkConfig,
    FrameworkMetadata,
    FrameworkDefaults,
    ControlConfig,
    PassesConfig,
    DeterministicPassConfig,
    ManualPassConfig,
    CheckConfig,
)

from darnit.config.user_schema import (
    UserConfig,
    UserSettings,
    ControlOverride,
    ControlStatus,
)

from darnit.config.merger import (
    merge_configs,
    merge_control,
    EffectiveConfig,
    EffectiveControl,
)


class TestMergeControl:
    """Test merging individual control configurations."""

    def test_framework_only(self):
        """Test control with no user override."""
        framework_control = ControlConfig(
            name="TestControl",
            level=1,
            domain="AC",
            description="Test description",
            tags={"category": "test"},
        )
        defaults = FrameworkDefaults()

        result = merge_control("TEST-01", framework_control, None, defaults)

        assert isinstance(result, EffectiveControl)
        assert result.name == "TestControl"
        assert result.level == 1
        assert result.domain == "AC"
        assert result.is_applicable() is True

    def test_user_override_status_na(self):
        """Test user marking control as N/A."""
        framework_control = ControlConfig(
            name="TestControl",
            level=1,
            domain="AC",
            description="Test description",
        )
        defaults = FrameworkDefaults()

        user_override = ControlOverride(
            status=ControlStatus.NA,
            reason="Pre-1.0 project, no releases yet",
        )

        result = merge_control("TEST-01", framework_control, user_override, defaults)

        assert result.is_applicable() is False
        assert result.status_reason == "Pre-1.0 project, no releases yet"

    def test_user_override_adapter(self):
        """Test user overriding check adapter."""
        framework_control = ControlConfig(
            name="TestControl",
            level=1,
            domain="AC",
            description="Test description",
        )
        defaults = FrameworkDefaults(check_adapter="builtin")

        user_override = ControlOverride(
            check=CheckConfig(adapter="kusari"),
        )

        result = merge_control("TEST-01", framework_control, user_override, defaults)

        assert result.check_adapter == "kusari"
        assert result.is_applicable() is True


class TestMergeConfigs:
    """Test merging complete framework and user configs."""

    def test_framework_only(self):
        """Test merging when no user config exists."""
        framework = FrameworkConfig(
            metadata=FrameworkMetadata(
                name="test",
                display_name="Test Framework",
                version="1.0",
            ),
            controls={
                "TEST-01": ControlConfig(
                    name="Control1",
                    level=1,
                    domain="AC",
                    description="Test",
                ),
            },
        )

        result = merge_configs(framework, None)

        assert isinstance(result, EffectiveConfig)
        assert "TEST-01" in result.controls
        assert result.controls["TEST-01"].name == "Control1"

    def test_user_exclusions(self):
        """Test that user exclusions are reflected in effective config."""
        framework = FrameworkConfig(
            metadata=FrameworkMetadata(
                name="test",
                display_name="Test Framework",
                version="1.0",
            ),
            controls={
                "TEST-01": ControlConfig(
                    name="Control1",
                    level=1,
                    domain="AC",
                    description="Test",
                ),
                "TEST-02": ControlConfig(
                    name="Control2",
                    level=2,
                    domain="BR",
                    description="Test 2",
                ),
            },
        )

        user = UserConfig(
            version="1.0",
            extends="test",
            controls={
                "TEST-01": ControlOverride(
                    status=ControlStatus.NA,
                    reason="Not needed",
                ),
            },
        )

        result = merge_configs(framework, user)

        assert result.controls["TEST-01"].is_applicable() is False
        assert result.controls["TEST-02"].is_applicable() is True

    def test_get_excluded_controls(self):
        """Test getting the list of excluded controls."""
        framework = FrameworkConfig(
            metadata=FrameworkMetadata(
                name="test",
                display_name="Test Framework",
                version="1.0",
            ),
            controls={
                "TEST-01": ControlConfig(
                    name="Control1",
                    level=1,
                    domain="AC",
                    description="Test",
                ),
                "TEST-02": ControlConfig(
                    name="Control2",
                    level=2,
                    domain="BR",
                    description="Test 2",
                ),
            },
        )

        user = UserConfig(
            version="1.0",
            extends="test",
            controls={
                "TEST-01": ControlOverride(
                    status=ControlStatus.NA,
                    reason="Pre-release project",
                ),
            },
        )

        result = merge_configs(framework, user)
        excluded = result.get_excluded_controls()

        assert "TEST-01" in excluded
        assert excluded["TEST-01"] == "Pre-release project"
        assert "TEST-02" not in excluded


class TestEffectiveControl:
    """Test EffectiveControl behavior."""

    def test_is_applicable_default(self):
        """Test that controls are applicable by default."""
        control = EffectiveControl(
            control_id="TEST-01",
            name="Test",
            level=1,
            domain="AC",
            description="Test",
            status=None,  # No status = applicable
        )

        assert control.is_applicable() is True

    def test_is_applicable_na(self):
        """Test N/A status makes control not applicable."""
        control = EffectiveControl(
            control_id="TEST-01",
            name="Test",
            level=1,
            domain="AC",
            description="Test",
            status=ControlStatus.NA,
            status_reason="Not needed",
        )

        assert control.is_applicable() is False

    def test_is_applicable_disabled(self):
        """Test disabled status makes control not applicable."""
        control = EffectiveControl(
            control_id="TEST-01",
            name="Test",
            level=1,
            domain="AC",
            description="Test",
            status=ControlStatus.DISABLED,
            status_reason="Temporarily disabled",
        )

        assert control.is_applicable() is False


class TestEffectiveConfig:
    """Test EffectiveConfig behavior."""

    def test_get_controls_by_level(self):
        """Test filtering controls by level."""
        config = EffectiveConfig(
            framework_name="test",
            framework_version="1.0",
            controls={
                "L1-01": EffectiveControl(
                    control_id="L1-01",
                    name="L1",
                    level=1,
                    domain="AC",
                    description="Level 1",
                ),
                "L2-01": EffectiveControl(
                    control_id="L2-01",
                    name="L2",
                    level=2,
                    domain="BR",
                    description="Level 2",
                ),
                "L3-01": EffectiveControl(
                    control_id="L3-01",
                    name="L3",
                    level=3,
                    domain="QA",
                    description="Level 3",
                ),
            },
        )

        level1 = config.get_controls_by_level(1)
        level2 = config.get_controls_by_level(2)

        assert len(level1) == 1
        assert "L1-01" in level1
        assert len(level2) == 1
        assert "L2-01" in level2

    def test_get_controls_by_level_excludes_na(self):
        """Test that get_controls_by_level excludes N/A controls."""
        config = EffectiveConfig(
            framework_name="test",
            framework_version="1.0",
            controls={
                "L1-01": EffectiveControl(
                    control_id="L1-01",
                    name="L1Active",
                    level=1,
                    domain="AC",
                    description="Active Level 1",
                ),
                "L1-02": EffectiveControl(
                    control_id="L1-02",
                    name="L1NA",
                    level=1,
                    domain="AC",
                    description="N/A Level 1",
                    status=ControlStatus.NA,
                ),
            },
        )

        level1 = config.get_controls_by_level(1)

        assert len(level1) == 1
        assert "L1-01" in level1
        assert "L1-02" not in level1

    def test_get_applicable_controls(self):
        """Test getting only applicable controls via get_controls_by_level."""
        config = EffectiveConfig(
            framework_name="test",
            framework_version="1.0",
            controls={
                "ACTIVE-01": EffectiveControl(
                    control_id="ACTIVE-01",
                    name="Active",
                    level=1,
                    domain="AC",
                    description="Active control",
                    status=None,
                ),
                "NA-01": EffectiveControl(
                    control_id="NA-01",
                    name="NotApplicable",
                    level=1,
                    domain="AC",
                    description="N/A control",
                    status=ControlStatus.NA,
                    status_reason="Not needed",
                ),
            },
        )

        # get_controls_by_level already filters by is_applicable
        applicable = config.get_controls_by_level(1)

        assert len(applicable) == 1
        assert "ACTIVE-01" in applicable
        assert "NA-01" not in applicable


class TestUserSettings:
    """Test user settings behavior."""

    def test_default_settings(self):
        """Test default user settings."""
        settings = UserSettings()

        assert settings.cache_results is True
        assert settings.timeout == 300

    def test_custom_settings(self):
        """Test custom user settings."""
        settings = UserSettings(
            cache_results=False,
            timeout=60,
        )

        assert settings.cache_results is False
        assert settings.timeout == 60


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
