#!/usr/bin/env python3
"""Set up dedicated E2E test projects for Darnit audit and remediation testing.

Flow brainstormed in the October 27, 2026 Darnit Community Meeting
(local and automated testing agenda by Mike Lieberman and Jaydeep Pokhariya).

Creates reproducible local test repositories with known expected outcomes
(failing, partially-compliant, and passing) for testing Darnit CLI, harness,
and agentic workflows.

Usage:
    uv run python scripts/setup_dev_projects.py [--dest PATH] [--clean] [--projects all|failing|partial|passing]

Default destination:
    <tempdir>/darnit-dev-projects (or /tmp/darnit-dev-projects on POSIX)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("setup_dev_projects")

REPO_ROOT = Path(__file__).resolve().parent.parent


def safe_rmtree(path: Path) -> None:
    """Safely remove a directory tree across platforms, handling read-only git files."""
    if not path.exists():
        return

    def _remove_readonly(func, p, exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_remove_readonly)
    else:
        shutil.rmtree(path, onerror=_remove_readonly)


DEFAULT_DEST = (
    Path("/tmp/darnit-dev-projects")
    if os.name != "nt" and Path("/tmp").exists()
    else Path(tempfile.gettempdir()) / "darnit-dev-projects"
)

MIT_LICENSE = """MIT License

Copyright (c) 2026 Darnit Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


def _init_git_repo(project_dir: Path, commit_msg: str = "Initial commit") -> None:
    """Initialize git repository with reproducible configuration."""
    subprocess.run(["git", "init", "-q"], cwd=project_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Darnit Developer"], cwd=project_dir, check=True)
    subprocess.run(["git", "config", "user.email", "dev@darnit.local"], cwd=project_dir, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=project_dir, check=True)
    subprocess.run(["git", "add", "."], cwd=project_dir, check=True)
    subprocess.run(["git", "commit", "-m", commit_msg, "-q"], cwd=project_dir, check=True)


def _write_common_files(project_dir: Path, project_name: str) -> None:
    """Write .mcp.json and CLAUDE.md for agent-based compliance testing."""
    mcp_config = {
        "mcpServers": {
            "darnit": {
                "command": "uv",
                "args": [
                    "--directory",
                    str(REPO_ROOT),
                    "run",
                    "darnit",
                    "serve",
                    "--framework",
                    "openssf-baseline",
                ],
            }
        }
    }
    (project_dir / ".mcp.json").write_text(json.dumps(mcp_config, indent=2) + "\n", encoding="utf-8")

    claude_md = f"""# {project_name}

This repository is an automated test fixture for Darnit compliance auditing and remediation.

## E2E Testing Instructions
1. Run audit:
   `/darnit-audit openssf-baseline`
2. Check/collect context:
   `/darnit-data`
3. Run remediation:
   `/darnit-comply openssf-baseline`
"""
    (project_dir / "CLAUDE.md").write_text(claude_md, encoding="utf-8")


def create_failing_empty_project(target_dir: Path) -> Path:
    """Create a minimal project that intentionally fails documentation and security controls."""
    project_dir = target_dir / "failing-empty"
    if project_dir.exists():
        safe_rmtree(project_dir)
    project_dir.mkdir(parents=True)

    src_dir = project_dir / "src" / "failing_empty"
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text('"""Failing empty package."""\n', encoding="utf-8")
    (src_dir / "main.py").write_text("def run():\n    print('Hello')\n", encoding="utf-8")

    (project_dir / "pyproject.toml").write_text(
        '[project]\nname = "failing-empty"\nversion = "0.1.0"\nrequires-python = ">=3.10"\n',
        encoding="utf-8",
    )

    expected = {
        "project": "failing-empty",
        "description": "Minimal repository missing documentation, license, security policy, and CI workflows",
        "expected": {
            "OSPS-DO-01.01": "FAIL",
            "OSPS-LE-03.01": "FAIL",
            "OSPS-GV-01.01": "FAIL",
            "OSPS-GV-03.01": "FAIL",
            "OSPS-VM-02.01": "FAIL",
            "OSPS-VM-05.03": "FAIL",
            "OSPS-BR-07.01": "FAIL",
            "OSPS-DO-03.01": "FAIL",
            "OSPS-GV-04.01": "FAIL",
            "OSPS-QA-02.01": "PASS",
            "OSPS-QA-05.01": "PASS",
        },
        "min_failures": 10,
        "max_failures": 15,
        "max_errors": 20,
    }
    (project_dir / "expected_verdicts.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")

    _write_common_files(project_dir, "failing-empty")
    _init_git_repo(project_dir, "Initial commit for failing-empty test project")
    logger.info("Created failing-empty at %s", project_dir)
    return project_dir


def create_partially_compliant_project(target_dir: Path) -> Path:
    """Create a project with README and LICENSE, but missing security policy and using unpinned actions."""
    project_dir = target_dir / "partially-compliant"
    if project_dir.exists():
        safe_rmtree(project_dir)
    project_dir.mkdir(parents=True)

    src_dir = project_dir / "src" / "partially_compliant"
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text('"""Partially compliant package."""\n', encoding="utf-8")
    (src_dir / "main.py").write_text("def run():\n    print('Partial')\n", encoding="utf-8")

    (project_dir / "README.md").write_text(
        "# Partially Compliant Test Project\n\n"
        "A sample project with basic documentation and an MIT license, but missing\n"
        "security policies, contribution guidelines, and containing unpinned workflows.\n",
        encoding="utf-8",
    )
    (project_dir / "LICENSE").write_text(MIT_LICENSE, encoding="utf-8")
    (project_dir / "pyproject.toml").write_text(
        '[project]\nname = "partially-compliant"\nversion = "0.1.0"\n'
        'description = "A partially compliant test project"\n'
        'requires-python = ">=3.10"\n'
        'license = { text = "MIT" }\n',
        encoding="utf-8",
    )

    wf_dir = project_dir / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "ci.yml").write_text(
        "name: CI\n"
        "on: [push, pull_request]\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: actions/setup-python@v5\n"
        "        with:\n"
        '          python-version: "3.11"\n'
        "      - run: python -c \"print('running tests')\"\n",
        encoding="utf-8",
    )

    expected = {
        "project": "partially-compliant",
        "description": "Project with README and LICENSE, but missing security policy, support, and dependabot",
        "expected": {
            "OSPS-LE-03.01": "PASS",
            "OSPS-LE-03.02": "PASS",
            "OSPS-QA-02.01": "PASS",
            "OSPS-QA-05.01": "PASS",
            "OSPS-DO-01.01": ["PENDING", "PASS"],
            "OSPS-GV-01.01": "FAIL",
            "OSPS-VM-02.01": "FAIL",
            "OSPS-VM-05.03": "FAIL",
            "OSPS-GV-04.01": "FAIL",
            "OSPS-SA-03.02": "FAIL",
            "OSPS-DO-03.01": "FAIL",
        },
        "min_failures": 5,
        "max_failures": 10,
        "max_errors": 20,
    }
    (project_dir / "expected_verdicts.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")

    _write_common_files(project_dir, "partially-compliant")
    _init_git_repo(project_dir, "Initial commit for partially-compliant test project")
    logger.info("Created partially-compliant at %s", project_dir)
    return project_dir


