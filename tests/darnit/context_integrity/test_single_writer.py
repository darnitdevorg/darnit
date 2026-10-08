"""Only the named modules write ``.project/`` through the loader's write helpers (feature 042, research R1)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGES = Path(__file__).resolve().parents[3] / "packages"

WRITE_HELPERS = frozenset(
    {
        "save_project_config",
        "_write_yaml_file",
        "update_yaml_file",
        "update_extension_file",
        "update_project_config",
        "save_context_value",
        "save_context_values",
    }
)

ALLOWED = {
    # Context values and in-repository confirmation records (the single writer).
    "darnit/src/darnit/config/context_writes.py",
    # Applied (non-dry-run) remediation.
    "darnit/src/darnit/remediation/executor.py",
    # File-location references, not context values.
    "darnit/src/darnit/config/resolver.py",
    # `darnit config migrate` moves .baseline.toml claims into `controls:` (feature 040).
    "darnit/src/darnit/config/operator/migrate.py",
    # The helpers themselves.
    "darnit/src/darnit/config/loader.py",
}


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _writers() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in PACKAGES.glob("*/src/**/*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _called_name(node) in WRITE_HELPERS:
                found.setdefault(path.relative_to(PACKAGES).as_posix(), set()).add(_called_name(node))
    return found


@pytest.mark.unit
def test_only_named_modules_write_project_files() -> None:
    unexpected = {module: sorted(names) for module, names in _writers().items() if module not in ALLOWED}

    assert unexpected == {}


@pytest.mark.unit
def test_context_values_have_one_writer() -> None:
    assert "darnit/src/darnit/config/context_writes.py" in _writers()


@pytest.mark.unit
def test_legacy_context_savers_are_gone() -> None:
    from darnit.config import context_storage

    assert not hasattr(context_storage, "save_context_value")
    assert not hasattr(context_storage, "save_context_values")
