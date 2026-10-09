"""Tests for the testchecks-steps implementation."""

import pytest
from darnit_testchecks import get_framework_path, get_steps_framework_path, register
from darnit_testchecks.implementation import CustomStepsImplementation

from darnit.core.plugin import ComplianceImplementation

STEP_TYPES = ("testchecks_readme_description", "testchecks_readme_quality", "testchecks_ci_config")


def _framework_controls(impl):
    """Controls as the audit loads them, from the implementation's framework TOML."""
    from darnit.config import load_controls_from_framework
    from darnit.config.merger import load_framework_config

    return load_controls_from_framework(load_framework_config(impl.get_framework_config_path()))


class TestCustomStepsImplementation:
    @pytest.fixture
    def impl(self):
        return CustomStepsImplementation()

    @pytest.mark.unit
    def test_properties(self, impl):
        assert impl.name == "testchecks-steps"
        assert impl.display_name == "Test Checks: Plugin Step Types"
        assert impl.version == "0.1.0"
        assert impl.spec_version == "test-steps-v1"

    @pytest.mark.unit
    def test_is_compliance_implementation(self, impl):
        assert isinstance(impl, ComplianceImplementation)

    @pytest.mark.unit
    def test_framework_toml_controls(self, impl):
        controls = _framework_controls(impl)
        assert sorted(c.control_id for c in controls) == ["TCS-CI-01", "TCS-DOC-01"]

    @pytest.mark.unit
    def test_framework_tomls_ship_inside_the_package(self, impl):
        """Feature 021: both framework TOMLs resolve inside src/darnit_testchecks/."""
        steps = impl.get_framework_config_path()
        assert steps == get_steps_framework_path()
        assert steps.name == "testchecks-steps.toml"
        assert get_framework_path().name == "testchecks.toml"
        for path in (steps, get_framework_path()):
            assert path.is_file()
            assert path.parent.name == "darnit_testchecks"


class TestHandlerRegistration:
    @pytest.mark.unit
    def test_register_handlers_adds_step_types_with_plugin_context(self, monkeypatch):
        import darnit.sieve.handler_registry as handler_registry
        from darnit.sieve.handler_registry import get_sieve_handler_registry

        monkeypatch.setattr(handler_registry, "_sieve_handler_registry", None)
        CustomStepsImplementation().register_handlers()

        registry = get_sieve_handler_registry()
        for name in STEP_TYPES:
            info = registry.get(name)
            assert info is not None, name
            assert info.plugin == "testchecks-steps"
            assert info.settings is not None


class TestRegisterFunction:
    @pytest.mark.unit
    def test_register_returns_implementation(self):
        assert isinstance(register(), CustomStepsImplementation)
