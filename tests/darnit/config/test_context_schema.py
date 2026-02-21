"""Tests for context schema models.

Tests the core Pydantic models for the Interactive Context Collection System.
"""

from datetime import UTC, datetime

import pytest

from darnit.config.context_schema import (
    BaselineExtension,
    BaselineExtensionConfig,
    CNCFProjectConfig,
    ContextDefinition,
    ContextPromptRequest,
    ContextSource,
    ContextType,
    ContextValue,
    ExtensionMetadata,
    ProjectExtensions,
)


class TestContextValue:
    """Tests for ContextValue model."""

    def test_basic_creation(self) -> None:
        """Test basic ContextValue creation."""
        value = ContextValue(
            source=ContextSource.USER_CONFIRMED,
            value=True,
        )
        assert value.source == "user_confirmed"
        assert value.value is True
        assert value.confidence == 1.0

    def test_with_timestamps(self) -> None:
        """Test ContextValue with timestamps."""
        now = datetime.now(UTC)
        value = ContextValue(
            source=ContextSource.USER_CONFIRMED,
            value=["@user1", "@user2"],
            confirmed_at=now,
        )
        assert value.confirmed_at == now
        assert value.detected_at is None

    def test_auto_detected_with_method(self) -> None:
        """Test auto-detected value with detection method."""
        now = datetime.now(UTC)
        value = ContextValue(
            source=ContextSource.AUTO_DETECTED,
            value="github",
            detected_at=now,
            detection_method="workflow_scan",
            confidence=0.8,
        )
        assert value.source == "auto_detected"
        assert value.detection_method == "workflow_scan"
        assert value.confidence == 0.8

    def test_confidence_bounds(self) -> None:
        """Test confidence must be between 0 and 1."""
        with pytest.raises(ValueError):
            ContextValue(
                source=ContextSource.DEFAULT,
                value="test",
                confidence=1.5,  # Invalid - above 1.0
            )

        with pytest.raises(ValueError):
            ContextValue(
                source=ContextSource.DEFAULT,
                value="test",
                confidence=-0.1,  # Invalid - below 0.0
            )

    def test_user_confirmed_factory(self) -> None:
        """Test user_confirmed factory method."""
        value = ContextValue.user_confirmed(["@maintainer1"])
        assert value.source == "user_confirmed"
        assert value.value == ["@maintainer1"]
        assert value.confidence == 1.0
        assert value.confirmed_at is not None

    def test_auto_detected_factory(self) -> None:
        """Test auto_detected factory method."""
        value = ContextValue.auto_detected(
            value="github",
            method="ci_file_scan",
            confidence=0.9,
        )
        assert value.source == "auto_detected"
        assert value.value == "github"
        assert value.detection_method == "ci_file_scan"
        assert value.confidence == 0.9
        assert value.detected_at is not None

    def test_file_reference_factory(self) -> None:
        """Test file_reference factory method."""
        value = ContextValue.file_reference("MAINTAINERS.md")
        assert value.source == "file_reference"
        assert value.value == "MAINTAINERS.md"
        assert value.confidence == 0.9

    def test_default_factory(self) -> None:
        """Test default factory method."""
        value = ContextValue.default(False)
        assert value.source == "default"
        assert value.value is False
        assert value.confidence == 0.5

    def test_serialization(self) -> None:
        """Test JSON serialization."""
        now = datetime(2025, 1, 26, 12, 0, 0, tzinfo=UTC)
        value = ContextValue(
            source=ContextSource.USER_CONFIRMED,
            value=["@user1"],
            confirmed_at=now,
        )
        data = value.model_dump(mode="json")
        assert data["source"] == "user_confirmed"
        assert data["value"] == ["@user1"]
        assert "confirmed_at" in data

    def test_deserialization(self) -> None:
        """Test loading from dict."""
        data = {
            "source": "auto_detected",
            "value": True,
            "detected_at": "2025-01-26T12:00:00Z",
            "detection_method": "file_exists",
            "confidence": 0.7,
        }
        value = ContextValue.model_validate(data)
        assert value.source == "auto_detected"
        assert value.value is True
        assert value.confidence == 0.7


