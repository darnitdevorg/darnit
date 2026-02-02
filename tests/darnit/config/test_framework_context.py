"""Tests for framework context definitions in framework_schema.py.

Tests the ContextDefinitionConfig and FrameworkContextConfig models
that enable declarative context prompts in TOML framework files.
"""


import pytest

from darnit.config.framework_schema import (
    ContextDefinitionConfig,
    FrameworkContextConfig,
)


class TestContextDefinitionConfig:
    """Tests for ContextDefinitionConfig model."""

    def test_basic_boolean_definition(self) -> None:
        """Test basic boolean context definition."""
        defn = ContextDefinitionConfig(
            type="boolean",
            prompt="Does this project make releases?",
            affects=["OSPS-BR-02.01"],
        )
        assert defn.type == "boolean"
        assert "releases" in defn.prompt
        assert defn.affects == ["OSPS-BR-02.01"]
        assert defn.required is False
        assert defn.auto_detect is False

    def test_enum_definition_with_values(self) -> None:
        """Test enum context definition with allowed values."""
        defn = ContextDefinitionConfig(
            type="enum",
            prompt="What CI provider do you use?",
            values=["github", "gitlab", "jenkins"],
            affects=["OSPS-QA-03.01"],
        )
        assert defn.type == "enum"
        assert defn.values == ["github", "gitlab", "jenkins"]

    def test_list_or_path_definition(self) -> None:
        """Test list_or_path context definition with all fields."""
        defn = ContextDefinitionConfig(
            type="list_or_path",
            prompt="Who are the maintainers?",
            hint="Provide GitHub usernames or path to MAINTAINERS.md",
            examples=["@user1, @user2", "MAINTAINERS.md"],
            affects=["OSPS-GV-01.01", "OSPS-GV-01.02"],
            store_as="governance.maintainers",
            auto_detect=False,
            required=False,
        )
        assert defn.type == "list_or_path"
        assert defn.hint is not None
        assert len(defn.examples) == 2
        assert defn.store_as == "governance.maintainers"

    def test_required_definition(self) -> None:
        """Test required context definition."""
        defn = ContextDefinitionConfig(
            type="string",
            prompt="Security contact?",
            affects=["OSPS-VM-01.01"],
            required=True,
        )
        assert defn.required is True


