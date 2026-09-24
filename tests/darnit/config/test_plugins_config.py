"""Tests for [plugins] verification policy parsing and adapting."""

import pytest

from darnit.config.framework_schema import PluginsConfig
from darnit.config.merger import load_user_config
from darnit.config.user_schema import UserConfig
from darnit.core.verification import VerificationConfig

pytestmark = pytest.mark.unit


class TestFlatKeyParsing:
    """The canonical spellings under `[plugins]`."""

    def test_flat_allow_unsigned(self):
        config = PluginsConfig(**{"allow_unsigned": True})
        assert config.global_allow_unsigned is True

    def test_flat_allow_unsigned_false(self):
        config = PluginsConfig(**{"allow_unsigned": False})
        assert config.global_allow_unsigned is False

    def test_flat_trusted_publishers(self):
        config = PluginsConfig(
            **{"trusted_publishers": ["https://github.com/openssf"]}
        )
        assert config.global_trusted_publishers == ["https://github.com/openssf"]

    def test_flat_keys_are_not_mistaken_for_plugin_names(self):
        config = PluginsConfig(
            **{"allow_unsigned": False, "trusted_publishers": ["my-org"]}
        )
        assert config.plugins == {}


class TestAliasParsing:
    """The legacy global_* spellings remain supported."""

    def test_global_allow_unsigned_alias(self):
        config = PluginsConfig(**{"global_allow_unsigned": True})
        assert config.global_allow_unsigned is True

    def test_global_trusted_publishers_alias(self):
        config = PluginsConfig(
            **{"global_trusted_publishers": ["https://github.com/my-company"]}
        )
        assert config.global_trusted_publishers == [
            "https://github.com/my-company"
        ]

    def test_canonical_wins_over_alias(self):
        config = PluginsConfig(
            **{"allow_unsigned": True, "global_allow_unsigned": False}
        )
        assert config.global_allow_unsigned is True


class TestCombinedParsing:
    """Flat globals and per-plugin subtables coexist."""

    def test_globals_and_per_plugin_together(self):
        config = PluginsConfig(
            **{
                "allow_unsigned": False,
                "trusted_publishers": ["https://github.com/my-org"],
                "darnit-baseline": {"version": ">=1.0.0"},
                "my-dev-plugin": {"allow_unsigned": True},
            }
        )

        assert config.global_allow_unsigned is False
        assert config.global_trusted_publishers == ["https://github.com/my-org"]
        assert set(config.plugins) == {"darnit-baseline", "my-dev-plugin"}
        assert config.plugins["darnit-baseline"].version == ">=1.0.0"

    def test_input_dict_is_not_mutated(self):
        data = {"allow_unsigned": True, "darnit-baseline": {"version": ">=1.0.0"}}
        PluginsConfig(**data)
        assert data == {
            "allow_unsigned": True,
            "darnit-baseline": {"version": ">=1.0.0"},
        }


class TestEmptyDefaults:
    """An empty or absent `[plugins]` table."""

    def test_empty_table_yields_defaults(self):
        config = PluginsConfig(**{})
        assert config.plugins == {}
        assert config.global_allow_unsigned is False
        assert config.global_trusted_publishers == []

    def test_empty_table_records_nothing_as_configured(self):
        """Nothing set means unconfigured, not "operator chose strict"."""
        assert PluginsConfig(**{}).resolve_allow_unsigned() is None