class TestContextDefinition:
    """Tests for ContextDefinition model."""

    def test_boolean_definition(self) -> None:
        """Test boolean context definition."""
        defn = ContextDefinition(
            type=ContextType.BOOLEAN,
            prompt="Does this project make releases?",
            affects=["OSPS-BR-02.01", "OSPS-BR-04.01"],
        )
        assert defn.type == "boolean"
        assert "releases" in defn.prompt
        assert len(defn.affects) == 2

    def test_enum_definition(self) -> None:
        """Test enum context definition with values."""
        defn = ContextDefinition(
            type=ContextType.ENUM,
            prompt="What CI provider?",
            values=["github", "gitlab", "jenkins"],
            affects=["OSPS-BR-01.01"],
        )
        assert defn.type == "enum"
        assert defn.values == ["github", "gitlab", "jenkins"]

    def test_list_or_path_definition(self) -> None:
        """Test list_or_path context definition."""
        defn = ContextDefinition(
            type=ContextType.LIST_OR_PATH,
            prompt="Who are the maintainers?",
            hint="Provide usernames or path to MAINTAINERS.md",
            examples=["@user1, @user2", "MAINTAINERS.md"],
            affects=["OSPS-GV-01.01", "OSPS-GV-01.02"],
            store_as="governance.maintainers",
        )
        assert defn.type == "list_or_path"
        assert defn.hint is not None
        assert len(defn.examples) == 2
        assert defn.store_as == "governance.maintainers"

    def test_serialization(self) -> None:
        """Test JSON serialization."""
        defn = ContextDefinition(
            type=ContextType.STRING,
            prompt="Security contact?",
            affects=["OSPS-VM-01.01"],
            required=True,
        )
        data = defn.model_dump(mode="json")
        assert data["type"] == "string"
        assert data["required"] is True


class TestContextDefinitionPresentationHints:
    """Tests for presentation hint fields on ContextDefinition."""

    def test_presentation_hint_field_parses(self) -> None:
        """Test that presentation_hint field parses from dict."""
        defn = ContextDefinition(
            type=ContextType.BOOLEAN,
            prompt="Does this project make releases?",
            affects=["OSPS-BR-02.01"],
            presentation_hint="[y/N]",
        )
        assert defn.presentation_hint == "[y/N]"

    def test_allowed_values_field_parses(self) -> None:
        """Test that allowed_values field parses from dict."""
        defn = ContextDefinition(
            type=ContextType.ENUM,
            prompt="CI provider?",
            values=["github", "gitlab", "jenkins", "other"],
            affects=["OSPS-QA-03.01"],
            allowed_values=["github", "gitlab", "other"],
        )
        assert defn.allowed_values == ["github", "gitlab", "other"]

    def test_computed_hint_boolean_default(self) -> None:
        """Test computed hint defaults to [y/N] for boolean type."""
        defn = ContextDefinition(
            type=ContextType.BOOLEAN,
            prompt="Has releases?",
            affects=[],
        )
        assert defn.computed_presentation_hint == "[y/N]"

    def test_computed_hint_boolean_explicit_override(self) -> None:
        """Test explicit presentation_hint overrides boolean default."""
        defn = ContextDefinition(
            type=ContextType.BOOLEAN,
            prompt="Has releases?",
            affects=[],
            presentation_hint="[Y/n]",
        )
        assert defn.computed_presentation_hint == "[Y/n]"

    def test_computed_hint_enum_auto_generated(self) -> None:
        """Test computed hint auto-generates from values for enum type."""
        defn = ContextDefinition(
            type=ContextType.ENUM,
            prompt="CI provider?",
            values=["github", "gitlab", "jenkins"],
            affects=[],
        )
        assert defn.computed_presentation_hint == "[github/gitlab/jenkins]"

    def test_computed_hint_enum_uses_allowed_values_over_values(self) -> None:
        """Test allowed_values takes precedence over values for enum hint."""
        defn = ContextDefinition(
            type=ContextType.ENUM,
            prompt="CI provider?",
            values=["github", "gitlab", "jenkins", "circleci", "azure", "travis", "none", "other"],
            allowed_values=["github", "gitlab", "other"],
            affects=[],
        )
        assert defn.computed_presentation_hint == "[github/gitlab/other]"

    def test_computed_hint_string_returns_none(self) -> None:
        """Test computed hint returns None for string type without explicit hint."""
        defn = ContextDefinition(
            type=ContextType.STRING,
            prompt="Security contact?",
            affects=[],
        )
        assert defn.computed_presentation_hint is None

    def test_computed_hint_list_returns_none(self) -> None:
        """Test computed hint returns None for list type without explicit hint."""
        defn = ContextDefinition(
            type=ContextType.LIST,
            prompt="Maintainers?",
            affects=[],
        )
        assert defn.computed_presentation_hint is None

    def test_fields_default_to_none(self) -> None:
        """Test both fields default to None when not provided."""
        defn = ContextDefinition(
            type=ContextType.STRING,
            prompt="Test?",
            affects=[],
        )
        assert defn.presentation_hint is None
        assert defn.allowed_values is None


