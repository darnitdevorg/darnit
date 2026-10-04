"""Step registration metadata (feature 044, framework-design 3.0.3).

Each step type declares the settings it reads and the names its ``expr``
may use. Strict loading (US1, US2) checks steps against these, so every
core step type declares its settings, and the declarations cover every key
the shipped framework TOML uses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit.config import load_framework_config
from darnit.config.framework_schema import HandlerInvocation
from darnit.sieve.handler_registry import SieveHandlerRegistry, get_sieve_handler_registry

REPO_ROOT = Path(__file__).resolve().parents[3]

CORE_STEP_TYPES = (
    "file_exists",
    "exec",
    "gh_api",
    "regex",
    "pattern",
    "llm_eval",
    "llm_extract",
    "manual",
    "manual_steps",
    "mcp",
    "file_create",
    "platform_setting",
    "project_update",
    "yaml_inject",
)

PLUGIN_STEP_TYPES = (
    "github_branch_protection",
    "generate_threat_model",
    "gittuf_verify_policy",
    "gittuf_commits_signed",
    "repro_deps_pinned",
    "repro_build_env_declared",
    "repro_hermetic_build",
    "repro_provenance_exists",
    "repro_bit_for_bit",
    "csl_llm_if_present",
    "readme_description",
    "readme_quality",
    "ci_config",
)

# Keys shipped TOML sets that no code reads. Each is a silent no-op (#481)
# and fails strict loading (T017) until its TOML is fixed.
UNREAD_SHIPPED_KEYS = {
    ("regex", "patterns"): "the handler reads `pattern` (a string, or `{patterns = {...}}`)",
    ("file_create", "create_dirs"): "the executor always creates parent directories",
    ("manual", "context_hints"): "nothing reads it",
    ("github_branch_protection", "timeout"): "the handler takes no timeout",
}


def _noop(config, context):  # noqa: ARG001
    raise AssertionError("not called")


@pytest.fixture(scope="module")
def plugin_step_types() -> None:
    import importlib

    import darnit_csl.handlers
    from darnit_gittuf.implementation import GittufImplementation
    from darnit_reproducibility.implementation import ReproducibilityImplementation

    from darnit_baseline.implementation import OSPSBaselineImplementation
    from darnit_example.implementation import ExampleHygieneImplementation

    importlib.reload(darnit_csl.handlers)  # registers on import, possibly into a registry reset since
    OSPSBaselineImplementation().register_handlers()
    for implementation in (ExampleHygieneImplementation, GittufImplementation, ReproducibilityImplementation):
        implementation().register_sieve_handlers()


class TestRegister:
    def test_stores_settings_and_expression_names(self) -> None:
        reg = SieveHandlerRegistry()
        reg.register(
            "my_check",
            phase="deterministic",
            handler_fn=_noop,
            settings=frozenset({"files", "threshold"}),
            expression_names=frozenset({"output", "project"}),
        )
        info = reg.get("my_check")
        assert info.settings == frozenset({"files", "threshold"})
        assert info.expression_names == frozenset({"output", "project"})

    def test_defaults(self) -> None:
        reg = SieveHandlerRegistry()
        reg.register("my_check", phase="deterministic", handler_fn=_noop)
        info = reg.get("my_check")
        assert info.settings is None
        assert info.expression_names == frozenset()

    def test_accepts_any_iterable(self) -> None:
        reg = SieveHandlerRegistry()
        reg.register("my_check", phase="deterministic", handler_fn=_noop, settings=["a"], expression_names={"output"})
        info = reg.get("my_check")
        assert info.settings == frozenset({"a"})
        assert info.expression_names == frozenset({"output"})


class TestBuiltinDeclarations:
    @pytest.mark.parametrize("name", CORE_STEP_TYPES)
    def test_core_step_type_declares_settings(self, name: str) -> None:
        info = get_sieve_handler_registry().get(name)
        assert info is not None
        assert info.plugin is None
        assert info.settings is not None

    @pytest.mark.parametrize(
        ("name", "names"),
        [
            ("exec", {"output", "project"}),
            ("pattern", {"output", "project"}),
            ("regex", {"output", "project"}),
            ("gh_api", {"response"}),
            ("mcp", {"result"}),
        ],
    )
    def test_expression_names(self, name: str, names: set[str]) -> None:
        assert get_sieve_handler_registry().get(name).expression_names == frozenset(names)

    @pytest.mark.parametrize("name", sorted(set(CORE_STEP_TYPES) - {"exec", "pattern", "regex", "gh_api", "mcp"}))
    def test_no_expression(self, name: str) -> None:
        assert get_sieve_handler_registry().get(name).expression_names == frozenset()

    def test_settings_exclude_common_step_fields(self) -> None:
        common = set(HandlerInvocation.model_fields) | {"description", "expr"}
        registry = get_sieve_handler_registry()
        for name in CORE_STEP_TYPES:
            assert not registry.get(name).settings & common, name

    @pytest.mark.usefixtures("plugin_step_types")
    @pytest.mark.parametrize("name", PLUGIN_STEP_TYPES)
    def test_shipped_plugin_step_type_declares_settings(self, name: str) -> None:
        info = get_sieve_handler_registry().get(name)
        assert info is not None
        assert info.settings is not None


def _shipped_tomls() -> list[Path]:
    packages = REPO_ROOT / "packages"
    nested = sorted(packages.glob("*/src/*/*.toml"))
    top = sorted(p for p in packages.glob("*/*.toml") if p.name != "pyproject.toml")
    return nested + top


def _steps(path: Path) -> list[tuple[str, HandlerInvocation]]:
    framework = load_framework_config(path)
    steps = []
    for control_id, control in framework.controls.items():
        for index, step in enumerate(control.passes or []):
            steps.append((f"{control_id} pass[{index}]", step))
        if control.remediation is not None:
            for index, step in enumerate(control.remediation.handlers):
                steps.append((f"{control_id} remediation[{index}]", step))
    for name, shared in framework.shared_handlers.items():
        steps.append((f"shared_handlers.{name}", HandlerInvocation(**shared.model_dump())))
    return steps


@pytest.mark.usefixtures("plugin_step_types")
@pytest.mark.parametrize("path", _shipped_tomls(), ids=lambda p: p.name)
def test_declared_settings_cover_shipped_steps(path: Path) -> None:
    registry = get_sieve_handler_registry()
    undeclared = []
    for where, step in _steps(path):
        info = registry.get(step.handler)
        assert info is not None, f"{where}: step type {step.handler!r} is not registered"
        if info.settings is None:
            continue
        for key in sorted(set(step.model_extra or {}) - {"description", "expr"} - info.settings):
            if (step.handler, key) not in UNREAD_SHIPPED_KEYS:
                undeclared.append(f"{where} ({step.handler}): {key}")
    assert not undeclared, "keys outside the step type's declared settings:\n" + "\n".join(undeclared)


def test_unread_shipped_keys_are_still_shipped() -> None:
    shipped = {
        (step.handler, key) for path in _shipped_tomls() for _, step in _steps(path) for key in step.model_extra or {}
    }
    assert set(UNREAD_SHIPPED_KEYS) <= shipped, "remove fixed entries from UNREAD_SHIPPED_KEYS"