class TestUserConfigTypedField:
    """`[plugins]` is a typed field, not an untyped extra."""

    def test_plugins_is_typed(self):
        user = UserConfig(**{"plugins": {"allow_unsigned": True}})
        assert isinstance(user.plugins, PluginsConfig)
        assert user.plugins.global_allow_unsigned is True

    def test_plugins_not_in_model_extra(self):
        user = UserConfig(**{"plugins": {"allow_unsigned": True}})
        assert "plugins" not in (user.model_extra or {})

    def test_absent_plugins_yields_typed_defaults(self):
        user = UserConfig()
        assert isinstance(user.plugins, PluginsConfig)
        assert user.plugins.resolve_allow_unsigned() is None

    def test_load_user_config_round_trip(self, tmp_path):
        (tmp_path / ".baseline.toml").write_text(
            "\n".join(
                [
                    'version = "1.0"',
                    "",
                    "[plugins]",
                    "allow_unsigned = false",
                    'trusted_publishers = ["https://github.com/my-org"]',
                    "",
                    '[plugins."darnit-baseline"]',
                    'version = ">=1.0.0"',
                ]
            ),
            encoding="utf-8",
        )

        user = load_user_config(tmp_path)

        assert user is not None
        assert isinstance(user.plugins, PluginsConfig)
        assert user.plugins.global_allow_unsigned is False
        assert user.plugins.global_trusted_publishers == [
            "https://github.com/my-org"
        ]
        assert "darnit-baseline" in user.plugins.plugins


class TestResolveAllowUnsigned:
    """Per-plugin inheritance semantics."""

    def test_global_applies_when_no_plugin_block(self):
        config = PluginsConfig(**{"allow_unsigned": False})
        assert config.resolve_allow_unsigned("darnit-baseline") is False

    def test_explicit_per_plugin_overrides_global(self):
        config = PluginsConfig(
            **{"allow_unsigned": False, "my-dev-plugin": {"allow_unsigned": True}}
        )
        assert config.resolve_allow_unsigned("my-dev-plugin") is True
        assert config.resolve_allow_unsigned("other-plugin") is False

    def test_version_only_block_inherits_global(self):
        """A version pin must not silently force strict verification."""
        config = PluginsConfig(
            **{"allow_unsigned": True, "darnit-baseline": {"version": ">=1.0.0"}}
        )
        assert config.resolve_allow_unsigned("darnit-baseline") is True

    def test_version_only_block_with_no_global_is_unconfigured(self):
        config = PluginsConfig(**{"darnit-baseline": {"version": ">=1.0.0"}})
        assert config.resolve_allow_unsigned("darnit-baseline") is None

    def test_explicit_per_plugin_false_is_honored(self):
        config = PluginsConfig(
            **{"allow_unsigned": True, "strict-plugin": {"allow_unsigned": False}}
        )
        assert config.resolve_allow_unsigned("strict-plugin") is False

    def test_unknown_plugin_falls_back_to_global(self):
        config = PluginsConfig(**{"allow_unsigned": False})
        assert config.resolve_allow_unsigned("not-configured") is False


class TestResolveTrustedPublishers:
    """Trusted publishers are additive."""

    def test_global_only(self):
        config = PluginsConfig(**{"trusted_publishers": ["global-org"]})
        assert config.resolve_trusted_publishers() == ["global-org"]

    def test_global_and_per_plugin_union(self):
        config = PluginsConfig(
            **{
                "trusted_publishers": ["global-org"],
                "vendor-plugin": {"trusted_publishers": ["vendor-org"]},
            }
        )
        assert config.resolve_trusted_publishers("vendor-plugin") == [
            "global-org",
            "vendor-org",
        ]

    def test_union_deduplicates(self):
        config = PluginsConfig(
            **{
                "trusted_publishers": ["shared-org"],
                "vendor-plugin": {"trusted_publishers": ["shared-org"]},
            }
        )
        assert config.resolve_trusted_publishers("vendor-plugin") == ["shared-org"]

    def test_per_plugin_publishers_not_leaked_to_others(self):
        config = PluginsConfig(
            **{
                "trusted_publishers": ["global-org"],
                "vendor-plugin": {"trusted_publishers": ["vendor-org"]},
            }
        )
        assert config.resolve_trusted_publishers("other-plugin") == ["global-org"]


