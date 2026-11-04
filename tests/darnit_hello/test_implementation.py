"""Tests for darnit-hello reference plugin."""

from __future__ import annotations

from typing import Any

import pytest
from darnit_hello import HelloImplementation, get_framework_path, register

from darnit.core.plugin import ComplianceImplementation


def _framework_controls(impl: HelloImplementation) -> list[Any]:
    from darnit.config import load_controls_from_framework
    from darnit.config.merger import load_framework_config

    config_path = impl.get_framework_config_path()
    assert config_path is not None
    return load_controls_from_framework(load_framework_config(config_path))


class TestHelloImplementation:
    @pytest.fixture
    def impl(self) -> HelloImplementation:
        return HelloImplementation()

    @pytest.mark.unit
    def test_properties(self, impl: HelloImplementation) -> None:
        assert impl.name == "hello"
        assert impl.display_name == "Hello — Minimal Darnit Plugin"
        assert impl.version == "0.1.0"
        assert impl.spec_version == "hello v0.1"

    @pytest.mark.unit
    def test_is_compliance_implementation(self, impl: HelloImplementation) -> None:
        assert isinstance(impl, ComplianceImplementation)

    @pytest.mark.unit
    def test_get_framework_config_path(self, impl: HelloImplementation) -> None:
        path = impl.get_framework_config_path()
        assert path is not None
        assert path.is_file()
        assert path.name == "hello.toml"
        assert path.parent.name == "darnit_hello"

    @pytest.mark.unit
    def test_register_handlers_is_noop(self, impl: HelloImplementation) -> None:
        assert impl.register_handlers() is None

    @pytest.mark.unit
    def test_framework_toml_controls(self, impl: HelloImplementation) -> None:
        controls = _framework_controls(impl)
        assert len(controls) == 1
        control = controls[0]
        assert control.control_id == "HELLO-01.01"
        assert control.name == "ReadmeExists"
        assert control.level == 1
        assert control.domain == "HELLO"


class TestHelloDiscoveryEntryPoints:
    @pytest.mark.unit
    def test_register_returns_instance(self) -> None:
        instance = register()
        assert isinstance(instance, HelloImplementation)
        assert instance.name == "hello"

    @pytest.mark.unit
    def test_get_framework_path_returns_existing_file(self) -> None:
        path = get_framework_path()
        assert path.is_file()
        assert path.name == "hello.toml"
        assert path.parent.name == "darnit_hello"
