"""An offline repository whose one operator-defined control needs a model judgment (feature 041 tests).

The control runs on the ``hello`` framework (file checks only, no platform
calls) and is added through the operator configuration, so an audit reaches
its ``llm_eval`` step without touching the network.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from darnit.config.operator.loader import set_launch_options

FRAMEWORK = "hello"
CONTROL = "JUDGE-01.01"
OWNER = "example"
REPO = "project"
IDENTITY = f"github.com/{OWNER}/{REPO}"
TARGET = IDENTITY

README = """# Project

Project is a command-line tool that converts Markdown documents to HTML.

## Installation

Run `pip install project` to install it.
"""

EXCERPT = "Project is a command-line tool that converts Markdown documents to HTML."

CI_VARS = ("GITHUB_ACTIONS", "GITLAB_CI", "CI", "JENKINS_URL", "TF_BUILD", "BUILDKITE", "CIRCLECI", "TRAVIS")


def make_repo(tmp_path: Path, readme: str = README) -> Path:
    path = tmp_path / "repo"
    path.mkdir(parents=True, exist_ok=True)
    (path / "README.md").write_text(readme, encoding="utf-8")
    if not (path / ".git").exists():
        subprocess.run(["git", "init", "--initial-branch=main", "-q"], cwd=path, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", f"https://github.com/{OWNER}/{REPO}.git"], cwd=path, check=True
        )
    return path


def write_operator_config(tmp_path: Path, prompt: str = "Does the README describe what the project is?") -> Path:
    """Write an operator configuration adding CONTROL, and make it this process's launch option."""
    path = tmp_path / "operator" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""schema_version = 1

[custom_controls."{CONTROL}"]
name = "ReadmeDescribesProject"
description = "The README describes what the project is."
level = 1
domain = "JUDGE"
passes = [
  {{ handler = "file_exists", files = ["README.md"] }},
  {{ handler = "llm_eval", prompt = "{prompt}", files_to_include = ["README.md"], analysis_hints = ["Look for a purpose statement"] }},
  {{ handler = "manual", steps = ["Read the README"] }},
]
""",
        encoding="utf-8",
    )
    path.chmod(0o600)
    set_launch_options(path)
    return path


def audit(repo: Path, target: str | None = TARGET) -> dict:
    """Run the canonical audit and return CONTROL's result."""
    from darnit.config.operator.loader import resolve_operator_config
    from darnit.tools.audit import run_sieve_audit

    results, _ = run_sieve_audit(
        OWNER,
        REPO,
        str(repo),
        "main",
        level=1,
        framework_name=FRAMEWORK,
        operator_config=resolve_operator_config(str(repo)),
        target=target,
    )
    return next(r for r in results if r["id"] == CONTROL)
