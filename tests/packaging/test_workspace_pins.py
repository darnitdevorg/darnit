"""Intra-workspace requirements move with the workspace version.

``darnit-mcp`` is a lockstep meta-package: ``pip install -U darnit-mcp`` must
move every component to the same release. With ``>=`` floors at the previous
version, pip's default strategy left ``darnit-core`` and the old plugin in
place and the new one could not load (review on #532). So the meta-package
pins its components ``==`` the workspace version, and every other
requirement between workspace packages is bounded by that version too, so a
release bump that forgets them fails here instead of on PyPI.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ["pyproject.toml", *sorted(str(p.relative_to(ROOT)) for p in ROOT.glob("packages/*/pyproject.toml"))]
PUBLIC = set((ROOT / "packaging/pypi/public-packages.txt").read_text().split())


def _projects() -> dict[str, tuple[str, dict]]:
    """The public packages: the ones a release ships in lockstep (packaging/pypi/public-packages.txt)."""
    out = {}
    for rel in WORKSPACE:
        data = tomllib.loads((ROOT / rel).read_text())
        project = data.get("project") or {}
        if project.get("name") in PUBLIC:
            out[project["name"]] = (rel, project)
    return out


def _requirements(project: dict) -> list[Requirement]:
    reqs = [Requirement(r) for r in project.get("dependencies") or []]
    for extra in (project.get("optional-dependencies") or {}).values():
        reqs += [Requirement(r) for r in extra]
    return reqs


def test_every_public_package_has_the_same_version() -> None:
    versions = {name: project["version"] for name, (_, project) in _projects().items()}
    assert set(versions) == PUBLIC, "public-packages.txt and the workspace disagree"
    assert len(set(versions.values())) == 1, versions


def test_darnit_mcp_pins_its_components_to_its_own_version() -> None:
    projects = _projects()
    rel, mcp = projects["darnit-mcp"]
    version = mcp["version"]
    pinned = {r.name: str(r.specifier) for r in _requirements(mcp) if r.name in projects}
    assert pinned, "darnit-mcp depends on no workspace package?"
    for name, spec in pinned.items():
        assert spec == f"=={version}", f"{rel}: {name}{spec} should be {name}=={version}"


def test_public_requirements_are_bounded_by_the_workspace_version() -> None:
    """``name==X`` or a floor ``name>=X`` where X is the workspace version: nothing older satisfies it."""
    projects = _projects()
    version = projects["darnit-mcp"][1]["version"]
    problems = []
    for name, (rel, project) in projects.items():
        for req in _requirements(project):
            if req.name not in projects:
                continue
            specs = {(s.operator, s.version) for s in req.specifier}
            if ("==", version) in specs or (">=", version) in specs:
                continue
            problems.append(f"{rel}: {req} (workspace version is {version})")
    assert not problems, "\n".join(problems)


def test_pins_appear_verbatim_so_the_release_bump_finds_them() -> None:
    """The runbook bumps versions with a text replace; the pins must be written as plain ``==X`` literals."""
    projects = _projects()
    version = projects["darnit-mcp"][1]["version"]
    text = (ROOT / "pyproject.toml").read_text()
    for name in ("darnit-core", "darnit-baseline", "darnit-gittuf", "darnit-amber"):
        assert re.search(rf'"{name}=={re.escape(version)}"', text), f"{name}=={version} not written verbatim"