def create_passing_reference_project(target_dir: Path) -> Path:
    """Create a fully compliant reference repository satisfying documentation, license, security, and CI."""
    project_dir = target_dir / "passing-reference"
    if project_dir.exists():
        safe_rmtree(project_dir)
    project_dir.mkdir(parents=True)

    src_dir = project_dir / "src" / "passing_reference"
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text('"""Passing reference package."""\n', encoding="utf-8")
    (src_dir / "main.py").write_text("def run():\n    print('Passing reference')\n", encoding="utf-8")

    (project_dir / "README.md").write_text(
        "# Passing Reference Test Project\n\n"
        "A well-structured reference repository meeting OpenSSF baseline requirements.\n\n"
        "## Installation\n\n"
        "```bash\n"
        "pip install passing-reference\n"
        "```\n\n"
        "## Usage\n\n"
        "```python\n"
        "from passing_reference import run\n"
        "run()\n"
        "```\n",
        encoding="utf-8",
    )
    (project_dir / "LICENSE").write_text(MIT_LICENSE, encoding="utf-8")
    (project_dir / "SECURITY.md").write_text(
        "# Security Policy\n\n"
        "## Supported Versions\n\n"
        "| Version | Supported |\n"
        "| ------- | --------- |\n"
        "| 0.1.x   | :white_check_mark: |\n\n"
        "## Reporting a Vulnerability\n\n"
        "Please report vulnerabilities by emailing security@example.com.\n"
        "Do not open public issues for security vulnerabilities.\n",
        encoding="utf-8",
    )
    (project_dir / "CONTRIBUTING.md").write_text(
        "# Contributing Guidelines\n\n"
        "Thank you for considering contributing!\n\n"
        "1. Fork the repository\n"
        "2. Create a feature branch\n"
        "3. Submit a pull request\n",
        encoding="utf-8",
    )
    (project_dir / "GOVERNANCE.md").write_text(
        "# Project Governance\n\n"
        "This project is maintained by the core engineering team. Decisions are made\n"
        "through open consensus on pull requests.\n",
        encoding="utf-8",
    )
    (project_dir / "SUPPORT.md").write_text(
        "# Support Policy\n\nFor help with this project, please open a discussion or email support@example.com.\n",
        encoding="utf-8",
    )
    (project_dir / "THREAT_MODEL.md").write_text(
        "# Threat Model Summary\n\n"
        "This project adheres to basic STRIDE threat modeling principles.\n"
        "Assets: source code, deployment artifacts.\n"
        "Mitigations: branch protection, static analysis, automated testing.\n",
        encoding="utf-8",
    )
    (project_dir / ".gitignore").write_text(
        "__pycache__/\n*.pyc\n.venv/\ndist/\nbuild/\n",
        encoding="utf-8",
    )
    (project_dir / ".editorconfig").write_text(
        "root = true\n\n"
        "[*]\n"
        "indent_style = space\n"
        "indent_size = 4\n"
        "end_of_line = lf\n"
        "charset = utf-8\n"
        "trim_trailing_whitespace = true\n"
        "insert_final_newline = true\n",
        encoding="utf-8",
    )
    (project_dir / "pyproject.toml").write_text(
        '[project]\nname = "passing-reference"\nversion = "0.1.0"\n'
        'description = "A well-structured reference repository meeting OpenSSF baseline requirements"\n'
        'requires-python = ">=3.10"\n'
        'license = { text = "MIT" }\n',
        encoding="utf-8",
    )

    wf_dir = project_dir / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    gh_dir = project_dir / ".github"
    (gh_dir / "CODEOWNERS").write_text("* @core-maintainers\n", encoding="utf-8")
    (gh_dir / "dependabot.yml").write_text(
        "version: 2\n"
        "updates:\n"
        '  - package-ecosystem: "pip"\n'
        '    directory: "/"\n'
        "    schedule:\n"
        '      interval: "weekly"\n',
        encoding="utf-8",
    )
    (wf_dir / "ci.yml").write_text(
        "name: CI\n"
        "on: [push, pull_request]\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v4\n"
        "      - uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v5\n"
        "        with:\n"
        '          python-version: "3.11"\n'
        "      - run: python -c \"print('Automated tests passed')\"\n",
        encoding="utf-8",
    )

    expected = {
        "project": "passing-reference",
        "description": "Compliant repository satisfying baseline documentation, license, security policy, and CI requirements",
        "expected": {
            "OSPS-LE-03.01": "PASS",
            "OSPS-LE-03.02": "PASS",
            "OSPS-QA-02.01": "PASS",
            "OSPS-QA-05.01": "PASS",
            "OSPS-QA-05.02": "PASS",
            "OSPS-DO-01.01": ["PENDING", "PASS"],
            "OSPS-DO-06.01": ["PENDING", "PASS"],
            "OSPS-GV-01.01": ["PENDING", "PASS"],
            "OSPS-SA-03.01": ["PENDING", "PASS"],
            "OSPS-GV-04.01": ["PENDING", "PASS"],
            "OSPS-VM-05.03": ["WARN", "PASS"],
        },
        "max_failures": 0,
        "max_errors": 20,
    }
    (project_dir / "expected_verdicts.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")

    _write_common_files(project_dir, "passing-reference")
    _init_git_repo(project_dir, "Initial commit for passing-reference test project")
    logger.info("Created passing-reference at %s", project_dir)
    return project_dir


