"""Operator ``[plugins] allowed`` is applied before a plugin it leaves out is loaded (framework-design 6.6)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from darnit.config.merger import load_framework_config
from darnit.config.operator.loader import load_operator_config
from darnit.core.composition import CompositionError
from darnit.core.discovery import clear_cache
from darnit.core.registry import get_plugin_registry

# Runs the real CLI entry point in a fresh interpreter, then reports which
# plugin packages that process imported and which plugins registered step types.
_CLI = """
import json, sys
from darnit.cli import main
from darnit.sieve.handler_registry import get_sieve_handler_registry

code = main(sys.argv[1:])
print(json.dumps({
    "exit": code,
    "modules": sorted({m.split(".")[0] for m in sys.modules if m.startswith("darnit_")}),
    "step_type_plugins": sorted({h.plugin for h in get_sieve_handler_registry().list_handlers() if h.plugin}),
}))
"""


def _operator_config(tmp_path: Path, allowed: list[str]) -> Path:
    path = tmp_path / "operator" / "config.toml"
    path.parent.mkdir(mode=0o700)
    path.write_text(f"schema_version = 1\n[plugins]\nallowed = {json.dumps(allowed)}\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def _run_cli(tmp_path: Path, *args: str) -> tuple[dict, str]:
    scratch = tmp_path / "scratch"
    env = dict(os.environ)
    for var, sub in (
        ("HOME", "home"),
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"),
        ("TMPDIR", "tmp"),
    ):
        (scratch / sub).mkdir(parents=True, exist_ok=True)
        env[var] = str(scratch / sub)
    proc = subprocess.run(
        [sys.executable, "-c", _CLI, *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
        check=False,
    )
    report = json.loads(proc.stdout.strip().splitlines()[-1])
    return report, proc.stdout + proc.stderr


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    (path / "README.md").write_text("# Example\n\nA project.\n", encoding="utf-8")
    return path


@pytest.mark.integration
def test_plugin_left_out_is_not_loaded_by_an_audit(tmp_path: Path, repo: Path) -> None:
    config = _operator_config(tmp_path, ["hello"])

    report, output = _run_cli(
        tmp_path, "audit", str(repo), "--framework", "hello", "--operator-config", str(config), "--output", "json"
    )

    assert report["modules"] == ["darnit_hello"], output
    assert "testchecks-steps" not in report["step_type_plugins"], output


@pytest.mark.integration
def test_audit_of_a_framework_left_out_is_refused(tmp_path: Path, repo: Path) -> None:
    config = _operator_config(tmp_path, ["hello"])

    report, output = _run_cli(
        tmp_path,
        "audit",
        str(repo),
        "--framework",
        "testchecks-steps",
        "--operator-config",
        str(config),
        "--output",
        "json",
    )

    assert report["exit"] == 1
    assert "not in the operator configuration's plugins.allowed list (hello)" in output
    assert "TCS-DOC-01" not in output
    assert "darnit_testchecks" not in report["modules"], output
    assert "testchecks-steps" not in report["step_type_plugins"], output


@pytest.mark.integration
def test_allowed_plugin_still_registers_its_step_types(tmp_path: Path, repo: Path) -> None:
    config = _operator_config(tmp_path, ["testchecks-steps"])

    report, output = _run_cli(
        tmp_path,
        "audit",
        str(repo),
        "--framework",
        "testchecks-steps",
        "--operator-config",
        str(config),
        "--output",
        "json",
    )

    assert report["modules"] == ["darnit_testchecks"], output
    assert report["step_type_plugins"] == ["testchecks-steps"], output


@pytest.fixture
def fresh_discovery():
    clear_cache()
    get_plugin_registry().clear_cache()
    yield
    clear_cache()
    get_plugin_registry().clear_cache()


@pytest.mark.unit
def test_composition_source_left_out_fails_loading(tmp_path: Path, fresh_discovery: None) -> None:
    composite = tmp_path / "composite.toml"
    composite.write_text(
        '[metadata]\nname = "composite"\ndisplay_name = "Composite"\nversion = "1.0.0"\n\n'
        '[[compose]]\nsource = "testchecks"\ninclude_all = true\n',
        encoding="utf-8",
    )
    load_operator_config(_operator_config(tmp_path, ["composite"]))

    with pytest.raises(CompositionError, match="testchecks"):
        load_framework_config(composite)


@pytest.mark.integration
def test_serve_refuses_a_framework_left_out(tmp_path: Path) -> None:
    config = _operator_config(tmp_path, ["hello"])

    report, output = _run_cli(tmp_path, "serve", "--framework", "testchecks-steps", "--operator-config", str(config))

    assert report["exit"] == 1
    assert "not in the operator configuration's plugins.allowed list (hello)" in output
    assert report["modules"] == [], output


@pytest.mark.unit
def test_framework_plugins_table_loads_and_has_no_effect(tmp_path: Path, fresh_discovery: None) -> None:
    """The framework TOML [plugins] table is not read (framework-design Appendix C)."""
    framework = tmp_path / "with-plugins.toml"
    framework.write_text(
        '[metadata]\nname = "with-plugins"\ndisplay_name = "With plugins"\nversion = "1.0.0"\n\n'
        '[plugins]\nglobal_allow_unsigned = false\n\n'
        '[plugins."openssf-baseline"]\nallow_unsigned = false\ntrusted_publishers = ["https://example.org/nobody"]\n',
        encoding="utf-8",
    )

    load_framework_config(framework)

    assert "openssf-baseline" in get_plugin_registry().list_frameworks()
