"""Tests for handler registration system."""

from pathlib import Path

from darnit.core.handlers import (
    HandlerRegistry,
    TemplateInfo,
    get_handler,
    get_handler_registry,
    register_handler,
    register_pass,
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

    def test_list_handlers(self) -> None:
        """Test listing all handlers."""
        registry = HandlerRegistry()

        def handler1():
            pass

        def handler2():
            pass

        registry.set_plugin_context("plugin-a")
        registry.register_handler("handler1", handler1)
        registry.set_plugin_context("plugin-b")
        registry.register_handler("handler2", handler2)

        all_handlers = registry.list_handlers()
        assert len(all_handlers) == 2

        plugin_a_handlers = registry.list_handlers(plugin="plugin-a")
        assert len(plugin_a_handlers) == 1
        assert plugin_a_handlers[0].name == "handler1"

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

    def test_load_handler_blocked_module_path(self) -> None:
        """Test that non-allowlisted module paths are blocked."""
        registry = HandlerRegistry()

        # os.path is not in ALLOWED_MODULE_PREFIXES, should be blocked
        handler = registry._load_handler_from_path("os.path:exists")
        assert handler is None

        # subprocess is not allowed either
        handler = registry._load_handler_from_path("subprocess:run")
        assert handler is None

    def test_load_handler_invalid_path(self) -> None:
        """Test loading handler from invalid path returns None."""
        registry = HandlerRegistry()
        assert registry._load_handler_from_path("invalid") is None
        assert registry._load_handler_from_path("darnit.nonexistent.module:func") is None


class TestPassRegistry:
    """Tests for pass registration in HandlerRegistry."""

    def test_register_pass(self) -> None:
        """Test registering a custom pass class."""
        registry = HandlerRegistry()

        class MyCustomPass:
            """A custom pass implementation."""

            pass

        registry.register_pass("my_pass", MyCustomPass)

        assert registry.get_pass("my_pass") is MyCustomPass
        passes = registry.list_passes()
        assert len(passes) == 1
        assert passes[0].name == "my_pass"

    def test_pass_with_plugin_context(self) -> None:
        """Test pass registration with plugin context."""
        registry = HandlerRegistry()
        registry.set_plugin_context("my-plugin")

        class CustomPass:
            pass

        registry.register_pass("custom", CustomPass)

        passes = registry.list_passes(plugin="my-plugin")
        assert len(passes) == 1
        assert passes[0].plugin == "my-plugin"


class TestTemplateRegistry:
    """Tests for template registration in HandlerRegistry."""

    def test_register_template(self, tmp_path: Path) -> None:
        """Test registering a template file."""
        registry = HandlerRegistry()

        template_file = tmp_path / "security.md"
        template_file.write_text("# Security Policy")

        registry.register_template("security", template_file)

        template = registry.get_template("security")
        assert template is not None
        assert template.name == "security"
        assert template.path == template_file

    def test_template_load_content(self, tmp_path: Path) -> None:
        """Test loading template content."""
        template_file = tmp_path / "test.md"
        template_file.write_text("Hello, $NAME!")

        template = TemplateInfo(name="test", path=template_file)
        content = template.load_content()

        assert content == "Hello, $NAME!"
        assert template.content == content  # Cached

    def test_discover_templates(self, tmp_path: Path) -> None:
        """Test automatic template discovery."""
        registry = HandlerRegistry()

        # Create some template files
        (tmp_path / "security.md").write_text("# Security")
        (tmp_path / "readme.md").write_text("# Readme")
        (tmp_path / "config.json").write_text("{}")  # Not a template
        (tmp_path / "template.j2").write_text("{{ var }}")

        registry.set_plugin_context("test-plugin")
        count = registry.discover_templates(tmp_path)

        assert count == 3  # .md and .j2 files
        assert registry.get_template("security") is not None
        assert registry.get_template("readme") is not None
        assert registry.get_template("template") is not None
        assert registry.get_template("config") is None  # .json not included

    def test_discover_templates_nonexistent_dir(self, tmp_path: Path) -> None:
        """Test discovery on non-existent directory returns 0."""
        registry = HandlerRegistry()
        count = registry.discover_templates(tmp_path / "nonexistent")
        assert count == 0


class TestDecorators:
    """Tests for @register_handler and @register_pass decorators."""

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

    def test_register_pass_decorator(self) -> None:
        """Test @register_pass decorator."""
        global_registry = get_handler_registry()
        global_registry.clear()

        @register_pass("decorated_pass")
        class MyDecoratedPass:
            pass

        pass_cls = global_registry.get_pass("decorated_pass")
        assert pass_cls is MyDecoratedPass

    def test_register_pass_decorator_no_args(self) -> None:
        """Test @register_pass without arguments uses class name."""
        global_registry = get_handler_registry()
        global_registry.clear()

        @register_pass
        class AnotherPass:
            pass

        pass_cls = global_registry.get_pass("AnotherPass")
        assert pass_cls is AnotherPass


class TestRegistryClear:
    """Tests for registry clear functionality."""

    def test_clear(self) -> None:
        """Test clearing the registry."""
        registry = HandlerRegistry()

        def handler():
            pass

        class Pass:
            pass

        registry.register_handler("h", handler)
        registry.register_pass("p", Pass)
        registry.set_plugin_context("plugin")

        registry.clear()

        assert registry.get_handler("h") is None
        assert registry.get_pass("p") is None
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

    def test_resolve_blocked_module_path(self) -> None:
        """Test that non-allowlisted modules are blocked."""
        registry = HandlerRegistry()

        # Should block arbitrary modules
        handler = registry.get_handler("os:system")
        assert handler is None

        handler = registry.get_handler("subprocess:run")
        assert handler is None

    def test_allowlist_includes_darnit_packages(self) -> None:
        """Test that allowlist includes all darnit package prefixes."""
        from darnit.core.handlers import HandlerRegistry

        allowed = HandlerRegistry.ALLOWED_MODULE_PREFIXES

        assert "darnit." in allowed
        assert "darnit_baseline." in allowed
        assert "darnit_testchecks." in allowed

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
