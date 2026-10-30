"""Tests for handler registration system."""

import re

import pytest

from darnit.core.handlers import (
    HandlerImportRefused,
    HandlerRegistry,
    get_handler,
    get_handler_registry,
    register_handler,
)


class TestHandlerRegistry:
    """Tests for HandlerRegistry class."""

    def test_register_handler(self) -> None:
        """Test registering a handler function."""
        registry = HandlerRegistry()

        def my_handler(owner: str, repo: str) -> dict:
            return {"status": "pass"}

        registry.register_handler("my_handler", my_handler)

        assert registry.get_handler("my_handler") is my_handler
        info = registry.get_handler_info("my_handler")
        assert info is not None
        assert info.name == "my_handler"
        assert info.func is my_handler

    def test_register_handler_with_plugin_context(self) -> None:
        """Test handler registration with plugin context."""
        registry = HandlerRegistry()
        registry.set_plugin_context("my-plugin")

        def handler_func():
            pass

        registry.register_handler("handler", handler_func)

        info = registry.get_handler_info("handler")
        assert info is not None
        assert info.plugin == "my-plugin"

    def test_get_handler_not_found(self) -> None:
        """Test getting a non-existent handler returns None."""
        registry = HandlerRegistry()
        assert registry.get_handler("nonexistent") is None

    def test_handlers_record_their_plugin(self) -> None:
        """Each handler records the plugin context it was registered under."""
        registry = HandlerRegistry()

        def handler1():
            pass

        def handler2():
            pass

        registry.set_plugin_context("plugin-a")
        registry.register_handler("handler1", handler1)
        registry.set_plugin_context("plugin-b")
        registry.register_handler("handler2", handler2)

        assert registry.get_handler_info("handler1").plugin == "plugin-a"
        assert registry.get_handler_info("handler2").plugin == "plugin-b"

    def test_handler_override_warning(self) -> None:
        """Test that overriding a handler logs a warning."""
        registry = HandlerRegistry()

        def handler_v1():
            return "v1"

        def handler_v2():
            return "v2"

        registry.set_plugin_context("plugin-a")
        registry.register_handler("handler", handler_v1)
        registry.set_plugin_context("plugin-b")
        registry.register_handler("handler", handler_v2)

        # Should have the new handler
        assert registry.get_handler("handler") is handler_v2

    def test_load_handler_from_module_path(self) -> None:
        """Test loading handler from allowed module:function path."""
        registry = HandlerRegistry()

        # Use a known function from the darnit package (allowed prefix)
        handler = registry._load_handler_from_path("darnit.core.logging:get_logger")
        assert handler is not None
        assert callable(handler)

    def test_load_handler_refused_module_path(self) -> None:
        """A module outside the resolution policy is refused, not "not found"."""
        registry = HandlerRegistry()

        for path in ("os.path:exists", "subprocess:run", "invalid"):
            with pytest.raises(HandlerImportRefused, match=re.escape(path)):
                registry._load_handler_from_path(path)

    def test_load_handler_missing_module_returns_none(self) -> None:
        registry = HandlerRegistry()
        assert registry._load_handler_from_path("darnit.nonexistent.module:func") is None


class TestDecorators:
    """Tests for the @register_handler decorator."""

    def test_register_handler_decorator(self) -> None:
        """Test @register_handler decorator."""
        # Clear the global registry first
        global_registry = get_handler_registry()
        global_registry.clear()

        @register_handler("decorated_handler")
        def my_decorated_handler():
            return "result"

        handler = get_handler("decorated_handler")
        assert handler is my_decorated_handler
        assert handler() == "result"

    def test_register_handler_decorator_no_args(self) -> None:
        """Test @register_handler without arguments uses function name."""
        global_registry = get_handler_registry()
        global_registry.clear()

        @register_handler
        def another_handler():
            return "another"

        handler = get_handler("another_handler")
        assert handler is another_handler

class TestRegistryClear:
    """Tests for registry clear functionality."""

    def test_clear(self) -> None:
        """Test clearing the registry."""
        registry = HandlerRegistry()

        def handler():
            pass

        registry.register_handler("h", handler)
        registry.set_plugin_context("plugin")

        registry.clear()

        assert registry.get_handler("h") is None
        assert registry._current_plugin is None


class TestDarnitBaselineIntegration:
    """Integration tests with darnit-baseline plugin."""

    def test_resolve_baseline_handler_by_module_path(self) -> None:
        """Test resolving darnit-baseline handler via module:function path."""
        registry = HandlerRegistry()

        # Should resolve darnit_baseline module path
        handler = registry.get_handler(
            "darnit_baseline.tools:audit_openssf_baseline"
        )
        assert handler is not None
        assert callable(handler)

    def test_resolve_refused_module_path(self) -> None:
        """Arbitrary modules are refused with an error naming the path."""
        registry = HandlerRegistry()

        for path in ("os:system", "subprocess:run"):
            with pytest.raises(HandlerImportRefused, match=re.escape(path)):
                registry.get_handler(path)

    def test_resolve_other_installed_implementation_modules(self) -> None:
        """Every installed implementation's package resolves, not only a fixed few."""
        registry = HandlerRegistry()

        for path in (
            "darnit_gittuf.implementation:GittufImplementation",
            "darnit_amber.implementation:AmberImplementation",
            "darnit_hello.implementation:HelloImplementation",
            "darnit_csl.mcp_tools:remediate_community_spec",
        ):
            assert callable(registry.get_handler(path))

    def test_get_handler_with_colon_tries_module_resolution(self) -> None:
        """Test that handler names with ':' trigger module resolution."""
        registry = HandlerRegistry()

        # Valid darnit_baseline path should resolve
        handler = registry.get_handler(
            "darnit_baseline.tools:list_available_checks"
        )
        assert callable(handler)

        # Invalid path (bad function name) should return None gracefully
        handler = registry.get_handler(
            "darnit_baseline.tools:nonexistent_function"
        )
        assert handler is None
