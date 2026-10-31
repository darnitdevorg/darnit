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


# A pattern step with `fail_on_miss` concludes FAIL when none of its files
# exists (#665). One that reads README.md must list every README variant, or
# a project with only README.rst fails without its README being read.
_README_VARIANTS = ("README.md", "README.rst", "README.txt", "README")


def _fail_on_miss_steps() -> list[tuple[str, dict]]:
    return sorted(
        (
            (control_id, p)
            for control_id, control in _load_framework()["controls"].items()
            for p in control.get("passes", [])
            if p.get("handler") in ("pattern", "regex") and p.get("fail_on_miss")
        ),
        key=lambda step: step[0],
    )


@pytest.mark.parametrize(
    ("control_id", "step"),
    [s for s in _fail_on_miss_steps() if "README.md" in s[1].get("files", [])],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_fail_on_miss_lists_every_readme_variant(control_id: str, step: dict):
    files = step["files"]
    missing = [v for v in _README_VARIANTS if v not in files]
    assert not missing, f"{control_id}: fail_on_miss pattern lacks {missing}: {files}"


# Remediation acts on that FAIL. On a case-sensitive filesystem, a file it
# creates under a name the step does not list leaves the control failing.
@pytest.mark.parametrize(("control_id", "step"), _fail_on_miss_steps(), ids=lambda v: v if isinstance(v, str) else "")
def test_fail_on_miss_lists_what_remediation_creates(framework: dict, control_id: str, step: dict):
    handlers = framework["controls"][control_id].get("remediation", {}).get("handlers", [])
    created = {h["path"] for h in handlers if h.get("handler") == "file_create"}
    assert created <= set(step["files"]), f"{control_id}: remediation creates {created - set(step['files'])}"
