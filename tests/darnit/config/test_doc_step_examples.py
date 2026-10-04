"""Documented step examples use only keys strict loading accepts (feature 044, 044 review).

A TOML example in the documentation that declares a step key its step type
does not read (for example ``create_dirs`` on ``file_create``) teaches a
framework author a file that fails to load (framework-design 3.0.3). Every
parseable TOML block under ``docs/`` (except ``docs/design/``, which holds
proposals, and ``docs/threatmodel/``) is checked against the registered step
types' declared settings. A block fenced as ```` ```toml removed ```` shows
syntax that no longer loads (a migration guide's "before") and is not checked.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

from darnit.config.control_loader import COMMON_STEP_FIELDS
from darnit.sieve.handler_registry import get_sieve_handler_registry

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS = REPO_ROOT / "docs"
SKIPPED = (DOCS / "design", DOCS / "threatmodel")
TOML_BLOCK = re.compile(r"^```toml\n(.*?)^```", re.MULTILINE | re.DOTALL)


@pytest.fixture(scope="module", autouse=True)
def _plugin_step_types() -> None:
    from darnit_baseline.implementation import OSPSBaselineImplementation

    OSPSBaselineImplementation().register_handlers()


def _doc_files() -> list[Path]:
    return sorted(p for p in DOCS.rglob("*.md") if not any(p.is_relative_to(s) for s in SKIPPED))


def _steps(document: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    steps: list[tuple[str, dict[str, Any]]] = []
    controls = document.get("controls")
    if not isinstance(controls, dict):
        return steps
    for control_id, control in controls.items():
        if not isinstance(control, dict):
            continue
        for idx, step in enumerate(control.get("passes") or []):
            steps.append((f"{control_id} pass[{idx}]", step))
        remediation = control.get("remediation")
        if isinstance(remediation, dict):
            for idx, step in enumerate(remediation.get("handlers") or []):
                steps.append((f"{control_id} remediation[{idx}]", step))
    return steps


def _unaccepted_keys(path: Path) -> list[str]:
    registry = get_sieve_handler_registry()
    problems = []
    for number, match in enumerate(TOML_BLOCK.finditer(path.read_text(encoding="utf-8"))):
        try:
            document = tomllib.loads(match.group(1))
        except tomllib.TOMLDecodeError:
            continue
        for where, step in _steps(document):
            if not isinstance(step, dict):
                continue
            info = registry.get(str(step.get("handler")))
            if info is None or info.settings is None:
                continue
            unknown = sorted(set(step) - COMMON_STEP_FIELDS - info.settings)
            if unknown:
                problems.append(f"block {number}, {where} ({info.name}): {', '.join(unknown)}")
    return problems


@pytest.mark.unit
@pytest.mark.parametrize("path", _doc_files(), ids=lambda p: str(p.relative_to(DOCS)))
def test_documented_steps_use_accepted_keys(path: Path) -> None:
    assert _unaccepted_keys(path) == []
