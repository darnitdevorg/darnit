"""Tests for config merging functionality.

This module tests merging a framework with operator configuration.
"""

import pytest

from darnit.config.control_loader import control_from_effective
from darnit.config.framework_schema import (
    ControlConfig,
    FrameworkConfig,
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


class TestMergeControl:
    """Test building a control's effective configuration."""

    def test_framework_only(self):
        """Test control built from its framework definition."""
        framework_control = ControlConfig(
            name="TestControl",
            level=1,
            domain="AC",
            description="Test description",
            tags={"category": "test"},
        )

        result = merge_control("TEST-01", framework_control)

        assert isinstance(result, EffectiveControl)
        assert result.name == "TestControl"
        assert result.level == 1
        assert result.domain == "AC"


class TestRemovedAdapterConfiguration:
    """The adapter keys removed in #487 (framework-design Appendix C)."""

    METADATA = '''[metadata]
name = "removed-adapters"
display_name = "Removed Adapters"
version = "0.1.0"
'''

    def test_control_check_key_fails_loading(self, tmp_path):
        path = tmp_path / "framework.toml"
        path.write_text(
            self.METADATA
            + '''
[controls."TEST-01"]
name = "TestControl"
description = "Test description"
check = { adapter = "kusari" }
'''
        )

        with pytest.raises(ValueError, match="control 'TEST-01' has unknown key 'check'"):
            load_framework_config(path)

    def test_adapter_tables_still_load_and_are_not_read(self, tmp_path):
        path = tmp_path / "framework.toml"
        path.write_text(
            self.METADATA
            + '''
[defaults]
check_adapter = "kusari"
remediation_adapter = "builtin"

[adapters.kusari]
type = "command"
command = "kusari"

[controls."TEST-01"]
name = "TestControl"
description = "Test description"
'''
        )

        effective = merge_configs(load_framework_config(path))

        assert list(effective.controls) == ["TEST-01"]
        assert not hasattr(effective, "adapters")
        assert not hasattr(effective.controls["TEST-01"], "check_adapter")


class TestMergeConfigs:
    """Test merging a framework with operator configuration."""

    def test_framework_only(self):
        """Test merging with no operator configuration."""
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

        result = merge_configs(framework)

        assert isinstance(result, EffectiveConfig)
        assert "TEST-01" in result.controls
        assert result.controls["TEST-01"].name == "Control1"


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

        effective = merge_control("OSPS-QA-02.01", framework_control)

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

        effective = merge_control("OSPS-QA-02.01", framework_control)
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

        effective = merge_control("OSPS-BR-01.01", framework_control)
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
