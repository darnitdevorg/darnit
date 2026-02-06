#!/usr/bin/env python3
"""Create a test repository for the darnit-example Project Hygiene Standard.

Generates a minimal Python project that intentionally fails all 8 PH controls,
with a .mcp.json pointing at the example-hygiene MCP server so Claude Code
can audit and remediate it immediately.

Usage:
    # Create a failing repo in /tmp (default):
    python scripts/create-example-test-repo.py --no-github

    # Apply quick fixes to make all controls pass:
    python scripts/create-example-test-repo.py --remediate /tmp/hygiene-test-repo

What's intentionally missing (maps to controls):
    README.md           → PH-DOC-01, PH-DOC-03
    LICENSE             → PH-DOC-02
    SECURITY.md         → PH-SEC-01
    .gitignore          → PH-CFG-01
    .editorconfig       → PH-CFG-02
    CONTRIBUTING.md     → PH-QA-01
    .github/workflows/  → PH-CI-01
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# Resolve darnit workspace root (parent of scripts/)
DARNIT_ROOT = Path(__file__).resolve().parent.parent


def create_repo(
    repo_name: str,
    parent_dir: str | None = None,
    create_github: bool = True,
    github_org: str | None = None,
    make_template: bool = False,
) -> None:
    """Create a minimal test repo that fails all PH controls."""
    if parent_dir is None:
        # Create a unique temp directory so repeated runs don't collide
        parent_dir = tempfile.mkdtemp(prefix="darnit-example-")

    parent_path = Path(parent_dir).resolve()
    repo_path = parent_path / repo_name

    if repo_path.exists():
        print(f"\033[0;31mError: Directory '{repo_path}' already exists.\033[0m")
        sys.exit(1)

    print("\033[0;32m=== Project Hygiene Test Repo Generator ===\033[0m\n")
    print(f"Creating: {repo_path}\n")

    # -- Directory structure --------------------------------------------------
    (repo_path / "src").mkdir(parents=True)

    # -- pyproject.toml (minimal, no license field) ---------------------------
    pyproject = """\
[project]
name = "hygiene-test"
version = "0.0.1"
requires-python = ">=3.10"
"""
    (repo_path / "pyproject.toml").write_text(pyproject)

    # -- src/main.py ----------------------------------------------------------
    main_py = """\
def main():
    print("Hello from hygiene-test!")
    print("This repo intentionally has no hygiene files.")
    print("Run the example_hygiene_check MCP tool to see what is missing.")


if __name__ == "__main__":
    main()
"""
    (repo_path / "src" / "main.py").write_text(main_py)

    # -- .mcp.json (points back to darnit workspace) -------------------------
    mcp_config = {
        "mcpServers": {
            "example-hygiene": {
                "command": "uv",
                "args": [
                    "--directory",
                    str(DARNIT_ROOT),
                    "run",
                    "darnit",
                    "serve",
                    "--framework",
                    "example-hygiene",
                ],
            }
        }
    }
    (repo_path / ".mcp.json").write_text(json.dumps(mcp_config, indent=2) + "\n")

    # -- CLAUDE.md (instructions for Claude Code) -----------------------------
    claude_md = """\
# Hygiene Test Repo

This repo intentionally fails all Project Hygiene Standard controls.

Use the `example_hygiene_check` MCP tool to audit this repository,
then fix each failing control.

## Quick start

1. Run the audit: ask Claude to check this repo's hygiene
2. Review the 8 failing controls
3. Fix them one by one (Claude can help create the missing files)

## What's missing

