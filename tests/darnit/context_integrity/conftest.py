"""Scratch repositories and a no-write snapshot helper (feature 042, quickstart.md).

The builders reproduce the repositories from the issue reports:

- ``R-maint``: MAINTAINERS.md and SECURITY.md, no ``.project/`` (#468, #469, #465).
- ``R-rel``: nothing but an origin, for release detection with a bad token (#470).
- ``R-ci``: a GitHub Actions workflow, no ``.project/`` (#476).
- ``R-hand``: a hand-written ``.project/project.yaml`` darnit's schema rejects (#463).
- ``R-legacy``: ``.project/`` written by an earlier darnit version, with bare
  values and no confirmation records.

Every repository has an ``origin`` of ``https://github.com/example-org/<name>``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.conftest_helpers import assert_unchanged, snapshot

__all__ = ["assert_unchanged", "snapshot", "write_operator_config"]

CI_VARS = ("GITHUB_ACTIONS", "GITLAB_CI", "CI", "JENKINS_URL", "TF_BUILD", "BUILDKITE", "CIRCLECI", "TRAVIS")

R_HAND_PROJECT_YAML = """\
# Maintained by hand. Do not reformat.
name: hand-project
description: A project that writes its own .project data
social:
  - https://social.example.net/@hand
maturity_log:
  - phase: sandbox
    date: not-a-date
security:
  contact: security@hand.example.net
"""

R_LEGACY_PROJECT_YAML = """\
# .project/project.yaml - CNCF Project Configuration
# https://github.com/cncf/automation/tree/main/utilities/dot-project

name: legacy-project
"""

R_LEGACY_DARNIT_YAML = """\
# .project/darnit.yaml - Darnit Extension

version: '1.0'
controls:
  OSPS-BR-02.01:
    status: n/a
    reason: No releases yet
    asserted_by: '@maintainer'
context:
  maintainers:
  - '@alice'
  - '@realcorp'
  has_releases: false
  ci_provider: github_actions
"""


@pytest.fixture(autouse=True)
def _no_ci_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trust decisions read CI metadata from the environment; keep the test runner's out."""
    for var in CI_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(scope="session")
def _offline_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # A link to the system `false` rather than a new script: some platforms
    # scan a freshly written executable on first run, which takes seconds.
    bin_dir = tmp_path_factory.mktemp("offline-bin")
    (bin_dir / "gh").symlink_to(shutil.which("false"))
    return bin_dir


@pytest.fixture(autouse=True)
def _offline_gh(_offline_bin: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``gh`` that always fails, so no test here reaches a real platform."""
    monkeypatch.setenv("PATH", f"{_offline_bin}{os.pathsep}{os.environ.get('PATH', '')}")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _init_repo(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "--initial-branch=main", "-q")
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "--allow-empty", "-q", "-m", "init")
    _git(root, "remote", "add", "origin", f"https://github.com/example-org/{root.name.lower()}.git")
    return root


def build_r_maint(root: Path) -> Path:
    return _init_repo(
        root,
        {
            "README.md": "# r-maint\n",
            "MAINTAINERS.md": "# Maintainers\n\n- Alice Example <alice@realcorp.io> @alice\n",
            "SECURITY.md": "# Security\n\nReport vulnerabilities to security@realcorp.io.\n",
        },
    )


def build_r_rel(root: Path) -> Path:
    return _init_repo(root, {"README.md": "# r-rel\n"})


def build_r_ci(root: Path) -> Path:
    return _init_repo(
        root,
        {
            "README.md": "# r-ci\n",
            ".github/workflows/ci.yml": "name: ci\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n",
        },
    )


def build_r_hand(root: Path) -> Path:
    return _init_repo(root, {"README.md": "# r-hand\n", ".project/project.yaml": R_HAND_PROJECT_YAML})


def build_r_legacy(root: Path) -> Path:
    return _init_repo(
        root,
        {
            "README.md": "# r-legacy\n",
            ".project/project.yaml": R_LEGACY_PROJECT_YAML,
            ".project/darnit.yaml": R_LEGACY_DARNIT_YAML,
        },
    )


def build_empty(root: Path) -> Path:
    return _init_repo(root, {})


BUILDERS: dict[str, Callable[[Path], Path]] = {
    "R-maint": build_r_maint,
    "R-rel": build_r_rel,
    "R-ci": build_r_ci,
    "R-hand": build_r_hand,
    "R-legacy": build_r_legacy,
    "empty": build_empty,
}


@pytest.fixture
def scratch_repo(tmp_path: Path) -> Callable[[str], Path]:
    """Build a named scratch repository under ``tmp_path``."""

    def _build(name: str) -> Path:
        return BUILDERS[name](tmp_path / name)

    return _build


def write_operator_config(path: Path, *, trusted: list[str] = (), identity: str | None = None) -> Path:
    """Write an operator configuration file that trusts ``trusted`` and select it for this run."""
    from darnit.config.operator.loader import set_launch_options

    lines = ["schema_version = 1", ""]
    if identity:
        lines += ["[operator]", f'identity = "{identity}"', ""]
    lines += ["[trust]", "repos = [" + ", ".join(f'"{r}"' for r in trusted) + "]", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    path.chmod(0o600)
    set_launch_options(path, strict=False)
    return path
