"""Tests for darnit.core.plugin module."""

from pathlib import Path

import pytest

from darnit.core.plugin import ComplianceImplementation, ControlSpec


class FullyCompliantImplementation:
    """Minimal implementation satisfying the compliance protocol."""

    name = "test-framework"
    display_name = "Test Framework"
    version = "0.1.0"
    spec_version = "TEST v1"

    def get_framework_config_path(self) -> Path | None:
        return Path("/tmp/framework.toml")


class LegacyMethodsImplementation(FullyCompliantImplementation):
    """A plugin written before #487 that still defines the removed methods."""

    name = "legacy-framework"

    def get_all_controls(self) -> list[ControlSpec]:
        return []

    def get_controls_by_level(self, level: int) -> list[ControlSpec]:
        return []

    def get_rules_catalog(self) -> dict[str, str]:
        return {}

    def get_remediation_registry(self) -> dict[str, str]:
        return {}

    def register_controls(self) -> None:
        return None


class MissingConfigPathImplementation:
    """Deliberately incomplete implementation for protocol checks."""

    name = "broken-framework"
    display_name = "Broken Framework"
    version = "0.1.0"
    spec_version = "TEST v1"


class TestControlSpec:
    """Tests for ControlSpec dataclass behavior."""

    @pytest.mark.unit
    def test_construction_stores_all_fields(self):
        """ControlSpec stores provided values and copies level/domain to tags."""
        control = ControlSpec(
            control_id="OSPS-AC-01.01",
            name="Access control policy",
            description="Ensure an access control policy exists",
            level=2,
            domain="AC",
            metadata={"severity": "medium"},
            tags={"source": "tests"},
        )

        assert control.control_id == "OSPS-AC-01.01"
        assert control.name == "Access control policy"
        assert control.description == "Ensure an access control policy exists"
        assert control.level == 2
        assert control.domain == "AC"
        assert control.metadata == {"severity": "medium"}
        assert control.tags == {"source": "tests", "level": 2, "domain": "AC"}

    @pytest.mark.unit
    def test_defaults_allow_none_level_and_domain(self):
        """ControlSpec keeps tags empty when level/domain are not provided."""
        control = ControlSpec(
            control_id="CUSTOM-01",
            name="Custom control",
            description="Framework without levels",
            level=None,
            domain=None,
            metadata={},
        )

        assert control.level is None
        assert control.domain is None
        assert control.metadata == {}
        assert control.tags == {}


class TestComplianceImplementationProtocol:
    """Tests for ComplianceImplementation runtime protocol checks."""

    @pytest.mark.unit
    def test_runtime_check_accepts_complete_implementation(self):
        """A class implementing the five required members satisfies isinstance()."""
        implementation = FullyCompliantImplementation()

        assert isinstance(implementation, ComplianceImplementation)
        assert implementation.get_framework_config_path() == Path(
            "/tmp/framework.toml"
        )

    @pytest.mark.unit
    def test_runtime_check_accepts_implementation_with_removed_methods(self):
        """Methods removed from the protocol (#487) do not affect isinstance()."""
        assert isinstance(LegacyMethodsImplementation(), ComplianceImplementation)

    @pytest.mark.unit
    def test_runtime_check_rejects_missing_required_method(self):
        """A class missing a required protocol method fails isinstance()."""
        implementation = MissingConfigPathImplementation()

        assert not isinstance(implementation, ComplianceImplementation)


class _EntryPoint:
    def __init__(self, name: str, factory: type) -> None:
        self.name = name
        self.module = f"{name.replace('-', '_')}_pkg"
        self._factory = factory

    def load(self):
        return self._factory


class TestDiscoveryOfTrimmedProtocol:
    """#487: dropping protocol members must not drop plugins out of discovery."""

    @pytest.fixture(autouse=True)
    def _fake_entry_points(self, monkeypatch: pytest.MonkeyPatch):
        import importlib.metadata

        from darnit.core.discovery import clear_cache

        eps = [
            _EntryPoint("test-framework", FullyCompliantImplementation),
            _EntryPoint("legacy-framework", LegacyMethodsImplementation),
            _EntryPoint("broken-framework", MissingConfigPathImplementation),
        ]
        monkeypatch.setattr(importlib.metadata, "entry_points", lambda **_: eps)
        clear_cache()
        yield
        clear_cache()

    @pytest.mark.unit
    def test_plugin_with_and_without_removed_methods_is_discovered(self):
        from darnit.core.discovery import discover_implementations

        found = discover_implementations()

        assert isinstance(found.get("test-framework"), FullyCompliantImplementation)
        assert isinstance(found.get("legacy-framework"), LegacyMethodsImplementation)

    @pytest.mark.unit
    def test_plugin_missing_a_required_member_is_not_discovered(self):
        from darnit.core.discovery import discover_implementations

        assert "broken-framework" not in discover_implementations()
