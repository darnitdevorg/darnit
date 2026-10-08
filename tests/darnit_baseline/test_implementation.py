"""Tests for darnit_baseline implementation."""
import importlib

import pytest

from darnit.core.plugin import ComplianceImplementation
from darnit_baseline import register
from darnit_baseline.implementation import OSPSBaselineImplementation


def _framework_controls(impl):
    """Controls as the audit loads them, from the implementation's framework TOML."""
    from darnit.config import load_controls_from_framework
    from darnit.config.merger import load_framework_config

    return load_controls_from_framework(load_framework_config(impl.get_framework_config_path()))


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
        assert impl.spec_version == "OSPS v2026.02.19"

    @pytest.mark.unit
    def test_is_compliance_implementation(self, impl):
        """Test implementation satisfies protocol."""
        assert isinstance(impl, ComplianceImplementation)

    @pytest.mark.unit
    def test_framework_toml_has_controls_at_every_level(self, impl):
        """The framework TOML defines controls at all three levels."""
        controls = _framework_controls(impl)
        assert len(controls) > 0
        levels = {c.level for c in controls}
        assert {1, 2, 3} <= levels

    @pytest.mark.unit
    def test_control_ids_are_osps_format(self, impl):
        """Test control IDs follow OSPS format.

        RFC-0001 Stage 1 (feature 025 T044) added STAGE1-REF-* controls as
        acceptance-gate reference controls. They are TAGGED and coexist
        with the OSPS-* set; the format check applies only to controls
        that are not explicitly marked as stage-reference fixtures.
        """
        controls = _framework_controls(impl)
        for control in controls:
            # Skip stage-reference controls; they use STAGE1-REF-* naming.
            tags = control.tags or {}
            if "stage1-ref" in tags:
                continue
            # Format: OSPS-XX-NN.NN
            assert control.control_id.startswith("OSPS-"), (
                f"Non-OSPS control id {control.control_id!r} not marked with stage1-ref tag"
            )
            parts = control.control_id.split("-")
            assert len(parts) >= 3  # OSPS, domain, number

    @pytest.mark.unit
    def test_control_domains(self, impl):
        """Test controls have valid domains."""
        controls = _framework_controls(impl)
        valid_domains = {"AC", "BR", "DO", "GV", "LE", "QA", "SA", "VM"}
        for control in controls:
            assert control.domain in valid_domains, f"Invalid domain: {control.domain}"


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

    @pytest.mark.skipif(
        importlib.util.find_spec("tree_sitter_language_pack") is None,
        reason="tree-sitter-language-pack not installed",
    )
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

    @pytest.mark.skipif(
        importlib.util.find_spec("tree_sitter_language_pack") is None,
        reason="tree-sitter-language-pack not installed",
    )
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

