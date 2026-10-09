"""One module-path resolution policy for every ``module:attribute`` import (#490)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from darnit.core import discovery
from darnit.core.handlers import HandlerImportRefused, HandlerRegistry, resolve_module_path

REPO_ROOT = Path(__file__).resolve().parents[3]
CORE_SRC = REPO_ROOT / "packages" / "darnit" / "src" / "darnit"


@pytest.fixture(autouse=True)
def fresh_discovery():
    discovery.clear_cache()
    yield
    discovery.clear_cache()


class TestAccepted:
    @pytest.mark.parametrize(
        "path",
        [
            "darnit.core.logging:get_logger",
            "darnit_baseline.tools:audit_openssf_baseline",
            "darnit_csl.mcp_tools:remediate_community_spec",
            "darnit_gittuf.implementation:GittufImplementation",
            "darnit_reproducibility.implementation:ReproducibilityImplementation",
            "darnit_hello.implementation:HelloImplementation",
        ],
    )
    def test_core_and_installed_implementation_modules_resolve(self, path: str) -> None:
        assert callable(resolve_module_path(path))

    def test_allowed_set_comes_from_implementation_entry_points(self) -> None:
        packages = discovery.implementation_packages()

        assert {"darnit_baseline", "darnit_csl", "darnit_gittuf", "darnit_reproducibility", "darnit_hello"} <= packages
        assert "yaml" not in packages

    def test_allowed_set_is_recomputed_after_discovery_reset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import importlib.metadata

        assert callable(resolve_module_path("darnit_csl.mcp_tools:remediate_community_spec"))

        discovery.clear_cache()
        monkeypatch.setattr(importlib.metadata, "entry_points", lambda **_: [])
        with pytest.raises(HandlerImportRefused):
            resolve_module_path("darnit_csl.mcp_tools:remediate_community_spec")
        assert callable(resolve_module_path("darnit.core.logging:get_logger"))

        monkeypatch.undo()
        discovery.clear_cache()
        assert callable(resolve_module_path("darnit_csl.mcp_tools:remediate_community_spec"))


class TestRefused:
    @pytest.mark.parametrize(
        "path",
        [
            "os:system",
            "subprocess:run",
            "builtins:eval",
            "os.path:exists",
            "darnit_not_installed_xyz.tools:run",
            "darnitx.core:thing",
            "yaml:safe_load",
        ],
    )
    def test_module_outside_policy_is_refused(self, path: str) -> None:
        with pytest.raises(HandlerImportRefused) as exc:
            resolve_module_path(path)
        assert isinstance(exc.value, ValueError)
        assert path in str(exc.value)
        assert "darnit_csl" in str(exc.value)

    @pytest.mark.parametrize(
        "path",
        [
            "invalid",
            ":get_logger",
            "darnit.core.logging:",
            ".darnit.core.logging:get_logger",
            "darnit..core.logging:get_logger",
            "darnit.core.logging.:get_logger",
            "darnit.core:logging:get_logger",
            "darnit.core.logging:get_logger.__globals__",
            "darnit/core/logging:get_logger",
        ],
    )
    def test_malformed_path_is_refused(self, path: str) -> None:
        with pytest.raises(HandlerImportRefused, match=re.escape(path)):
            resolve_module_path(path)

    def test_refusal_is_logged_at_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="darnit.core.handlers"):
            with pytest.raises(HandlerImportRefused):
                resolve_module_path("os:system")
        assert any(r.levelno == logging.WARNING and "os:system" in r.getMessage() for r in caplog.records)

    def test_refused_module_is_never_imported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import importlib

        imported: list[str] = []
        real = importlib.import_module
        monkeypatch.setattr(importlib, "import_module", lambda name, *a: imported.append(name) or real(name, *a))

        with pytest.raises(HandlerImportRefused):
            resolve_module_path("darnit_not_installed_xyz.tools:run")
        assert imported == []


class TestNotFound:
    def test_allowed_module_that_does_not_exist_raises_import_error(self) -> None:
        with pytest.raises(ImportError):
            resolve_module_path("darnit.nonexistent_module_xyz:func")

    def test_allowed_module_without_the_attribute_raises_attribute_error(self) -> None:
        with pytest.raises(AttributeError):
            resolve_module_path("darnit.core.logging:nonexistent_function_xyz")


class TestOnePolicy:
    def test_no_prefix_allowlist_remains(self) -> None:
        from darnit.core.registry import PluginRegistry
        from darnit.server.registry import ToolRegistry

        for owner in (HandlerRegistry, PluginRegistry, ToolRegistry):
            assert not hasattr(owner, "ALLOWED_MODULE_PREFIXES")
        offenders = [p for p in CORE_SRC.rglob("*.py") if "ALLOWED_MODULE_PREFIXES" in p.read_text(encoding="utf-8")]
        assert offenders == []

    def test_core_imports_by_name_in_one_place(self) -> None:
        sites = [
            p.relative_to(CORE_SRC).as_posix()
            for p in CORE_SRC.rglob("*.py")
            if "import_module(" in p.read_text(encoding="utf-8")
        ]
        assert sites == ["core/handlers.py"]
