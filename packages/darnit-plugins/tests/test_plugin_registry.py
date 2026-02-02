"""Tests for the PluginRegistry."""

from pathlib import Path

from darnit.core.adapters import CheckAdapter
from darnit.core.models import AdapterCapability, CheckResult, CheckStatus
from darnit.core.registry import (
    AdapterInfo,
    FrameworkInfo,
    PluginRegistry,
    get_plugin_registry,
    reset_plugin_registry,
)


class MockCheckAdapter(CheckAdapter):
    """Mock adapter for testing."""

    def name(self) -> str:
        return "mock"

    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            control_ids={"MOCK-01", "MOCK-02"},
            supports_batch=True,
        )

    def check(self, control_id, owner, repo, local_path, config) -> CheckResult:
        return CheckResult(
            control_id=control_id,
            status=CheckStatus.PASS,
            message="Mock check passed",
            level=1,
            source="mock",
        )


class TestPluginRegistryBasics:
    """Basic registry functionality tests."""

    def setup_method(self):
        """Reset registry before each test."""
        reset_plugin_registry()

    def test_global_registry_singleton(self):
        """Should return the same instance."""
        reg1 = get_plugin_registry()
        reg2 = get_plugin_registry()
        assert reg1 is reg2

    def test_reset_registry(self):
        """Should create new instance after reset."""
        reg1 = get_plugin_registry()
        reset_plugin_registry()
        reg2 = get_plugin_registry()
        assert reg1 is not reg2

    def test_clear_cache(self):
        """Should clear all caches."""
        registry = PluginRegistry()
        registry.register_check_adapter("test", MockCheckAdapter)

        assert "test" in registry.list_check_adapters()

        registry.clear_cache()

        # After clear, manually registered adapters are gone
        assert "test" not in registry._check_adapters


class TestFrameworkRegistration:
    """Tests for framework registration and discovery."""

    def setup_method(self):
        reset_plugin_registry()

    def test_register_framework(self):
        """Should register a framework."""
        registry = PluginRegistry()
        registry.register_framework(
            "test-framework",
            lambda: Path("/path/to/test.toml"),
        )

        assert "test-framework" in registry.list_frameworks()

    def test_get_framework_path(self):
        """Should return framework path."""
        registry = PluginRegistry()
        registry.register_framework(
            "test-framework",
            lambda: Path("/path/to/test.toml"),
        )

        path = registry.get_framework_path("test-framework")
        assert path == Path("/path/to/test.toml")

    def test_get_framework_path_not_found(self):
        """Should return None for unknown framework."""
        registry = PluginRegistry()
        path = registry.get_framework_path("nonexistent")
        assert path is None

    def test_has_framework(self):
        """Should check framework existence."""
        registry = PluginRegistry()
        registry.register_framework("exists", lambda: Path("/test.toml"))

        assert registry.has_framework("exists")
        assert not registry.has_framework("missing")

    def test_get_framework_info(self):
        """Should return FrameworkInfo."""
        registry = PluginRegistry()
        registry.register_framework(
            "test",
            lambda: Path("/test.toml"),
            package="test-package",
        )

        info = registry.get_framework_info("test")
        assert info is not None
        assert info.name == "test"
        assert info.package == "test-package"


class TestCheckAdapterRegistration:
    """Tests for check adapter registration and discovery."""

    def setup_method(self):
        reset_plugin_registry()

    def test_register_adapter_class(self):
        """Should register an adapter class."""
        registry = PluginRegistry()
        registry.register_check_adapter("mock", MockCheckAdapter)

        assert "mock" in registry.list_check_adapters()

    def test_register_adapter_instance(self):
        """Should register an adapter instance."""
        registry = PluginRegistry()
        instance = MockCheckAdapter()
        registry.register_check_adapter("mock", instance)

        adapter = registry.get_check_adapter("mock")
        assert adapter is instance

    def test_get_check_adapter(self):
        """Should return adapter instance."""
        registry = PluginRegistry()
        registry.register_check_adapter("mock", MockCheckAdapter)

        adapter = registry.get_check_adapter("mock")
        assert adapter is not None
        assert adapter.name() == "mock"

    def test_get_check_adapter_cached(self):
        """Should cache adapter instances."""
        registry = PluginRegistry()
        registry.register_check_adapter("mock", MockCheckAdapter)

        adapter1 = registry.get_check_adapter("mock")
        adapter2 = registry.get_check_adapter("mock")
        assert adapter1 is adapter2

    def test_get_check_adapter_not_found(self):
        """Should return None for unknown adapter."""
        registry = PluginRegistry()
        adapter = registry.get_check_adapter("nonexistent")
        assert adapter is None

    def test_has_check_adapter(self):
        """Should check adapter existence."""
        registry = PluginRegistry()
        registry.register_check_adapter("mock", MockCheckAdapter)

        assert registry.has_check_adapter("mock")
        assert not registry.has_check_adapter("missing")

    def test_get_check_adapter_info(self):
        """Should return AdapterInfo."""
        registry = PluginRegistry()
        registry.register_check_adapter("mock", MockCheckAdapter, package="test-pkg")

        info = registry.get_check_adapter_info("mock")
        assert info is not None
        assert info.name == "mock"
        assert info.package == "test-pkg"
        assert info.adapter_type == "check"


