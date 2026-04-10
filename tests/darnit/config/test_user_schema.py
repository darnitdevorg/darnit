"""Tests for user_schema module.

Tests for darnit.config.user_schema - Pydantic models for
user customisation configuration loaded from .baseline.toml.
"""


from darnit.config.framework_schema import CheckConfig, CommandAdapterConfig
from darnit.config.user_schema import (
    ControlGroup,
    ControlOverride,
    ControlStatus,
    CustomControl,
    UserConfig,
    UserSettings,
    create_user_config,
    create_user_config_with_kusari,
)

# ---------------------------------------------------------------------------
# UserSettings
# ---------------------------------------------------------------------------


class TestUserSettings:
    def test_defaults(self):
        s = UserSettings()

        assert s.cache_results is True
        assert s.cache_ttl == 300
        assert s.timeout == 300
        assert s.fail_on_error is False
        assert s.parallel_checks is True
        assert s.max_parallel == 5

    def test_custom_values(self):
        s = UserSettings(cache_results=False, timeout=60, max_parallel=10)

        assert s.cache_results is False
        assert s.timeout == 60
        assert s.max_parallel == 10

    def test_extra_fields_allowed(self):
        """UserSettings allows extra fields (ConfigDict extra=allow)."""
        s = UserSettings(my_custom_key="value")

        assert s.my_custom_key == "value"


# ---------------------------------------------------------------------------
# ControlStatus enum
# ---------------------------------------------------------------------------


class TestControlStatus:
    def test_na_value(self):
        assert ControlStatus.NA == "n/a"

    def test_enabled_value(self):
        assert ControlStatus.ENABLED == "enabled"

    def test_disabled_value(self):
        assert ControlStatus.DISABLED == "disabled"


# ---------------------------------------------------------------------------
# ControlOverride
# ---------------------------------------------------------------------------


class TestControlOverride:
    def test_minimal_override(self):
        override = ControlOverride()

        assert override.status is None
        assert override.reason is None
        assert override.check is None
        assert override.passes is None

    def test_na_override(self):
        override = ControlOverride(status=ControlStatus.NA, reason="Not needed")

        assert override.status == ControlStatus.NA
        assert override.reason == "Not needed"

    def test_disabled_override(self):
        override = ControlOverride(status=ControlStatus.DISABLED, reason="Temp disabled")

        assert override.status == ControlStatus.DISABLED

    def test_check_override(self):
        override = ControlOverride(check=CheckConfig(adapter="kusari"))

        assert override.check is not None
        assert override.check.adapter == "kusari"


# ---------------------------------------------------------------------------
# ControlGroup
# ---------------------------------------------------------------------------


class TestControlGroup:
    def test_basic_group(self):
        group = ControlGroup(
            controls=["CTRL-01", "CTRL-02"],
            check=CheckConfig(adapter="kusari"),
        )

        assert "CTRL-01" in group.controls
        assert group.check.adapter == "kusari"

    def test_empty_config_by_default(self):
        group = ControlGroup(controls=["CTRL-01"])

        assert group.config == {}
        assert group.check is None
        assert group.remediation is None


# ---------------------------------------------------------------------------
# UserConfig.get_control_override
# ---------------------------------------------------------------------------


class TestGetControlOverride:
    def test_returns_none_when_no_overrides(self):
        config = UserConfig()

        assert config.get_control_override("CTRL-01") is None

    def test_returns_direct_override(self):
        override = ControlOverride(status=ControlStatus.NA, reason="N/A")
        config = UserConfig(controls={"CTRL-01": override})

        result = config.get_control_override("CTRL-01")

        assert result is not None
        assert result.status == ControlStatus.NA

    def test_returns_override_from_dict(self):
        config = UserConfig(controls={"CTRL-01": {"status": "n/a", "reason": "test"}})

        result = config.get_control_override("CTRL-01")

        assert result is not None
        assert result.status == ControlStatus.NA

    def test_returns_override_from_group(self):
        group = ControlGroup(
            controls=["CTRL-01"],
            check=CheckConfig(adapter="kusari"),
        )
        config = UserConfig(control_groups={"my-group": group})

        result = config.get_control_override("CTRL-01")

        assert result is not None
        assert result.check is not None
        assert result.check.adapter == "kusari"

    def test_direct_override_takes_priority_over_group(self):
        direct = ControlOverride(status=ControlStatus.NA, reason="direct")
        group = ControlGroup(
            controls=["CTRL-01"],
            check=CheckConfig(adapter="kusari"),
        )
        config = UserConfig(
            controls={"CTRL-01": direct},
            control_groups={"my-group": group},
        )

        result = config.get_control_override("CTRL-01")

        assert result.status == ControlStatus.NA


# ---------------------------------------------------------------------------
# UserConfig.is_control_applicable
# ---------------------------------------------------------------------------