class TestFrameworkContextConfig:
    """Tests for FrameworkContextConfig model."""

    def test_empty_definitions(self) -> None:
        """Test empty context config."""
        config = FrameworkContextConfig()
        assert config.definitions == {}
        assert config.get_definition("missing") is None

    def test_explicit_definitions(self) -> None:
        """Test config with explicit definitions dict."""
        config = FrameworkContextConfig(
            definitions={
                "has_releases": ContextDefinitionConfig(
                    type="boolean",
                    prompt="Does this project make releases?",
                    affects=["OSPS-BR-02.01"],
                ),
            }
        )
        assert len(config.definitions) == 1
        assert config.get_definition("has_releases") is not None

    def test_toml_structure_transformation(self) -> None:
        """Test that TOML structure is correctly transformed.

        TOML [context.key] sections produce:
            {"key": {"type": ..., "prompt": ...}}

        This should be transformed to:
            {"definitions": {"key": {"type": ..., "prompt": ...}}}
        """
        # Simulate what the TOML parser produces
        toml_data = {
            "maintainers": {
                "type": "list_or_path",
                "prompt": "Who are the maintainers?",
                "affects": ["OSPS-GV-01.01"],
            },
            "has_releases": {
                "type": "boolean",
                "prompt": "Does this project make releases?",
                "affects": ["OSPS-BR-02.01"],
            },
        }
        config = FrameworkContextConfig.model_validate(toml_data)
        assert len(config.definitions) == 2
        assert "maintainers" in config.definitions
        assert "has_releases" in config.definitions

    def test_get_definition(self) -> None:
        """Test getting a specific definition."""
        config = FrameworkContextConfig(
            definitions={
                "ci_provider": ContextDefinitionConfig(
                    type="enum",
                    prompt="CI provider?",
                    values=["github", "gitlab"],
                    affects=["OSPS-QA-03.01"],
                ),
            }
        )
        defn = config.get_definition("ci_provider")
        assert defn is not None
        assert defn.type == "enum"
        assert defn.values == ["github", "gitlab"]

        # Missing definition returns None
        assert config.get_definition("missing") is None

    def test_get_definitions_for_control(self) -> None:
        """Test getting definitions that affect a specific control."""
        config = FrameworkContextConfig(
            definitions={
                "maintainers": ContextDefinitionConfig(
                    type="list_or_path",
                    prompt="Maintainers?",
                    affects=["OSPS-GV-01.01", "OSPS-GV-01.02"],
                ),
                "governance_model": ContextDefinitionConfig(
                    type="enum",
                    prompt="Governance?",
                    values=["bdfl", "meritocracy"],
                    affects=["OSPS-GV-01.01"],
                ),
                "has_releases": ContextDefinitionConfig(
                    type="boolean",
                    prompt="Releases?",
                    affects=["OSPS-BR-02.01"],
                ),
            }
        )

        # OSPS-GV-01.01 should match maintainers and governance_model
        gv_defs = config.get_definitions_for_control("OSPS-GV-01.01")
        assert len(gv_defs) == 2
        assert "maintainers" in gv_defs
        assert "governance_model" in gv_defs
        assert "has_releases" not in gv_defs

        # OSPS-BR-02.01 should only match has_releases
        br_defs = config.get_definitions_for_control("OSPS-BR-02.01")
        assert len(br_defs) == 1
        assert "has_releases" in br_defs

        # Unknown control returns empty dict
        unknown_defs = config.get_definitions_for_control("UNKNOWN")
        assert len(unknown_defs) == 0

    def test_get_all_affected_controls(self) -> None:
        """Test getting all control IDs affected by context."""
        config = FrameworkContextConfig(
            definitions={
                "maintainers": ContextDefinitionConfig(
                    type="list_or_path",
                    prompt="Maintainers?",
                    affects=["OSPS-GV-01.01", "OSPS-GV-01.02"],
                ),
                "has_releases": ContextDefinitionConfig(
                    type="boolean",
                    prompt="Releases?",
                    affects=["OSPS-BR-02.01", "OSPS-BR-03.01"],
                ),
            }
        )
        all_controls = config.get_all_affected_controls()
        assert len(all_controls) == 4
        assert "OSPS-GV-01.01" in all_controls
        assert "OSPS-GV-01.02" in all_controls
        assert "OSPS-BR-02.01" in all_controls
        assert "OSPS-BR-03.01" in all_controls


class TestFrameworkContextIntegration:
    """Integration tests for loading context from real TOML file."""

    def test_load_from_toml(self) -> None:
        """Test loading context definitions from the actual TOML file."""
        from pathlib import Path

        from darnit.config import load_framework_config

        toml_path = Path("packages/darnit-baseline/openssf-baseline.toml")
        if not toml_path.exists():
            pytest.skip("TOML file not found")

        config = load_framework_config(toml_path)

        # Should have context definitions
        assert len(config.context.definitions) > 0

        # Check known context keys exist
        assert config.context.get_definition("maintainers") is not None
        assert config.context.get_definition("security_contact") is not None
        assert config.context.get_definition("governance_model") is not None
        assert config.context.get_definition("has_releases") is not None
        assert config.context.get_definition("ci_provider") is not None

    def test_maintainers_definition_structure(self) -> None:
        """Test the maintainers definition has expected structure."""
        from pathlib import Path

        from darnit.config import load_framework_config

        toml_path = Path("packages/darnit-baseline/openssf-baseline.toml")
        if not toml_path.exists():
            pytest.skip("TOML file not found")

        config = load_framework_config(toml_path)
        maintainers = config.context.get_definition("maintainers")

        assert maintainers is not None
        assert maintainers.type == "list_or_path"
        assert "maintainer" in maintainers.prompt.lower()
        assert len(maintainers.affects) >= 1
        assert maintainers.store_as == "governance.maintainers"

    def test_ci_provider_enum_values(self) -> None:
        """Test the ci_provider definition has valid enum values."""
        from pathlib import Path

        from darnit.config import load_framework_config

        toml_path = Path("packages/darnit-baseline/openssf-baseline.toml")
        if not toml_path.exists():
            pytest.skip("TOML file not found")

        config = load_framework_config(toml_path)
        ci_provider = config.context.get_definition("ci_provider")

        assert ci_provider is not None
        assert ci_provider.type == "enum"
        assert ci_provider.values is not None
        assert "github" in ci_provider.values
        assert "gitlab" in ci_provider.values
