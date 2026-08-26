"""SC-008 + FR-017 import-isolation guards for feature 033.

Two AST-walking assertions:

* **SC-008**: no module under ``packages/darnit/src/darnit/`` imports a
  named third-party AttestationStore / ReportStore / AuditCacheStore
  backend directly. Backend discovery MUST route through
  ``darnit.stores.discovery`` -- direct references would defeat the
  plugin abstraction and re-couple darnit-core to specific backends.
* **FR-017**: no module under ``packages/darnit/src/darnit/sieve/``
  imports from ``darnit.stores`` at all. Sieve handlers must NOT
  consume stores directly; the audit driver is the sole boundary that
  wires stores into control execution.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DARNIT_SRC = _REPO_ROOT / "packages" / "darnit" / "src" / "darnit"
_SIEVE_SRC = _DARNIT_SRC / "sieve"

# Third-party backend module prefixes that must NEVER be imported by
# darnit-core. The in-memory reference backends in `darnit_testchecks`
# are a testing sibling package; if a `darnit.*` module named them
# directly, the plugin abstraction is broken.
_BANNED_TP_MODULE_PREFIXES = (
    "darnit_testchecks.stores",
    "example_store_plugin",
)


def _iter_py_files(root: Path):
    for p in root.rglob("*.py"):
        # Skip __pycache__ and .pyc detritus.
        if "__pycache__" in p.parts:
            continue
        yield p


def _module_names_imported(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
    return names


class TestSC008NoDirectBackendImports:
    def test_darnit_core_never_imports_third_party_backend_module(self):
        offenders: list[tuple[Path, str]] = []
        for f in _iter_py_files(_DARNIT_SRC):
            source = f.read_text(encoding="utf-8")
            imported = _module_names_imported(source)
            for name in imported:
                for banned_prefix in _BANNED_TP_MODULE_PREFIXES:
                    if name == banned_prefix or name.startswith(
                        banned_prefix + "."
                    ):
                        offenders.append((f, name))
        assert not offenders, (
            "darnit-core must not import third-party store backends "
            "directly; use discover_stores() instead. Offenders:\n"
            + "\n".join(f"  {f}: {n}" for f, n in offenders)
        )


class TestFR017SieveNeverConsumesStores:
    def test_sieve_modules_never_import_darnit_stores(self):
        offenders: list[tuple[Path, str]] = []
        for f in _iter_py_files(_SIEVE_SRC):
            source = f.read_text(encoding="utf-8")
            imported = _module_names_imported(source)
            for name in imported:
                if name == "darnit.stores" or name.startswith("darnit.stores."):
                    offenders.append((f, name))
        assert not offenders, (
            "sieve modules must NOT import from darnit.stores "
            "(FR-017). The audit driver is the sole boundary. "
            "Offenders:\n"
            + "\n".join(f"  {f}: {n}" for f, n in offenders)
        )
