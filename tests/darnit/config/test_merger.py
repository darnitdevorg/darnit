"""Tests for config merging functionality.

This module tests the framework + user config merging system.
"""

import pytest

from darnit.config.control_loader import control_from_effective
from darnit.config.framework_schema import (
    CheckConfig,
    ControlConfig,
    FrameworkConfig,
    FrameworkDefaults,
    FrameworkMetadata,
    OnPassConfig,
)
from darnit.config.merger import (
    EffectiveConfig,
    EffectiveControl,
    load_framework_config,
    merge_configs,
    merge_control,
)
from darnit.config.user_schema import (
    ControlOverride,
    ControlStatus,
    UserConfig,
    UserSettings,
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


class TestSieveGatingMetadataPreservation:
    """Regression tests for sieve gating metadata surviving the effective-config pipeline.

    The effective-config path (merge_control → control_from_effective) was silently
    dropping ``when``, ``depends_on``, ``inferred_from``, and ``on_pass`` from ALL
    controls, so every when-gate and inferred_from auto-pass was dead in production.
    These tests guard against that regression.
    """

    def _make_framework_control_with_gating(self) -> ControlConfig:
        """Build a FrameworkControl carrying all four gating metadata fields."""
        return ControlConfig(
            name="GatedControl",
            level=1,
            domain="QA",
            description="A control with all sieve gating fields set",
            when={"has_releases": True},
            depends_on=["OSPS-AC-01.01"],
            inferred_from="OSPS-AC-02.01",
            on_pass=OnPassConfig(project_update={"security.policy.path": "$EVIDENCE.relative_path"}),
        )

    def test_merge_control_preserves_gating_metadata(self):
        """All four gating fields must survive merge_control into EffectiveControl."""
        framework_control = self._make_framework_control_with_gating()
        defaults = FrameworkDefaults()

        effective = merge_control("OSPS-QA-02.01", framework_control, None, defaults)

        assert effective.when == {"has_releases": True}, (
            "merge_control dropped 'when' — when-gates will be silently ignored"
        )
        assert effective.depends_on == ["OSPS-AC-01.01"], (
            "merge_control dropped 'depends_on' — control ordering will be wrong"
        )
        assert effective.inferred_from == "OSPS-AC-02.01", (
            "merge_control dropped 'inferred_from' — auto-pass will never trigger"
        )
        assert effective.on_pass is not None, (
            "merge_control dropped 'on_pass' — project context will not be updated on pass"
        )
        assert effective.on_pass.get("project_update", {}).get("security.policy.path") == "$EVIDENCE.relative_path"

    def test_control_from_effective_preserves_gating_metadata(self):
        """All four gating fields must survive control_from_effective into ControlSpec.metadata."""
        framework_control = self._make_framework_control_with_gating()
        defaults = FrameworkDefaults()

        effective = merge_control("OSPS-QA-02.01", framework_control, None, defaults)
        spec = control_from_effective("OSPS-QA-02.01", effective)

        assert "when" in spec.metadata, (
            "control_from_effective dropped 'when' from ControlSpec.metadata"
        )
        assert spec.metadata["when"] == {"has_releases": True}

        assert "depends_on" in spec.metadata, (
            "control_from_effective dropped 'depends_on' from ControlSpec.metadata"
        )
        assert spec.metadata["depends_on"] == ["OSPS-AC-01.01"]

        assert "inferred_from" in spec.metadata, (
            "control_from_effective dropped 'inferred_from' from ControlSpec.metadata"
        )
        assert spec.metadata["inferred_from"] == "OSPS-AC-02.01"

        assert "on_pass" in spec.metadata, (
            "control_from_effective dropped 'on_pass' from ControlSpec.metadata"
        )
        assert spec.metadata["on_pass"].get("project_update", {}).get("security.policy.path") == "$EVIDENCE.relative_path"

    def test_control_without_gating_metadata_is_unaffected(self):
        """Controls without optional gating fields must continue to work normally."""
        framework_control = ControlConfig(
            name="PlainControl",
            level=2,
            domain="BR",
            description="A control with no optional gating fields",
        )
        defaults = FrameworkDefaults()

        effective = merge_control("OSPS-BR-01.01", framework_control, None, defaults)
        spec = control_from_effective("OSPS-BR-01.01", effective)

        # Optional fields default to None — must not appear in metadata
        assert effective.when is None
        assert effective.depends_on is None
        assert effective.inferred_from is None
        assert effective.on_pass is None
        assert "when" not in spec.metadata
        assert "depends_on" not in spec.metadata
        assert "inferred_from" not in spec.metadata
        assert "on_pass" not in spec.metadata


class TestLoadFrameworkConfig:
    def test_load_framework_config_success(self, tmp_path):
        config_path = tmp_path / "valid.toml"
        template_file = tmp_path / "template.md"
        template_file.write_text("Hello $OWNER")

        config_path.write_text("""[metadata]
name = "test"
version = "1.0"
display_name = "test"
[templates.test_template]
file = "template.md"
""")

        config = load_framework_config(config_path)
        assert "test_template" in config.templates
        assert config.templates["test_template"].file == "template.md"

    def test_load_framework_config_missing_template(self, tmp_path):
        config_path = tmp_path / "invalid.toml"

        config_path.write_text("""[metadata]
name = "test"
version = "1.0"
display_name = "test"
[templates.test_template]
file = "missing.md"
""")

        with pytest.raises(FileNotFoundError, match="not found relative to framework config"):
            load_framework_config(config_path)