def setup_all_projects(target_dir: Path) -> dict[str, Path]:
    """Create all 3 dedicated test projects."""
    target_dir.mkdir(parents=True, exist_ok=True)
    return {
        "failing-empty": create_failing_empty_project(target_dir),
        "partially-compliant": create_partially_compliant_project(target_dir),
        "passing-reference": create_passing_reference_project(target_dir),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DEST,
        help=f"Destination directory (default: {DEFAULT_DEST})",
    )
    parser.add_argument("--clean", action="store_true", help="Clean destination directory before creating")
    parser.add_argument(
        "--projects",
        choices=["all", "failing", "partial", "passing"],
        default="all",
        help="Which projects to generate (default: all)",
    )
    args = parser.parse_args()

    dest = args.dest.resolve()
    if args.clean and dest.exists():
        logger.info("Cleaning destination directory: %s", dest)
        safe_rmtree(dest)

    dest.mkdir(parents=True, exist_ok=True)
    if args.projects == "all":
        setup_all_projects(dest)
    elif args.projects == "failing":
        create_failing_empty_project(dest)
    elif args.projects == "partial":
        create_partially_compliant_project(dest)
    elif args.projects == "passing":
        create_passing_reference_project(dest)

    logger.info("\n=== Dev Test Projects Ready ===")
    logger.info("Location: %s", dest)
    logger.info("Projects created: %s", ", ".join(p.name for p in dest.iterdir() if p.is_dir()))


if __name__ == "__main__":
    main()