class TestFromPluginsConfigAdapter:
    """PluginsConfig -> VerificationConfig."""

    def test_none_yields_permissive_default(self):
        assert VerificationConfig.from_plugins_config(None).allow_unsigned is True

    def test_unconfigured_yields_permissive_default(self):
        config = VerificationConfig.from_plugins_config(PluginsConfig(**{}))
        assert config.allow_unsigned is True
        assert config.trusted_publishers == []

    def test_global_settings_apply(self):
        config = VerificationConfig.from_plugins_config(
            PluginsConfig(
                **{
                    "allow_unsigned": False,
                    "trusted_publishers": ["https://github.com/my-org"],
                }
            )
        )
        assert config.allow_unsigned is False
        assert config.trusted_publishers == ["https://github.com/my-org"]

    def test_explicit_per_plugin_overrides_global(self):
        plugins = PluginsConfig(
            **{"allow_unsigned": False, "my-dev-plugin": {"allow_unsigned": True}}
        )
        assert (
            VerificationConfig.from_plugins_config(
                plugins, "my-dev-plugin"
            ).allow_unsigned
            is True
        )
        assert (
            VerificationConfig.from_plugins_config(
                plugins, "darnit-baseline"
            ).allow_unsigned
            is False
        )

    def test_version_only_block_inherits_global(self):
        plugins = PluginsConfig(
            **{"allow_unsigned": True, "darnit-baseline": {"version": ">=1.0.0"}}
        )
        config = VerificationConfig.from_plugins_config(plugins, "darnit-baseline")
        assert config.allow_unsigned is True

    def test_version_only_block_with_no_global_is_permissive(self):
        plugins = PluginsConfig(**{"darnit-baseline": {"version": ">=1.0.0"}})
        config = VerificationConfig.from_plugins_config(plugins, "darnit-baseline")
        assert config.allow_unsigned is True

    def test_trusted_publishers_union(self):
        plugins = PluginsConfig(
            **{
                "trusted_publishers": ["global-org"],
                "vendor-plugin": {"trusted_publishers": ["vendor-org"]},
            }
        )
        config = VerificationConfig.from_plugins_config(plugins, "vendor-plugin")
        assert config.trusted_publishers == ["global-org", "vendor-org"]

    def test_defaults_are_preserved(self):
        """The adapter only sets policy fields it was given."""
        config = VerificationConfig.from_plugins_config(
            PluginsConfig(**{"allow_unsigned": False})
        )
        assert config.use_default_publishers is True
        assert config.verify_online is True


class TestIsPluginTrusted:
    """is_plugin_trusted() resolves policy through the shared resolvers."""

    def test_explicit_per_plugin_false_overrides_global_true(self):
        config = PluginsConfig(
            **{"allow_unsigned": True, "strict-plugin": {"allow_unsigned": False}}
        )
        assert config.is_plugin_trusted("strict-plugin") is False

    def test_explicit_per_plugin_true_overrides_global_false(self):
        config = PluginsConfig(
            **{"allow_unsigned": False, "my-dev-plugin": {"allow_unsigned": True}}
        )
        assert config.is_plugin_trusted("my-dev-plugin") is True

    def test_version_only_block_inherits_global(self):
        permissive = PluginsConfig(
            **{"allow_unsigned": True, "darnit-baseline": {"version": ">=1.0.0"}}
        )
        strict = PluginsConfig(
            **{"allow_unsigned": False, "darnit-baseline": {"version": ">=1.0.0"}}
        )
        assert permissive.is_plugin_trusted("darnit-baseline") is True
        assert strict.is_plugin_trusted("darnit-baseline") is False

    def test_unconfigured_is_permissive(self):
        assert PluginsConfig(**{}).is_plugin_trusted("anything") is True

    def test_global_and_per_plugin_publishers_both_honored(self):
        config = PluginsConfig(
            **{
                "allow_unsigned": False,
                "trusted_publishers": ["global-org"],
                "vendor-plugin": {"trusted_publishers": ["vendor-org"]},
            }
        )
        assert config.is_plugin_trusted("vendor-plugin", "global-org") is True
        assert config.is_plugin_trusted("vendor-plugin", "vendor-org") is True
        assert config.is_plugin_trusted("vendor-plugin", "other-org") is False