class TestContextPromptRequest:
    """Tests for ContextPromptRequest model."""

    def test_basic_creation(self) -> None:
        """Test basic prompt request."""
        defn = ContextDefinition(
            type=ContextType.LIST_OR_PATH,
            prompt="Who are the maintainers?",
            affects=["OSPS-GV-01.01"],
        )
        request = ContextPromptRequest(
            key="maintainers",
            definition=defn,
            control_ids=["OSPS-GV-01.01", "OSPS-GV-01.02"],
            priority=2,
        )
        assert request.key == "maintainers"
        assert request.priority == 2
        assert len(request.control_ids) == 2

    def test_with_current_value(self) -> None:
        """Test prompt request with auto-detected value."""
        defn = ContextDefinition(
            type=ContextType.ENUM,
            prompt="CI provider?",
            values=["github", "gitlab"],
            affects=["OSPS-BR-01.01"],
        )
        current = ContextValue.auto_detected("github", "workflow_scan")
        request = ContextPromptRequest(
            key="ci_provider",
            definition=defn,
            control_ids=["OSPS-BR-01.01"],
            current_value=current,
        )
        assert request.current_value is not None
        assert request.current_value.value == "github"


class TestCNCFExtensionModels:
    """Tests for CNCF extension format models."""

    def test_extension_metadata(self) -> None:
        """Test ExtensionMetadata creation."""
        meta = ExtensionMetadata(
            author="OpenSSF",
            homepage="https://baseline.openssf.org",
            version="0.1.0",
        )
        assert meta.author == "OpenSSF"
        assert meta.version == "0.1.0"

    def test_baseline_extension_config(self) -> None:
        """Test BaselineExtensionConfig with context."""
        config = BaselineExtensionConfig(
            context={
                "governance": {
                    "maintainers": ContextValue.user_confirmed(["@user1"]),
                },
            },
            controls={
                "OSPS-BR-02.01": {"status": "not_applicable", "reason": "No releases"},
            },
        )
        assert "governance" in config.context
        assert "OSPS-BR-02.01" in config.controls

    def test_baseline_extension(self) -> None:
        """Test full BaselineExtension."""
        ext = BaselineExtension(
            metadata=ExtensionMetadata(author="OpenSSF"),
            config=BaselineExtensionConfig(),
        )
        assert ext.metadata.author == "OpenSSF"

    def test_project_extensions_alias(self) -> None:
        """Test ProjectExtensions handles hyphenated key."""
        data = {
            "openssf-baseline": {
                "metadata": {"author": "OpenSSF"},
                "config": {},
            }
        }
        extensions = ProjectExtensions.model_validate(data)
        assert extensions.openssf_baseline is not None
        assert extensions.openssf_baseline.metadata.author == "OpenSSF"

    def test_cncf_project_config(self) -> None:
        """Test full CNCFProjectConfig."""
        config = CNCFProjectConfig(
            schema_version="1.1.0",
            name="test-project",
            extensions=ProjectExtensions(
                openssf_baseline=BaselineExtension(
                    metadata=ExtensionMetadata(author="OpenSSF"),
                    config=BaselineExtensionConfig(),
                )
            ),
        )
        assert config.schema_version == "1.1.0"
        assert config.name == "test-project"
        assert config.extensions.openssf_baseline is not None

    def test_cncf_config_from_yaml_dict(self) -> None:
        """Test loading CNCF config from YAML-style dict."""
        data = {
            "schema_version": "1.1.0",
            "name": "my-project",
            "extensions": {
                "openssf-baseline": {
                    "metadata": {
                        "author": "OpenSSF",
                        "homepage": "https://baseline.openssf.org",
                    },
                    "config": {
                        "context": {
                            "governance": {
                                "maintainers": {
                                    "source": "user_confirmed",
                                    "value": ["@user1"],
                                    "confidence": 1.0,
                                }
                            }
                        }
                    },
                }
            },
        }
        config = CNCFProjectConfig.model_validate(data)
        assert config.extensions.openssf_baseline.metadata.author == "OpenSSF"