class TestIsControlApplicable:
    def test_applicable_by_default(self):
        config = UserConfig()

        applicable, reason = config.is_control_applicable("CTRL-01")

        assert applicable is True
        assert reason is None

    def test_not_applicable_when_na(self):
        config = UserConfig(
            controls={"CTRL-01": ControlOverride(status=ControlStatus.NA, reason="Pre-1.0")}
        )

        applicable, reason = config.is_control_applicable("CTRL-01")

        assert applicable is False
        assert reason == "Pre-1.0"

    def test_not_applicable_when_disabled(self):
        config = UserConfig(
            controls={"CTRL-01": ControlOverride(status=ControlStatus.DISABLED, reason="skip")}
        )

        applicable, reason = config.is_control_applicable("CTRL-01")

        assert applicable is False

    def test_applicable_when_explicitly_enabled(self):
        config = UserConfig(
            controls={"CTRL-01": ControlOverride(status=ControlStatus.ENABLED)}
        )

        applicable, reason = config.is_control_applicable("CTRL-01")

        assert applicable is True


# ---------------------------------------------------------------------------
# UserConfig.get_check_adapter
# ---------------------------------------------------------------------------


class TestGetCheckAdapter:
    def test_returns_none_when_no_override(self):
        config = UserConfig()

        assert config.get_check_adapter("CTRL-01") is None

    def test_returns_adapter_from_override(self):
        config = UserConfig(
            controls={"CTRL-01": ControlOverride(check=CheckConfig(adapter="custom"))}
        )

        assert config.get_check_adapter("CTRL-01") == "custom"

    def test_returns_none_when_override_has_no_check(self):
        config = UserConfig(
            controls={"CTRL-01": ControlOverride(status=ControlStatus.NA)}
        )

        assert config.get_check_adapter("CTRL-01") is None


# ---------------------------------------------------------------------------
# UserConfig.get_custom_controls
# ---------------------------------------------------------------------------


class TestGetCustomControls:
    def test_returns_empty_when_no_custom_controls(self):
        config = UserConfig(
            controls={"CTRL-01": ControlOverride(status=ControlStatus.NA)}
        )

        assert config.get_custom_controls() == {}

    def test_returns_custom_control_from_dict(self):
        config = UserConfig(
            controls={
                "CUSTOM-01": {
                    "name": "MyCustomControl",
                    "level": 1,
                    "domain": "SA",
                    "description": "Custom check",
                    "custom": True,
                }
            }
        )

        result = config.get_custom_controls()

        assert "CUSTOM-01" in result
        assert result["CUSTOM-01"].name == "MyCustomControl"

    def test_returns_custom_control_instance(self):
        custom = CustomControl(
            name="MyControl",
            level=1,
            domain="SA",
            description="My custom control",
        )
        config = UserConfig(controls={"CUSTOM-01": custom})

        result = config.get_custom_controls()

        assert "CUSTOM-01" in result

    def test_override_without_custom_fields_not_returned(self):
        """ControlOverride without name/level/domain is NOT a custom control."""
        config = UserConfig(
            controls={"CTRL-01": {"status": "n/a", "reason": "not applicable"}}
        )

        result = config.get_custom_controls()

        assert "CTRL-01" not in result


# ---------------------------------------------------------------------------
# UserConfig.get_adapter_config / get_all_adapter_names
# ---------------------------------------------------------------------------


class TestAdapterHelpers:
    def test_get_adapter_config_returns_none_for_missing(self):
        config = UserConfig()

        assert config.get_adapter_config("nonexistent") is None

    def test_get_adapter_config_returns_config(self):
        adapter = CommandAdapterConfig(command="kusari")
        config = UserConfig(adapters={"kusari": adapter})

        result = config.get_adapter_config("kusari")

        assert result is not None

    def test_get_all_adapter_names_empty(self):
        config = UserConfig()

        assert config.get_all_adapter_names() == []

    def test_get_all_adapter_names(self):
        config = UserConfig(
            adapters={
                "kusari": CommandAdapterConfig(command="kusari"),
                "custom": {"type": "script", "command": "./check.sh"},
            }
        )

        names = config.get_all_adapter_names()

        assert set(names) == {"kusari", "custom"}


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


class TestCreateUserConfig:
    def test_defaults_to_openssf_baseline(self):
        config = create_user_config()

        assert config.extends == "openssf-baseline"
        assert config.version == "1.0"

    def test_custom_extends(self):
        config = create_user_config(extends="my-framework")

        assert config.extends == "my-framework"

    def test_extends_none(self):
        config = create_user_config(extends=None)

        assert config.extends is None

    def test_returns_user_config_instance(self):
        config = create_user_config()

        assert isinstance(config, UserConfig)


class TestCreateUserConfigWithKusari:
    def test_has_kusari_adapter(self):
        config = create_user_config_with_kusari()

        assert "kusari" in config.adapters

    def test_default_controls_for_kusari(self):
        config = create_user_config_with_kusari()

        # Default controls are OSPS-VM-05.02 and OSPS-VM-05.03 in a group
        all_group_controls = []
        for group in config.control_groups.values():
            all_group_controls.extend(group.controls)

        assert "OSPS-VM-05.02" in all_group_controls
        assert "OSPS-VM-05.03" in all_group_controls

    def test_custom_controls_list(self):
        config = create_user_config_with_kusari(controls=["CTRL-01", "CTRL-02"])

        all_group_controls = []
        for group in config.control_groups.values():
            all_group_controls.extend(group.controls)

        assert "CTRL-01" in all_group_controls
        assert "CTRL-02" in all_group_controls

    def test_extends_openssf_baseline(self):
        config = create_user_config_with_kusari()

        assert config.extends == "openssf-baseline"
