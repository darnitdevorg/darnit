"""Tests for darnit.core.plugin module."""

from pathlib import Path
from typing import Any

import pytest

from darnit.core.plugin import (
    ComplianceImplementation,
    ControlSpec,
)


class TestControlSpec:
    """Tests for ControlSpec dataclass."""

    @pytest.mark.unit
    def test_basic_creation(self):
        """Test basic ControlSpec creation."""
        spec = ControlSpec(
            control_id="OSPS-AC-01.01",
            name="Access Control",
            description="Verify access control policies",
            level=1,
            domain="AC",
            metadata={}
        )
        assert spec.control_id == "OSPS-AC-01.01"
        assert spec.name == "Access Control"
        assert spec.level == 1
        assert spec.domain == "AC"

    @pytest.mark.unit
    def test_with_metadata(self):
        """Test ControlSpec with metadata."""
        spec = ControlSpec(
            control_id="OSPS-VM-02.01",
            name="Security Policy",
            description="Security reporting policy",
            level=1,
            domain="VM",
            metadata={
                "help_uri": "https://baseline.openssf.org",
                "remediation": "Create SECURITY.md"
            }
        )
        assert spec.metadata["help_uri"] == "https://baseline.openssf.org"
        assert "remediation" in spec.metadata


class MockImplementation:
    """Mock compliance implementation for testing."""

    @property
    def name(self) -> str:
        return "mock-baseline"

    @property
    def display_name(self) -> str:
        return "Mock Baseline"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def spec_version(self) -> str:
        return "Mock v1.0"

    def get_all_controls(self) -> list[ControlSpec]:
        return [
            ControlSpec(
                control_id="MOCK-01",
                name="Mock Control 1",
                description="First mock control",
                level=1,
                domain="MOCK",
                metadata={}
            ),
            ControlSpec(
                control_id="MOCK-02",
                name="Mock Control 2",
                description="Second mock control",
                level=2,
                domain="MOCK",
                metadata={}
            ),
        ]

    def get_controls_by_level(self, level: int) -> list[ControlSpec]:
        return [c for c in self.get_all_controls() if c.level == level]

    def get_check_functions(self) -> dict[str, Any]:
        return {"level1": lambda: [], "level2": lambda: []}

    def get_rules_catalog(self) -> dict[str, Any]:
        return {"MOCK-01": {"name": "Mock Control 1"}}

    def get_remediation_registry(self) -> dict[str, Any]:
        return {}

    def get_framework_config_path(self) -> Path | None:
        return None

    def register_controls(self) -> None:
        pass


class TestComplianceImplementation:
    """Tests for ComplianceImplementation protocol."""

    @pytest.mark.unit
    def test_mock_implementation_is_protocol(self):
        """Test that MockImplementation satisfies the protocol."""
        impl = MockImplementation()
        # Check it's recognized as implementing the protocol
        assert isinstance(impl, ComplianceImplementation)

    @pytest.mark.unit
    def test_implementation_properties(self):
        """Test implementation property access."""
        impl = MockImplementation()
        assert impl.name == "mock-baseline"
        assert impl.display_name == "Mock Baseline"
        assert impl.version == "1.0.0"
        assert impl.spec_version == "Mock v1.0"

    @pytest.mark.unit
    def test_get_all_controls(self):
        """Test get_all_controls method."""
        impl = MockImplementation()
        controls = impl.get_all_controls()
        assert len(controls) == 2
        assert controls[0].control_id == "MOCK-01"
        assert controls[1].control_id == "MOCK-02"

    @pytest.mark.unit
    def test_get_controls_by_level(self):
        """Test get_controls_by_level method."""
        impl = MockImplementation()
        level1 = impl.get_controls_by_level(1)
        level2 = impl.get_controls_by_level(2)
        assert len(level1) == 1
        assert level1[0].control_id == "MOCK-01"
        assert len(level2) == 1
        assert level2[0].control_id == "MOCK-02"

    @pytest.mark.unit
    def test_get_check_functions(self):
        """Test get_check_functions method."""
        impl = MockImplementation()
        funcs = impl.get_check_functions()
        assert "level1" in funcs
        assert "level2" in funcs
        assert callable(funcs["level1"])

    @pytest.mark.unit
    def test_get_rules_catalog(self):
        """Test get_rules_catalog method."""
        impl = MockImplementation()
        catalog = impl.get_rules_catalog()
        assert "MOCK-01" in catalog

    @pytest.mark.unit
    def test_get_remediation_registry(self):
        """Test get_remediation_registry method."""
        impl = MockImplementation()
        registry = impl.get_remediation_registry()
        assert isinstance(registry, dict)