| Control | What to create |
|---------|---------------|
| PH-DOC-01 | README.md |
| PH-DOC-02 | LICENSE |
| PH-DOC-03 | README.md with a description section |
| PH-SEC-01 | SECURITY.md |
| PH-CFG-01 | .gitignore |
| PH-CFG-02 | .editorconfig |
| PH-QA-01 | CONTRIBUTING.md |
| PH-CI-01 | .github/workflows/*.yml |
"""
    (repo_path / "CLAUDE.md").write_text(claude_md)

    # -- Initialize git -------------------------------------------------------
    try:
        subprocess.run(
            ["git", "init"], cwd=repo_path, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "add", "."], cwd=repo_path, capture_output=True, check=True
        )
        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                "Initial commit - intentionally non-compliant\n\n"
                "This repository is designed for testing Project Hygiene Standard\n"
                "compliance. It intentionally fails all 8 PH controls.",
            ],
            cwd=repo_path,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if e.stderr else str(e)
        print(f"\033[0;31mGit error: {stderr}\033[0m")
        sys.exit(1)

    print("\033[0;32m✓ Local repository created\033[0m")

    # -- Optional GitHub repo -------------------------------------------------
    if create_github:
        _create_github_repo(repo_path, repo_name, github_org, make_template)

    # -- Summary --------------------------------------------------------------
    print(f"""
\033[0;32m=== Repository Created ===\033[0m

  Location: {repo_path}

\033[1;33mWhat's intentionally MISSING (for testing):\033[0m
  ✗ README.md          (PH-DOC-01, PH-DOC-03)
  ✗ LICENSE            (PH-DOC-02)
  ✗ SECURITY.md        (PH-SEC-01)
  ✗ .gitignore         (PH-CFG-01)
  ✗ .editorconfig      (PH-CFG-02)
  ✗ CONTRIBUTING.md    (PH-QA-01)
  ✗ CI workflows       (PH-CI-01)

\033[0;32mNext steps:\033[0m
  1. cd {repo_path}
  2. Open in Claude Code
  3. Ask Claude to run the hygiene audit and fix failures

\033[0;36mOr apply quick fixes:\033[0m
  python scripts/create-example-test-repo.py --remediate {repo_path}
""")


def remediate_repo(repo_path_str: str) -> None:
    """Apply minimal fixes to make all 8 PH controls pass."""
    repo_path = Path(repo_path_str).resolve()
    if not repo_path.exists():
        print(f"\033[0;31mError: '{repo_path}' does not exist.\033[0m")
        sys.exit(1)

    print("\033[0;32m=== Applying Quick Remediations ===\033[0m\n")
    print(f"Target: {repo_path}\n")

    created: list[str] = []

    # PH-DOC-01 + PH-DOC-03: README with description (body must be >20 chars)
    readme = repo_path / "README.md"
    if not readme.exists():
        readme.write_text(
            "# hygiene-test-repo\n\n"
            "A test project for the Project Hygiene Standard demo.\n"
        )
        created.append("README.md")

    # PH-DOC-02: LICENSE
    license_file = repo_path / "LICENSE"
    if not license_file.exists():
        license_file.write_text("MIT License - test project for demo purposes.\n")
        created.append("LICENSE")

    # PH-SEC-01: SECURITY.md
    security = repo_path / "SECURITY.md"
    if not security.exists():
        security.write_text(
            "# Security Policy\n\nTo report a vulnerability, open an issue.\n"
        )
        created.append("SECURITY.md")

    # PH-CFG-01: .gitignore
    gitignore = repo_path / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*.pyc\n__pycache__/\n")
        created.append(".gitignore")

    # PH-CFG-02: .editorconfig
    editorconfig = repo_path / ".editorconfig"
    if not editorconfig.exists():
        editorconfig.write_text(
            "root = true\n\n[*]\nindent_style = space\nindent_size = 4\n"
        )
        created.append(".editorconfig")

    # PH-QA-01: CONTRIBUTING.md
    contributing = repo_path / "CONTRIBUTING.md"
    if not contributing.exists():
        contributing.write_text("# Contributing\n\nOpen a pull request.\n")
        created.append("CONTRIBUTING.md")

    # PH-CI-01: CI config
    workflows_dir = repo_path / ".github" / "workflows"
    ci_file = workflows_dir / "ci.yml"
    if not ci_file.exists():
        workflows_dir.mkdir(parents=True, exist_ok=True)
        ci_file.write_text(
            "name: CI\n"
            "on: [push, pull_request]\n"
            "jobs:\n"
            "  check:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
        )
        created.append(".github/workflows/ci.yml")

    if created:
        print("\033[0;32mCreated files:\033[0m")
        for f in created:
            print(f"  ✓ {f}")
        print(f"\n\033[0;32mDone! {len(created)} files created.\033[0m")
        print("Re-run the audit to verify all controls pass.")
    else:
        print("\033[1;33mAll files already exist — nothing to do.\033[0m")


def _create_github_repo(
    repo_path: Path,
    repo_name: str,
    github_org: str | None,
    make_template: bool,
) -> None:
    """Create a GitHub repository using the gh CLI."""
    try:
        result = subprocess.run(
            ["gh", "auth", "status"], capture_output=True
        )
        if result.returncode != 0:
            print(
                "\033[1;33m⚠ GitHub CLI not authenticated. "
                "Skipping GitHub repo creation.\033[0m"
            )
            return
    except FileNotFoundError:
        print(
            "\033[1;33m⚠ GitHub CLI (gh) not found. "
            "Skipping GitHub repo creation.\033[0m"
        )
        return

    if not github_org:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True,
            text=True,
        )
        github_org = result.stdout.strip()
        print(f"\033[1;33mUsing GitHub user: {github_org}\033[0m")

    print(f"\033[0;32mCreating GitHub repository: {github_org}/{repo_name}\033[0m")

    try:
        subprocess.run(
            [
                "gh",
                "repo",
                "create",
                f"{github_org}/{repo_name}",
                "--public",
                "--source",
                str(repo_path),
                "--remote",
                "origin",
                "--description",
                "Project Hygiene test repo - intentionally non-compliant",
                "--push",
            ],
            capture_output=True,
            check=True,
        )
        print("\033[0;32m✓ GitHub repository created\033[0m")

        if make_template:
            subprocess.run(
                [
                    "gh",
                    "api",
                    "--method",
                    "PATCH",
                    "-H",
                    "Accept: application/vnd.github+json",
                    f"/repos/{github_org}/{repo_name}",
                    "-f",
                    "is_template=true",
                ],
                capture_output=True,
                check=True,
            )
            print("\033[0;32m✓ Repository is now a template\033[0m")

    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if e.stderr else str(e)
        print(f"\033[1;33m⚠ GitHub error: {stderr}\033[0m")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a test repo for the Project Hygiene Standard",
    )
    parser.add_argument(
        "repo_name",
        nargs="?",
        default="hygiene-test-repo",
        help="Name of the repository (default: hygiene-test-repo)",
    )
    parser.add_argument(
        "--parent-dir",
        default=None,
        help=f"Directory to create the repo in (default: {tempfile.gettempdir()})",
    )
    parser.add_argument(
        "--no-github",
        action="store_true",
        help="Skip GitHub repository creation",
    )
    parser.add_argument(
        "--github-org",
        default=None,
        help="GitHub org or username (default: authenticated user)",
    )
    parser.add_argument(
        "--template",
        action="store_true",
        help="Make the GitHub repo a template",
    )
    parser.add_argument(
        "--remediate",
        metavar="PATH",
        default=None,
        help="Apply quick fixes to an existing test repo instead of creating a new one",
    )

    args = parser.parse_args()

    if args.remediate:
        remediate_repo(args.remediate)
    else:
        create_repo(
            repo_name=args.repo_name,
            parent_dir=args.parent_dir,
            create_github=not args.no_github,
            github_org=args.github_org,
            make_template=args.template,
        )


if __name__ == "__main__":
    main()
