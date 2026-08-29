"""Regression guard for the pattern-handler file-list widening.

Sibling to `test_llm_eval_file_contents.py` (#402). The 5 controls
that go `pattern -> llm_eval` (no `file_exists` between) previously
listed .md-only README candidates in their `pattern.files`. On projects
that ship a .rst / .txt / no-extension README (tqdm, and any Sphinx-
based Python project), the pattern tier resolved INCONCLUSIVE and
llm_eval fired -- which was the trigger for #402's empty-file_contents
bug in the first place.

Widening the pattern lists to include README.rst / README.txt / README
means the deterministic tier PASSes or FAILs conclusively on those
repos, and the LLM tier fires less often. This test locks the widening
in place per control -- a revert of any entry re-opens the same class
of bug.
"""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib  # type: ignore

_FRAMEWORK_TOML = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "darnit-baseline"
    / "src"
    / "darnit_baseline"
    / "openssf-baseline.toml"
)


def _load_framework() -> dict:
    with open(_FRAMEWORK_TOML, "rb") as f:
        return tomllib.load(f)


def _pattern_files(framework: dict, control_id: str) -> list[str]:
    """Return the `files` list of the first `pattern` pass on control_id."""
    for p in framework["controls"][control_id]["passes"]:
        if p.get("handler") in ("pattern", "regex"):
            return list(p.get("files", []))
    return []


# Controls whose pattern handler gates an llm_eval pass. Widening their
# file lists reduces how often the LLM tier fires on non-.md repos.
_GATED_CONTROLS = [
    "OSPS-DO-03.02",
    "OSPS-DO-04.01",
    "OSPS-DO-05.01",
    "OSPS-SA-01.01",
    "OSPS-SA-02.01",
]


@pytest.fixture(scope="module")
def framework() -> dict:
    return _load_framework()


@pytest.mark.parametrize("control_id", _GATED_CONTROLS)
def test_pattern_list_covers_rst_readme(framework: dict, control_id: str):
    """Each gated control's pattern.files MUST include README.rst.

    Without it, the deterministic tier can't resolve on Sphinx-based
    projects and the pipeline falls through to `llm_eval`.
    """
    files = _pattern_files(framework, control_id)
    assert "README.rst" in files, (
        f"{control_id}: pattern handler's `files` list must include "
        f"README.rst so the deterministic tier can resolve on rst-based "
        f"projects (see #402). Current list: {files}"
    )


@pytest.mark.parametrize(
    "control_id",
    ["OSPS-DO-03.02", "OSPS-DO-04.01", "OSPS-DO-05.01"],
)
def test_pattern_list_covers_txt_and_no_ext_readme(
    framework: dict, control_id: str
):
    """DO-* controls that scan README should also accept `README.txt`
    and the no-extension `README` filename convention some older
    projects still use."""
    files = _pattern_files(framework, control_id)
    assert "README.txt" in files, f"{control_id}: missing README.txt in {files}"
    assert "README" in files, f"{control_id}: missing README in {files}"
