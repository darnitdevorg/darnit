"""Tests for darnit_example implementation."""

import pytest

from darnit.core.plugin import ComplianceImplementation
from darnit_example import register
from darnit_example.implementation import ExampleHygieneImplementation


class TestExampleHygieneImplementation:
    """Tests for ExampleHygieneImplementation class."""

    @pytest.fixture
    def impl(self):
        return ExampleHygieneImplementation()

    @pytest.mark.unit
    def test_properties(self, impl):
        assert impl.name == "example-hygiene"
        assert impl.display_name == "Project Hygiene Standard (Example)"
        assert impl.version == "0.1.0"
        assert impl.spec_version == "PH v1.0"

    @pytest.mark.unit
    def test_is_compliance_implementation(self, impl):
        assert isinstance(impl, ComplianceImplementation)

    @pytest.mark.unit
    def test_get_all_controls(self, impl):
        controls = impl.get_all_controls()
        assert len(controls) == 8
        levels = {c.level for c in controls}
        assert levels == {1, 2}

    @pytest.mark.unit
    def test_get_controls_by_level(self, impl):
        level1 = impl.get_controls_by_level(1)
        level2 = impl.get_controls_by_level(2)

        assert len(level1) == 6
        assert len(level2) == 2

        assert all(c.level == 1 for c in level1)
        assert all(c.level == 2 for c in level2)

        assert len(level1) + len(level2) == len(impl.get_all_controls())

    @pytest.mark.unit
    def test_control_ids_are_ph_format(self, impl):
        controls = impl.get_all_controls()
        for control in controls:
            assert control.control_id.startswith("PH-")
            parts = control.control_id.split("-")
            assert len(parts) >= 3

    @pytest.mark.unit
    def test_control_domains(self, impl):
        controls = impl.get_all_controls()
        valid_domains = {"DOC", "SEC", "CFG", "QA", "CI"}
        for control in controls:
            assert control.domain in valid_domains, f"Invalid domain: {control.domain}"

    @pytest.mark.unit
    def test_get_rules_catalog(self, impl):
        catalog = impl.get_rules_catalog()
        assert isinstance(catalog, dict)
        assert len(catalog) == 8

    @pytest.mark.unit
    def test_get_remediation_registry(self, impl):
        registry = impl.get_remediation_registry()
        assert isinstance(registry, dict)
        assert len(registry) > 0

    @pytest.mark.unit
    def test_get_framework_config_path(self, impl):
        path = impl.get_framework_config_path()
        assert path is not None
        assert path.name == "example-hygiene.toml"
        assert path.exists()


class TestHandlerRegistration:
    """Tests for handler registration."""

    @pytest.fixture(autouse=True)
    def clear_registry(self):
        from darnit.core.handlers import get_handler_registry

        registry = get_handler_registry()
        registry.clear()
        yield
        registry.clear()

    @pytest.mark.unit
    def test_register_handlers_adds_tools(self):
        from darnit.core.handlers import get_handler_registry

        impl = ExampleHygieneImplementation()
        impl.register_handlers()

        registry = get_handler_registry()
        handlers = registry.list_handlers()

        assert len(handlers) > 0
        handler_names = {h.name for h in handlers}
        assert "example_hygiene_check" in handler_names

    @pytest.mark.unit
    def test_handlers_have_plugin_context(self):
        from darnit.core.handlers import get_handler_registry

        impl = ExampleHygieneImplementation()
        impl.register_handlers()

        registry = get_handler_registry()
        handler_info = registry.get_handler_info("example_hygiene_check")

        assert handler_info is not None
        assert handler_info.plugin == "example-hygiene"

class TestRegisterFunction:
    """Tests for the register() entry point function."""

    @pytest.mark.unit
    def test_register_returns_implementation(self):
        impl = register()
        assert isinstance(impl, ExampleHygieneImplementation)

