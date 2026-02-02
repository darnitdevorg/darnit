"""Test repository creation tool for OpenSSF Baseline testing.

Creates a minimal test repository that intentionally fails all OpenSSF Baseline
controls, useful for testing and learning.
"""

import os
import subprocess

from darnit.core.utils import validate_local_path


def create_test_repository_impl(
    repo_name: str = "baseline-test-repo",
    parent_dir: str = ".",
    github_org: str | None = None,
    create_github: bool = True,
    make_template: bool = False
) -> str:
    """Create a minimal test repository that intentionally fails all controls.

    Args:
        repo_name: Name of the repository
        parent_dir: Directory to create the repo in
        github_org: GitHub org/username (auto-detected if not provided)
        create_github: Whether to create a GitHub repo (requires gh CLI)
        make_template: Whether to make it a GitHub template repository

    Returns:
        Success message with next steps
    """
    parent_path, error = validate_local_path(parent_dir)
    if error:
        return f"❌ Error: {error}"

    repo_path = os.path.join(parent_path, repo_name)

    # Check if already exists
    if os.path.exists(repo_path):
        return f"❌ Error: Directory '{repo_path}' already exists"

    # Create directory structure
    os.makedirs(os.path.join(repo_path, "src"))

    # Create package.json (minimal - no license, no description)
    package_json = """{
  "name": "baseline-test",
  "version": "0.0.1",
  "main": "src/index.js",
  "scripts": {
    "start": "node src/index.js"
  },
  "dependencies": {
    "chalk": "^4.1.2"
  }
}
"""
    with open(os.path.join(repo_path, "package.json"), "w") as f:
        f.write(package_json)

    # Create src/index.js
    index_js = """const chalk = require('chalk');

console.log(chalk.green('Hello from baseline-test!'));
console.log(chalk.yellow('This repo intentionally has no security controls.'));
console.log('');
console.log('Run an OpenSSF Baseline audit to see what is missing:');
console.log(chalk.cyan('  audit_openssf_baseline(local_path=".")'));
"""
    with open(os.path.join(repo_path, "src", "index.js"), "w") as f:
        f.write(index_js)

    # Create minimal .gitignore (intentionally missing security exclusions)
    gitignore = """# Intentionally minimal .gitignore for testing
# This is MISSING important security exclusions!
node_modules/
"""
    with open(os.path.join(repo_path, ".gitignore"), "w") as f:
        f.write(gitignore)

    # Initialize git
    try:
        subprocess.run(
            ["git", "init"],
            cwd=repo_path,
            capture_output=True,
            check=True
        )
        subprocess.run(
            ["git", "add", "."],
            cwd=repo_path,
            capture_output=True,
            check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "Initial commit - intentionally non-compliant"],
            cwd=repo_path,
            capture_output=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        return f"❌ Git error: {e.stderr.decode() if e.stderr else str(e)}"

    output_lines = [
        f"✅ Created test repository: {repo_path}",
        "",
        "**What's intentionally MISSING (for testing):**",
        "- ✗ LICENSE file",
        "- ✗ README.md",
        "- ✗ SECURITY.md",
        "- ✗ CONTRIBUTING.md",
        "- ✗ CI/CD workflows",
        "- ✗ Branch protection",
        "- ✗ Package lockfile",
        "- ✗ ...and 50+ more controls",
        "",
    ]

    # Create GitHub repo if requested
    if create_github:
        try:
            # Check if gh is available
            gh_check = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True
            )
            if gh_check.returncode != 0:
                output_lines.append("⚠️ GitHub CLI not authenticated. Skipping GitHub repo creation.")
                output_lines.append("   Run: gh auth login")
            else:
                # Get org if not specified
                if not github_org:
                    result = subprocess.run(
                        ["gh", "api", "user", "--jq", ".login"],
                        capture_output=True,
                        text=True
                    )
                    github_org = result.stdout.strip()

                # Create GitHub repo
                subprocess.run(
                    [
                        "gh", "repo", "create", f"{github_org}/{repo_name}",
                        "--public",
                        "--source", repo_path,
                        "--remote", "origin",
                        "--description", "OpenSSF Baseline test repo - intentionally non-compliant",
                        "--push"
                    ],
                    capture_output=True,
                    check=True
                )
                output_lines.append(f"✅ GitHub repo created: https://github.com/{github_org}/{repo_name}")

                # Make template if requested
                if make_template:
                    subprocess.run(
                        [
                            "gh", "api",
                            "--method", "PATCH",
                            "-H", "Accept: application/vnd.github+json",
                            f"/repos/{github_org}/{repo_name}",
                            "-f", "is_template=true"
                        ],
                        capture_output=True,
                        check=True
                    )
                    output_lines.append("✅ Repository is now a template")
                    output_lines.append("")
                    output_lines.append("**To use the template:**")
                    output_lines.append(f"  gh repo create my-test --template {github_org}/{repo_name}")

        except FileNotFoundError:
            output_lines.append("⚠️ GitHub CLI (gh) not found. Skipping GitHub repo creation.")
        except subprocess.CalledProcessError as e:
            output_lines.append(f"⚠️ GitHub error: {e.stderr.decode() if e.stderr else str(e)}")

    output_lines.extend([
        "",
        "**Next steps:**",
        f"1. cd {repo_path}",
        "2. npm install",
        "3. Run: audit_openssf_baseline(local_path='.', level=3)",
        "4. Start implementing fixes to reach 100% compliance!",
    ])

    return "\n".join(output_lines)
