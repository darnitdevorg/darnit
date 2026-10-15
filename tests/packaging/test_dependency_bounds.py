# SPDX-License-Identifier: Apache-2.0
"""Regression tests for runtime dependency compatibility bounds."""

import tomllib
from pathlib import Path

from packaging.requirements import Requirement

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pydantic_ai_dependency_bounds() -> None:
    with (REPO_ROOT / "packages/darnit/pyproject.toml").open("rb") as source:
        project = tomllib.load(source)
    requirements = [Requirement(dependency) for dependency in project["project"]["dependencies"]]
    requirement = next(item for item in requirements if item.name == "pydantic-ai-slim")

    assert "0.0.14" not in requirement.specifier
    assert "2.24.0" in requirement.specifier
    assert "3.0.0" not in requirement.specifier

    with (REPO_ROOT / "uv.lock").open("rb") as source:
        lock = tomllib.load(source)
    locked = next(package for package in lock["package"] if package["name"] == "pydantic-ai-slim")
    assert locked["version"] in requirement.specifier