class TestConfigBasedRegistration:
    """Tests for config-based adapter registration."""

    def setup_method(self):
        reset_plugin_registry()

    def test_register_command_adapter(self):
        """Should register a command adapter from config."""
        registry = PluginRegistry()
        adapter = registry.register_from_adapter_config("test-cmd", {
            "type": "command",
            "command": "echo",
            "output_format": "json",
        })

        assert adapter is not None
        assert adapter.name() == "test-cmd"

    def test_register_script_adapter(self):
        """Should register a script adapter from config."""
        registry = PluginRegistry()
        adapter = registry.register_from_adapter_config("test-script", {
            "type": "script",
            "command": "/bin/true",
        })

        assert adapter is not None
        assert adapter.name() == "test-script"

    def test_register_unknown_type(self):
        """Should return None for unknown adapter type."""
        registry = PluginRegistry()
        adapter = registry.register_from_adapter_config("test", {
            "type": "unknown",
        })

        assert adapter is None


class TestPluginSummary:
    """Tests for plugin summary."""

    def setup_method(self):
        reset_plugin_registry()

    def test_get_plugin_summary(self):
        """Should return plugin summary."""
        registry = PluginRegistry()
        registry.register_framework("fw1", lambda: Path("/fw1.toml"))
        registry.register_check_adapter("adapter1", MockCheckAdapter)

        summary = registry.get_plugin_summary()

        assert "frameworks" in summary
        assert "check_adapters" in summary
        assert "remediation_adapters" in summary
        assert "counts" in summary

        assert "fw1" in summary["frameworks"]
        assert "adapter1" in summary["check_adapters"]


class TestAdapterInfo:
    """Tests for AdapterInfo class."""

    def test_get_instance_lazy(self):
        """Should lazily instantiate adapter."""
        info = AdapterInfo(
            name="test",
            package="test-pkg",
            entry_point_name="test",
            adapter_class=MockCheckAdapter,
            adapter_type="check",
        )

        # Not instantiated yet
        assert info._instance is None

        # Get instance
        instance = info.get_instance()
        assert instance is not None
        assert isinstance(instance, MockCheckAdapter)

        # Cached
        assert info._instance is instance
        assert info.get_instance() is instance

    def test_capabilities_property(self):
        """Should get capabilities via property."""
        info = AdapterInfo(
            name="test",
            package="test-pkg",
            entry_point_name="test",
            adapter_class=MockCheckAdapter,
            adapter_type="check",
        )

        caps = info.capabilities
        assert caps is not None
        assert "MOCK-01" in caps.control_ids


class TestFrameworkInfo:
    """Tests for FrameworkInfo class."""

    def test_path_lazy(self):
        """Should lazily resolve path."""
        call_count = [0]

        def get_path():
            call_count[0] += 1
            return Path("/test.toml")

        info = FrameworkInfo(
            name="test",
            package="test-pkg",
            entry_point_name="test",
            path_func=get_path,
        )

        # Not resolved yet
        assert info._path is None
        assert call_count[0] == 0

        # Get path
        path = info.path
        assert path == Path("/test.toml")
        assert call_count[0] == 1

        # Cached
        assert info.path == Path("/test.toml")
        assert call_count[0] == 1  # Not called again
