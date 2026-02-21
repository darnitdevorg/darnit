"""Tests for darnit_baseline implementation."""

import pytest

from darnit.core.plugin import ComplianceImplementation
from darnit_baseline import register
from darnit_baseline.implementation import OSPSBaselineImplementation


class TestOSPSBaselineImplementation:
    """Tests for OSPSBaselineImplementation class."""

    @pytest.fixture
    def impl(self):
        """Create an implementation instance."""
        return OSPSBaselineImplementation()

    @pytest.mark.unit
    def test_properties(self, impl):
        """Test implementation properties."""
        assert impl.name == "openssf-baseline"
        assert impl.display_name == "OpenSSF Baseline"
        assert impl.version == "0.1.0"
        assert impl.spec_version == "OSPS v2025.10.10"

    @pytest.mark.unit
    def test_is_compliance_implementation(self, impl):
        """Test implementation satisfies protocol."""
        assert isinstance(impl, ComplianceImplementation)

    @pytest.mark.unit
    def test_get_all_controls(self, impl):
        """Test get_all_controls returns all controls."""
        controls = impl.get_all_controls()
        assert len(controls) > 0
        # Should have controls from all 3 levels
        levels = {c.level for c in controls}
        assert 1 in levels
        assert 2 in levels
        assert 3 in levels

    @pytest.mark.unit
    def test_get_controls_by_level(self, impl):
        """Test get_controls_by_level filters correctly."""
        level1 = impl.get_controls_by_level(1)
        level2 = impl.get_controls_by_level(2)
        level3 = impl.get_controls_by_level(3)

        # All should be non-empty
        assert len(level1) > 0
        assert len(level2) > 0
        assert len(level3) > 0

        # All controls should have correct level
        assert all(c.level == 1 for c in level1)
        assert all(c.level == 2 for c in level2)
        assert all(c.level == 3 for c in level3)

        # Sum should equal total
        assert len(level1) + len(level2) + len(level3) == len(impl.get_all_controls())

    @pytest.mark.unit
    def test_control_ids_are_osps_format(self, impl):
        """Test control IDs follow OSPS format."""
        controls = impl.get_all_controls()
        for control in controls:
            # Format: OSPS-XX-NN.NN
            assert control.control_id.startswith("OSPS-")
            parts = control.control_id.split("-")
            assert len(parts) >= 3  # OSPS, domain, number

    @pytest.mark.unit
    def test_control_domains(self, impl):
        """Test controls have valid domains."""
        controls = impl.get_all_controls()
        valid_domains = {"AC", "BR", "DO", "GV", "LE", "QA", "SA", "VM"}
        for control in controls:
            assert control.domain in valid_domains, f"Invalid domain: {control.domain}"

    @pytest.mark.unit
    def test_rules_catalog_has_required_fields(self, impl):
        """Test rules catalog entries have required fields."""
        catalog = impl.get_rules_catalog()
        for rule_id, rule in catalog.items():
            assert "name" in rule or "shortDescription" in rule
            assert "level" in rule

class TestHandlerRegistration:
    """Tests for auto-registration of handlers."""

    @pytest.fixture(autouse=True)
    def clear_registry(self):
        """Clear handler registry before each test."""
        from darnit.core.handlers import get_handler_registry

        registry = get_handler_registry()
        registry.clear()
        yield
        registry.clear()

    @pytest.mark.unit
    def test_register_handlers_adds_tools(self):
        """Test register_handlers adds tool handlers to registry."""
        from darnit.core.handlers import get_handler_registry

        impl = OSPSBaselineImplementation()
        impl.register_handlers()

        registry = get_handler_registry()
        handlers = registry.list_handlers()

        # Should have handlers registered
        assert len(handlers) > 0

        # Check some specific handlers exist
        handler_names = {h.name for h in handlers}
        assert "audit_openssf_baseline" in handler_names
        assert "create_security_policy" in handler_names
        assert "enable_branch_protection" in handler_names

    @pytest.mark.unit
    def test_handlers_have_plugin_context(self):
        """Test registered handlers have correct plugin context."""
        from darnit.core.handlers import get_handler_registry

        impl = OSPSBaselineImplementation()
        impl.register_handlers()

        registry = get_handler_registry()
        handler_info = registry.get_handler_info("audit_openssf_baseline")

        assert handler_info is not None
        assert handler_info.plugin == "openssf-baseline"

class TestRegisterFunction:
    """Tests for the register() entry point function."""

    @pytest.mark.unit
    def test_register_returns_implementation(self):
        """Test register() returns an OSPSBaselineImplementation."""
        impl = register()
        assert isinstance(impl, OSPSBaselineImplementation)

