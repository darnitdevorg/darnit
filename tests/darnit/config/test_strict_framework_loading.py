"""Strict framework loading (feature 044, US2, FR-007 to FR-009, framework-design 2.3 and 3.0.3).

Unknown control keys, step keys outside the common step fields and the step
type's declared settings, and unregistered step types fail loading, naming
the framework file, control, step, and key. A plugin step type that does not
declare its settings loads with one warning per step type. An operator
control naming a step type that is not registered loads and audits ERROR,
class ``missing_tool``.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

import darnit.config.control_loader as control_loader
from darnit.config import load_framework_config
from darnit.config.control_loader import load_controls_from_effective, load_controls_from_framework
from darnit.config.merger import merge_configs
from darnit.config.operator.schema import OperatorConfig
from darnit.core.errors import AuthorityViolation
from darnit.sieve.handler_registry import HandlerContext, HandlerResult, HandlerResultStatus, get_sieve_handler_registry
from darnit.sieve.models import CheckContext
from darnit.sieve.orchestrator import SieveOrchestrator

REPO_ROOT = Path(__file__).resolve().parents[3]

HEADER = """\
[metadata]
name = "strict-fw"
display_name = "Strict"
version = "0.0.1"
spec_version = "t"

[controls."STR-01"]
name = "Strict"
description = "A control"
level = 1
domain = "ST"
"""


def _toml(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "strict.toml"
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def _shipped_tomls() -> list[Path]:
    packages = REPO_ROOT / "packages"
    nested = sorted(packages.glob("*/src/*/*.toml"))
    top = sorted(p for p in packages.glob("*/*.toml") if p.name != "pyproject.toml")
    return nested + top


@pytest.fixture(scope="module")
def plugin_step_types() -> None:
    import importlib

    import darnit_csl.handlers
    from darnit_gittuf.implementation import GittufImplementation
    from darnit_reproducibility.implementation import ReproducibilityImplementation

    from darnit_baseline.implementation import OSPSBaselineImplementation
    from darnit_example.implementation import ExampleHygieneImplementation

    importlib.reload(darnit_csl.handlers)
    OSPSBaselineImplementation().register_handlers()
    for implementation in (ExampleHygieneImplementation, GittufImplementation, ReproducibilityImplementation):
        implementation().register_sieve_handlers()


def _loose(config, context: HandlerContext) -> HandlerResult:  # noqa: ARG001
    return HandlerResult(status=HandlerResultStatus.INCONCLUSIVE, message="evidence")


@pytest.mark.unit
class TestControlKeys:
    """FR-007."""

    def test_unknown_control_key_names_file_control_and_key(self, tmp_path: Path) -> None:
        path = _toml(tmp_path, 'nmae = "typo"\n')

        with pytest.raises(ValueError) as excinfo:
            load_framework_config(path)

        text = str(excinfo.value)
        for fragment in (str(path), "STR-01", "nmae"):
            assert fragment in text, (fragment, text)


@pytest.mark.unit
class TestStepKeys:
    """FR-008."""

    def test_misspelled_step_setting(self, tmp_path: Path) -> None:
        path = _toml(
            tmp_path,
            '[[controls."STR-01".passes]]\nhandler = "pattern"\nfiles = ["README.md"]\npattern = "x"\n'
            "fail_on_mis = true\n",
        )

        with pytest.raises(AuthorityViolation) as excinfo:
            load_controls_from_framework(load_framework_config(path))

        text = str(excinfo.value)
        for fragment in (str(path), "STR-01", "pass[0]:pattern", "fail_on_mis"):
            assert fragment in text, (fragment, text)

    def test_misspelled_remediation_setting(self, tmp_path: Path) -> None:
        path = _toml(
            tmp_path,
            '[[controls."STR-01".remediation.handlers]]\nhandler = "file_create"\npath = "README.md"\ncontnet = "x"\n',
        )

        with pytest.raises(AuthorityViolation) as excinfo:
            load_controls_from_framework(load_framework_config(path))

        text = str(excinfo.value)
        for fragment in (str(path), "STR-01", "remediation[0]:file_create", "contnet"):
            assert fragment in text, (fragment, text)

    def test_declared_settings_and_common_fields_load(self, tmp_path: Path) -> None:
        path = _toml(
            tmp_path,
            '[[controls."STR-01".passes]]\nhandler = "pattern"\nfiles = ["README.md"]\npattern = "x"\n'
            'description = "documentation only"\nfail_on_miss = true\nwhen = { ci_provider = "github" }\n',
        )

        assert [c.control_id for c in load_controls_from_framework(load_framework_config(path))] == ["STR-01"]

    def test_effective_path_checks_step_keys(self, tmp_path: Path) -> None:
        path = _toml(tmp_path, '[[controls."STR-01".passes]]\nhandler = "exec"\ncommand = ["true"]\ntimout = 5\n')

        with pytest.raises(AuthorityViolation, match="timout"):
            load_controls_from_effective(merge_configs(load_framework_config(path)))

    def test_plugin_step_type_without_settings_warns_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        registry = get_sieve_handler_registry()
        registry.set_plugin_context("loose-plugin")
        try:
            registry.register("loose_check_044", "deterministic", _loose)
        finally:
            registry.set_plugin_context(None)
        monkeypatch.setattr(control_loader, "_UNCHECKED_SETTINGS_WARNED", set())
        path = _toml(
            tmp_path,
            '[[controls."STR-01".passes]]\nhandler = "loose_check_044"\nanything = 1\n\n'
            '[controls."STR-02"]\nname = "Second"\ndescription = "Another"\nlevel = 1\ndomain = "ST"\n\n'
            '[[controls."STR-02".passes]]\nhandler = "loose_check_044"\nelse = 2\n',
        )

        with caplog.at_level(logging.WARNING):
            load_controls_from_framework(load_framework_config(path))
            load_controls_from_framework(load_framework_config(path))

        warnings = [r for r in caplog.records if "loose_check_044" in r.getMessage()]
        assert len(warnings) == 1
        assert "not checked" in warnings[0].getMessage()


@pytest.mark.unit
class TestStepTypes:
    """FR-009."""

    def test_unregistered_step_type_fails_loading(self, tmp_path: Path) -> None:
        path = _toml(tmp_path, '[[controls."STR-01".passes]]\nhandler = "file_must_exst"\nfiles = ["README.md"]\n')

        with pytest.raises(AuthorityViolation) as excinfo:
            load_controls_from_framework(load_framework_config(path))

        text = str(excinfo.value)
        for fragment in ("STR-01", "file_must_exst", "not registered"):
            assert fragment in text, (fragment, text)

    def test_unregistered_remediation_step_type_fails_loading(self, tmp_path: Path) -> None:
        path = _toml(tmp_path, '[[controls."STR-01".remediation.handlers]]\nhandler = "file_creat"\npath = "x"\n')

        with pytest.raises(AuthorityViolation, match="file_creat"):
            load_controls_from_framework(load_framework_config(path))

    def test_operator_control_naming_a_missing_plugin_step_type_is_error(self, tmp_path: Path) -> None:
        framework = load_framework_config(_toml(tmp_path, ""))
        operator = OperatorConfig.model_validate(
            {
                "schema_version": 1,
                "custom_controls": {
                    "OP-01": {
                        "name": "Operator control",
                        "description": "Uses a plugin that is not installed",
                        "level": 1,
                        "passes": [{"handler": "absent_plugin_check", "threshold": 3}],
                    }
                },
            }
        )

        specs = {s.control_id: s for s in load_controls_from_effective(merge_configs(framework, None, operator))}
        context = CheckContext(owner="o", repo="r", local_path=str(tmp_path), default_branch="main", control_id="OP-01")
        result = SieveOrchestrator(stop_on_llm=False).verify(specs["OP-01"], context)

        assert result.status == "ERROR"
        assert result.error["class"] == "missing_tool"
        assert "absent_plugin_check" in result.error["cause"]
        assert "not registered" in result.error["cause"]

    def test_operator_pass_override_naming_a_missing_plugin_step_type_is_error(self, tmp_path: Path) -> None:
        framework = load_framework_config(
            _toml(tmp_path, '[[controls."STR-01".passes]]\nhandler = "file_exists"\nfiles = ["README.md"]\n')
        )
        operator = OperatorConfig.model_validate(
            {"schema_version": 1, "controls": {"STR-01": {"passes": [{"handler": "absent_plugin_check"}]}}}
        )

        specs = {s.control_id: s for s in load_controls_from_effective(merge_configs(framework, None, operator))}
        context = CheckContext(
            owner="o", repo="r", local_path=str(tmp_path), default_branch="main", control_id="STR-01"
        )
        result = SieveOrchestrator(stop_on_llm=False).verify(specs["STR-01"], context)

        assert result.status == "ERROR"
        assert result.error["class"] == "missing_tool"


@pytest.mark.unit
@pytest.mark.usefixtures("plugin_step_types")
@pytest.mark.parametrize("path", _shipped_tomls(), ids=lambda p: p.name)
def test_shipped_framework_loads(path: Path) -> None:
    framework = load_framework_config(path)

    assert len(load_controls_from_framework(framework)) == len(framework.controls)
    assert len(load_controls_from_effective(merge_configs(framework))) == len(framework.controls)


@pytest.mark.unit
def test_validate_sync_passes() -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from validate_sync import run_validations
    finally:
        sys.path.remove(str(REPO_ROOT / "scripts"))

    assert run_validations() == 0
