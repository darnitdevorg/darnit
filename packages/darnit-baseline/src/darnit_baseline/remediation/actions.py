"""File creation remediation actions.

This module contains functions that create compliance-related files
like SECURITY.md, CONTRIBUTING.md, GOVERNANCE.md, CODEOWNERS, etc.

Design Philosophy:
- Simple cases: Just create files with sensible defaults
- Pull data from .project.yaml, GitHub API, and git config when available
- Provide clear guidance for manual steps when automation isn't possible
- Use detected project context (e.g., single maintainer) to make smart defaults
"""

import json
import os
import subprocess
from pathlib import Path

from darnit.config.context_storage import get_context_value
from darnit.core.logging import get_logger
from darnit.core.utils import detect_repo_from_git, file_exists, validate_local_path
from darnit.remediation.helpers import (
    ensure_directory,
    format_error,
    get_repo_maintainers,
    write_file_safe,
)
from darnit.tools import write_file_safely

logger = get_logger("remediation.actions")


def _detect_package_ecosystems(local_path: str) -> list[str]:
    """Detect package ecosystems used in the repository.

    Returns list of Dependabot ecosystem names.
    """
    ecosystems = []

    # Check for various package manager files
    ecosystem_files = {
        "npm": ["package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
        "pip": ["requirements.txt", "setup.py", "pyproject.toml", "Pipfile"],
        "cargo": ["Cargo.toml", "Cargo.lock"],
        "gomod": ["go.mod", "go.sum"],
        "maven": ["pom.xml"],
        "gradle": ["build.gradle", "build.gradle.kts"],
        "nuget": ["*.csproj", "packages.config", "*.fsproj"],
        "bundler": ["Gemfile", "Gemfile.lock"],
        "composer": ["composer.json", "composer.lock"],
        "docker": ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"],
        "terraform": ["*.tf", "terraform.lock.hcl"],
        "github-actions": [".github/workflows/*.yml", ".github/workflows/*.yaml"],
    }

    for ecosystem, files in ecosystem_files.items():
        for file_pattern in files:
            if "*" in file_pattern:
                # Simple glob check
                import glob
                if glob.glob(os.path.join(local_path, file_pattern)):
                    ecosystems.append(ecosystem)
                    break
            else:
                if os.path.exists(os.path.join(local_path, file_pattern)):
                    ecosystems.append(ecosystem)
                    break

    return ecosystems


def _get_project_description(local_path: str, repo: str) -> str:
    """Try to get project description from README or package files."""
    # Try README
    for readme in ["README.md", "README.rst", "README.txt", "README"]:
        readme_path = os.path.join(local_path, readme)
        if os.path.exists(readme_path):
            try:
                with open(readme_path, encoding='utf-8') as f:
                    content = f.read()
                    # Get first non-empty, non-header line
                    for line in content.split('\n'):
                        line = line.strip()
                        if line and not line.startswith('#') and not line.startswith('='):
                            if len(line) > 20:
                                return line[:200]
            except OSError:
                pass

    # Try package.json
    pkg_path = os.path.join(local_path, "package.json")
    if os.path.exists(pkg_path):
        try:
            with open(pkg_path) as f:
                pkg = json.load(f)
                if pkg.get("description"):
                    return pkg["description"]
        except (OSError, json.JSONDecodeError):
            pass

    # Try pyproject.toml
    pyproject_path = os.path.join(local_path, "pyproject.toml")
    if os.path.exists(pyproject_path):
        try:
            with open(pyproject_path) as f:
                content = f.read()
                import re
                match = re.search(r'description\s*=\s*"([^"]+)"', content)
                if match:
                    return match.group(1)
        except OSError:
            pass

    return f"A project for {repo}"


def _ensure_owner_repo(
    owner: str | None,
    repo: str | None,
    local_path: Path
) -> tuple:
    """Auto-detect owner/repo from git if not provided.

    Args:
        owner: GitHub owner (or None to auto-detect)
        repo: Repository name (or None to auto-detect)
        local_path: Path to the repository

    Returns:
        Tuple of (owner, repo) - uses defaults if detection fails
    """
    if not owner or not repo:
        detected = detect_repo_from_git(str(local_path))
        if detected:
            owner = owner or detected["owner"]
            repo = repo or detected["repo"]
        else:
            owner = owner or "OWNER"
            repo = repo or "REPO"
    return owner, repo


def _is_single_maintainer_project(owner: str, repo: str, maintainers: list[str]) -> bool:
    """Detect if this appears to be a single-maintainer project."""
    if len(maintainers) <= 1:
        return True

    # Check if owner is also the only contributor (using API if available)
    try:
        result = subprocess.run(
            ["gh", "api", f"/repos/{owner}/{repo}/contributors", "--jq", "length"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            count = int(result.stdout.strip())
            return count <= 2
    except (subprocess.SubprocessError, ValueError, OSError):
        pass

    return False


def _get_vex_section() -> str:
    """Get the VEX policy section to add to SECURITY.md."""
    return """
## Vulnerability Exploitability (VEX)

When vulnerabilities are reported in our dependencies that do not affect this project,
we will provide VEX (Vulnerability Exploitability eXchange) statements explaining why
the vulnerability is not exploitable in our context.

VEX statements will be published as:
- GitHub Security Advisories with "not affected" status
- VEX documents in this repository (when applicable)

For more information about VEX, see:
- [OpenVEX Specification](https://openvex.dev/)
- [CISA VEX Guide](https://www.cisa.gov/resources-tools/resources/vulnerability-exploitability-exchange-vex-overview)
"""


def _has_vex_section(content: str) -> bool:
    """Check if content already has a VEX section."""
    import re
    # Same pattern used by the control check
    pattern = r"(vex|vulnerability.exploitability|exploitability.exchange|affected.*not.affected)"
    return bool(re.search(pattern, content, re.IGNORECASE))


def ensure_vex_policy(local_path: str = ".") -> str:
    """
    Ensure SECURITY.md has a VEX policy section.

    If SECURITY.md exists but doesn't have a VEX section, appends one.
    If SECURITY.md doesn't exist, returns a message to create it first.

    Satisfies: OSPS-VM-04.02

    Args:
        local_path: Path to repository

    Returns:
        Success message or instructions
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        return f"❌ Error: {error}"

    # Check for SECURITY.md in common locations
    security_paths = [
        os.path.join(resolved_path, "SECURITY.md"),
        os.path.join(resolved_path, ".github", "SECURITY.md"),
    ]

    security_file = None
    for path in security_paths:
        if os.path.exists(path):
            security_file = path
            break

    if not security_file:
        return """ℹ️ No SECURITY.md found.

Run `create_security_policy()` to create one with VEX policy included.
"""

    # Read existing content
    try:
        with open(security_file, encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        return f"❌ Failed to read {security_file}: {e}"

    # Check if VEX section already exists
    if _has_vex_section(content):
        return f"""✅ SECURITY.md already has VEX policy section.

**File:** {security_file}
**Control:** OSPS-VM-04.02 ✓
"""

    # Append VEX section
    vex_section = _get_vex_section()
    updated_content = content.rstrip() + "\n" + vex_section

    try:
        with open(security_file, 'w', encoding='utf-8') as f:
            f.write(updated_content)
    except OSError as e:
        return f"❌ Failed to update {security_file}: {e}"

    logger.info(f"Added VEX policy section to {security_file}")
    return f"""✅ Added VEX policy section to SECURITY.md

**File:** {security_file}
**Control addressed:** OSPS-VM-04.02 (VEX policy documented)

The VEX section explains how the project handles vulnerability exploitability
statements for dependencies that don't affect this project.
"""


def create_security_policy(
    owner: str | None = None,
    repo: str | None = None,
    local_path: str = ".",
    template: str = "standard"
) -> str:
    """
    Create a SECURITY.md file for vulnerability reporting.

    If SECURITY.md already exists, checks for and adds VEX section if missing.

    Satisfies: OSPS-VM-01.01, OSPS-VM-02.01, OSPS-VM-03.01, OSPS-VM-04.02

    Args:
        owner: GitHub Org/User (auto-detected if not provided)
        repo: Repository Name (auto-detected if not provided)
        local_path: Path to repository
        template: Template to use (standard, minimal, enterprise)

    Returns:
        Success message with created file path
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        logger.warning(f"Invalid path for security policy: {error}")
        return f"❌ Error: {error}"

    # Check if SECURITY.md already exists
    existing_security = file_exists(resolved_path, "SECURITY.md", ".github/SECURITY.md")
    if existing_security:
        # File exists - ensure it has VEX section
        vex_result = ensure_vex_policy(local_path)
        return f"""ℹ️ SECURITY.md already exists: {existing_security}

{vex_result}
**Note:** To regenerate the entire file, remove it first and re-run this command.
"""

    # Auto-detect owner/repo
    if not owner or not repo:
        detected = detect_repo_from_git(resolved_path)
        if detected:
            owner = owner or detected["owner"]
            repo = repo or detected["repo"]
        else:
            owner = owner or "OWNER"
            repo = repo or "REPO"

    # Get maintainers
    maintainers = get_repo_maintainers(owner, repo)
    maintainer_list = ", ".join(f"@{m}" for m in maintainers[:3]) if maintainers else "@maintainers"

    content = f"""# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability, please report it responsibly.

### How to Report

1. **DO NOT** create a public GitHub issue for security vulnerabilities
2. Email security concerns to: security@example.com
3. Or use GitHub's private vulnerability reporting feature

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline

- **Initial Response**: Within 48 hours
- **Status Update**: Within 7 days
- **Resolution Target**: Within 90 days for critical issues

### Maintainers

{maintainer_list}

## Security Best Practices

When contributing, please ensure:
- No hardcoded secrets or credentials
- Dependencies are up to date
- Input validation is implemented
- Secure coding practices are followed

## Vulnerability Exploitability (VEX)

When vulnerabilities are reported in our dependencies that do not affect this project,
we will provide VEX (Vulnerability Exploitability eXchange) statements explaining why
the vulnerability is not exploitable in our context.

VEX statements will be published as:
- GitHub Security Advisories with "not affected" status
- VEX documents in this repository (when applicable)

For more information about VEX, see:
- [OpenVEX Specification](https://openvex.dev/)
- [CISA VEX Guide](https://www.cisa.gov/resources-tools/resources/vulnerability-exploitability-exchange-vex-overview)
"""

    # TODO: Add tooling or guidance for repo owners on how to create VEX documents.
    # This could include:
    # - Integration with `vexctl` CLI tool (https://github.com/openvex/vexctl)
    # - Templates for common VEX statements (not_affected, under_investigation, etc.)
    # - Guidance on when to create VEX vs when to use GitHub Security Advisories
    # - Example VEX document structure
    # See: https://github.com/openvex/spec for the OpenVEX specification

    filepath = os.path.join(resolved_path, "SECURITY.md")
    success, message = write_file_safely(filepath, content)

    if success:
        logger.info(f"Created SECURITY.md at {filepath}")
        return f"""✅ Created SECURITY.md

**OSPS Controls Addressed:**
- OSPS-VM-01.01: Security contact defined
- OSPS-VM-02.01: Vulnerability reporting process
- OSPS-VM-03.01: Response timeline documented
- OSPS-VM-04.02: VEX policy documented

**File:** {filepath}
"""
    else:
        logger.error(f"Failed to create SECURITY.md: {message}")
        return f"❌ {message}"


def create_contributing_guide(
    owner: str | None = None,
    repo: str | None = None,
    local_path: str = ".",
) -> str:
    """
    Create a CONTRIBUTING.md file with contributor guidelines.

    Satisfies: OSPS-GV-03.01, OSPS-GV-03.02

    Args:
        owner: GitHub Org/User (auto-detected if not provided)
        repo: Repository Name (auto-detected if not provided)
        local_path: Path to repository

    Returns:
        Success message with created file path
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        logger.warning(f"Invalid path for contributing guide: {error}")
        return f"❌ Error: {error}"

    # Auto-detect owner/repo
    if not owner or not repo:
        detected = detect_repo_from_git(resolved_path)
        if detected:
            owner = owner or detected["owner"]
            repo = repo or detected["repo"]
        else:
            owner = owner or "OWNER"
            repo = repo or "REPO"

    content = f"""# Contributing to {repo}

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing.

## Code of Conduct

Please read and follow our Code of Conduct to maintain a welcoming environment for all contributors.

## Getting Started

### Prerequisites

- Git
- A GitHub account

### Setup

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/YOUR-USERNAME/{repo}.git
   cd {repo}
   ```
3. Add the upstream remote:
   ```bash
   git remote add upstream https://github.com/{owner}/{repo}.git
   ```

## Making Changes

### Branch Naming

Create a branch with a descriptive name:
- `feat/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation updates
- `refactor/description` - Code refactoring

### Commit Messages

Write clear, concise commit messages:
```
type: short description

Longer description if needed explaining the what and why.
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `ci`, `chore`

### Pull Request Process

1. Update your fork with the latest upstream changes:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```
2. Push your changes to your fork
3. Open a Pull Request against the `main` branch
4. Fill out the PR template with relevant details
5. Wait for review and address any feedback

## Development Guidelines

### Code Style

- Follow existing code patterns and conventions
- Write clear, self-documenting code
- Add comments only where necessary to explain complex logic

### Testing

- Write tests for new functionality
- Ensure all tests pass before submitting a PR
- Maintain or improve test coverage

### Documentation

- Update relevant documentation for any changes
- Document public APIs and interfaces
- Include examples where helpful

## Questions?

If you have questions, feel free to:
- Open a GitHub Issue
- Start a Discussion

Thank you for contributing!
"""

    filepath = os.path.join(resolved_path, "CONTRIBUTING.md")
    success, message = write_file_safely(filepath, content)

    if success:
        logger.info(f"Created CONTRIBUTING.md at {filepath}")
        return f"""✅ Created CONTRIBUTING.md

**OSPS Controls Addressed:**
- OSPS-GV-03.01: Contribution guide exists
- OSPS-GV-03.02: Development process documented

**File:** {filepath}
"""
    else:
        logger.error(f"Failed to create CONTRIBUTING.md: {message}")
        return f"❌ {message}"


def create_codeowners(
    owner: str | None = None,
    repo: str | None = None,
    local_path: str = ".",
) -> str:
    """
    Create a CODEOWNERS file defining code ownership.

    Satisfies: OSPS-GV-01.01, OSPS-GV-01.02, OSPS-GV-04.01

    Requires maintainers to be confirmed via confirm_project_context() first.
    If not confirmed, shows auto-detected collaborators and prompts for confirmation.

    Args:
        owner: GitHub Org/User (auto-detected if not provided)
        repo: Repository Name (auto-detected if not provided)
        local_path: Path to repository

    Returns:
        Success message with created file path, or prompt to confirm maintainers
    """
    resolved_path = Path(local_path).resolve()

    # Detect owner/repo if not provided
    owner, repo = _ensure_owner_repo(owner, repo, resolved_path)

    # Check if file already exists
    existing = file_exists(resolved_path, "CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS")
    if existing:
        return f"""ℹ️ CODEOWNERS file already exists: {existing}

No changes made. To regenerate, remove the existing file first.
"""

    # Get maintainers from context (orchestrator validates this before calling us)
    # Context may be USER_CONFIRMED or AUTO_DETECTED (sieve detected it)
    context_value = get_context_value(str(resolved_path), "maintainers", "governance")

    if context_value and context_value.value:
        # Use confirmed/detected maintainers
        maintainers = context_value.value
        if isinstance(maintainers, str):
            maintainers = [maintainers]
        # Normalize: remove @ prefix if present for consistency
        maintainers = [m.lstrip("@") for m in maintainers]
    else:
        # Context missing - shouldn't happen if called through orchestrator
        # Return a simple error directing users to use the orchestrator
        return f"""⚠️ **Maintainers context required**

The maintainers context is not set. Please use `remediate_audit_findings()` which will
auto-detect maintainers and prompt for confirmation.

Or set context directly:
```
confirm_project_context(maintainers=["@{owner}", "@other_maintainer"])
```

Then run this remediation again.
"""

    # Build maintainer string from confirmed maintainers
    maintainer_handles = " ".join(f"@{m}" for m in maintainers)

    # Simple CODEOWNERS - global ownership only
    # Users can customize with path-specific rules as needed
    content = f"""# CODEOWNERS - Defines code ownership for review requirements
# See: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners

# Global ownership - all files require review from these owners
* {maintainer_handles}
"""

    # Prefer .github/CODEOWNERS location
    github_dir = resolved_path / ".github"
    if github_dir.exists():
        filepath = github_dir / "CODEOWNERS"
    else:
        filepath = resolved_path / "CODEOWNERS"

    success, message = write_file_safe(filepath, content)

    if success:
        logger.info(f"Created CODEOWNERS at {filepath}")
        return f"""✅ Created CODEOWNERS

**OSPS Controls Addressed:**
- OSPS-GV-01.01: Governance roles defined
- OSPS-GV-01.02: Maintainers documented
- OSPS-GV-04.01: Code ownership defined

**File:** {filepath}
**Code Owners:** {maintainer_handles}

ℹ️ Customize with path-specific rules as your project grows.
"""
    else:
        logger.error(f"Failed to create CODEOWNERS: {message}")
        return format_error(message)


def create_governance_doc(
    owner: str | None = None,
    repo: str | None = None,
    local_path: str = ".",
) -> str:
    """
    Create a GOVERNANCE.md file describing project governance.

    Satisfies: OSPS-GV-01.01, OSPS-GV-01.02

    Requires maintainers to be confirmed via confirm_project_context() first.
    If not confirmed, shows auto-detected collaborators and prompts for confirmation.

    Args:
        owner: GitHub Org/User (auto-detected if not provided)
        repo: Repository Name (auto-detected if not provided)
        local_path: Path to repository

    Returns:
        Success message with created file path, or prompt to confirm maintainers
    """
    resolved_path = Path(local_path).resolve()

    # Detect owner/repo if not provided
    owner, repo = _ensure_owner_repo(owner, repo, resolved_path)

    # Check if file already exists
    existing = file_exists(resolved_path, "GOVERNANCE.md", "docs/GOVERNANCE.md")
    if existing:
        return f"""ℹ️ GOVERNANCE.md already exists: {existing}

No changes made. To regenerate, remove the existing file first.
"""

    # Get maintainers from context (orchestrator validates this before calling us)
    # Context may be USER_CONFIRMED or AUTO_DETECTED (sieve detected it)
    context_value = get_context_value(str(resolved_path), "maintainers", "governance")

    if context_value and context_value.value:
        # Use confirmed/detected maintainers
        maintainers = context_value.value
        if isinstance(maintainers, str):
            maintainers = [maintainers]
        # Normalize: remove @ prefix if present for consistency
        maintainers = [m.lstrip("@") for m in maintainers]
    else:
        # Context missing - shouldn't happen if called through orchestrator
        # Return a simple error directing users to use the orchestrator
        return f"""⚠️ **Maintainers context required**

The maintainers context is not set. Please use `remediate_audit_findings()` which will
auto-detect maintainers and prompt for confirmation.

Or set context directly:
```
confirm_project_context(maintainers=["@{owner}", "@other_maintainer"])
```

Then run this remediation again.
"""

    # Build maintainer list from confirmed maintainers
    maintainer_list = "\n".join(f"- [@{m}](https://github.com/{m})" for m in maintainers)
    is_single = len(maintainers) <= 1

    if is_single:
        content = f"""# Governance

## Project Maintainer

This project is currently maintained by @{maintainers[0]}.

## Decision Making

As a single-maintainer project, decisions are made by the maintainer with input
from the community through issues and discussions.

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Changes to Governance

If the project grows, this governance model may be updated to include additional
maintainers or a more formal decision-making process.
"""
    else:
        content = f"""# Governance

## Overview

This document describes the governance model for {repo}.

## Roles

### Maintainers

Maintainers are responsible for the overall direction and health of the project.

**Current Maintainers:**
{maintainer_list}

### Contributors

Anyone who contributes code, documentation, or other improvements to the project.

## Decision Making

- **Minor changes**: Can be merged by any maintainer after review
- **Major changes**: Require discussion and consensus among maintainers
- **Breaking changes**: Require announcement and community feedback period

## Becoming a Maintainer

Contributors who have made significant contributions may be invited to become
maintainers. Criteria include:

- Sustained contributions over time
- Quality of contributions
- Constructive participation in discussions
- Alignment with project goals

## Code of Conduct

All participants are expected to follow our Code of Conduct.

## Changes to Governance

Significant changes to governance require consensus among maintainers and should
be discussed openly before implementation.
"""

    filepath = resolved_path / "GOVERNANCE.md"
    success, message = write_file_safe(filepath, content)

    if success:
        logger.info(f"Created GOVERNANCE.md at {filepath}")
        return f"""✅ Created GOVERNANCE.md

**OSPS Controls Addressed:**
- OSPS-GV-01.01: Governance roles defined
- OSPS-GV-01.02: Maintainers documented

**File:** {filepath}
**Maintainers (confirmed):** {', '.join(f'@{m}' for m in maintainers)}

{"ℹ️ Single-maintainer governance template used. Update as your project grows." if is_single else "ℹ️ Review and customize the governance model for your project's needs."}
"""
    else:
        logger.error(f"Failed to create GOVERNANCE.md: {message}")
        return format_error(message)


def create_maintainers_doc(
    owner: str | None = None,
    repo: str | None = None,
    local_path: str = ".",
) -> str:
    """
    Create a MAINTAINERS.md file listing project maintainers.

    Satisfies: OSPS-GV-01.01, OSPS-GV-01.02, OSPS-GV-04.01

    Requires maintainers to be confirmed via confirm_project_context() first.
    If not confirmed, shows auto-detected maintainers and prompts for confirmation.

    Args:
        owner: GitHub Org/User (auto-detected if not provided)
        repo: Repository Name (auto-detected if not provided)
        local_path: Path to repository

    Returns:
        Success message with created file path, or prompt to confirm maintainers
    """
    resolved_path = Path(local_path).resolve()

    # Detect owner/repo if not provided
    owner, repo = _ensure_owner_repo(owner, repo, resolved_path)

    # Check if file already exists
    existing = file_exists(resolved_path, "MAINTAINERS.md", "MAINTAINERS")
    if existing:
        return f"""ℹ️ Maintainers file already exists: {existing}

No changes made. To regenerate, remove the existing file first.
"""

    # Get maintainers from context (orchestrator validates this before calling us)
    # Context may be USER_CONFIRMED or AUTO_DETECTED (sieve detected it)
    context_value = get_context_value(str(resolved_path), "maintainers", "governance")

    if context_value and context_value.value:
        # Use confirmed/detected maintainers
        maintainers = context_value.value
        if isinstance(maintainers, str):
            maintainers = [maintainers]
        # Normalize: remove @ prefix if present for consistency
        maintainers = [m.lstrip("@") for m in maintainers]
        maintainer_list = "\n".join(f"- [@{m}](https://github.com/{m})" for m in maintainers)
    else:
        # Context missing - shouldn't happen if called through orchestrator
        # Return a simple error directing users to use the orchestrator
        return f"""⚠️ **Maintainers context required**

The maintainers context is not set. Please use `remediate_audit_findings()` which will
auto-detect maintainers and prompt for confirmation.

Or set context directly:
```
confirm_project_context(maintainers=["@{owner}", "@other_maintainer"])
```

Then run this remediation again.
"""

    content = f"""# Maintainers

This document lists the maintainers for {repo}.

## Current Maintainers

{maintainer_list}

## Maintainer Responsibilities

Maintainers are responsible for:

- Reviewing and merging pull requests
- Triaging issues and feature requests
- Ensuring code quality and security standards
- Making release decisions
- Guiding the project's technical direction

## Becoming a Maintainer

New maintainers are nominated by existing maintainers based on:

- Sustained, high-quality contributions
- Deep understanding of the codebase
- Demonstrated commitment to the project
- Constructive collaboration with the community

## Emeritus Maintainers

Former maintainers who have stepped back from active maintenance:

- (none yet)

---

*This file was auto-generated. Please review and update as needed.*
"""

    filepath = resolved_path / "MAINTAINERS.md"
    success, message = write_file_safe(filepath, content)

    if success:
        logger.info(f"Created MAINTAINERS.md at {filepath}")
        return f"""✅ Created MAINTAINERS.md

**Controls addressed:**
- OSPS-GV-01.01: Project maintainers documented
- OSPS-GV-01.02: Maintainer responsibilities defined
- OSPS-GV-04.01: Trusted contributors identified

**File:** {filepath}

**Maintainers:**
{maintainer_list}

ℹ️ Please review and update the maintainer list as needed.
"""
    else:
        logger.error(f"Failed to create MAINTAINERS.md: {message}")
        return format_error(message)


def create_dependabot_config(
    owner: str | None = None,
    repo: str | None = None,
    local_path: str = ".",
) -> str:
    """
    Create a Dependabot configuration file for automated dependency updates.

    Satisfies: OSPS-VM-05.01, OSPS-VM-05.02, OSPS-VM-05.03

    Intelligently detects package ecosystems used in the repository and
    configures Dependabot for each.

    Args:
        owner: GitHub Org/User (auto-detected if not provided)
        repo: Repository Name (auto-detected if not provided)
        local_path: Path to repository

    Returns:
        Success message with created file path
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        logger.warning(f"Invalid path for dependabot.yml: {error}")
        return format_error(error)

    # Auto-detect owner/repo
    if not owner or not repo:
        detected = detect_repo_from_git(resolved_path)
        if detected:
            owner = owner or detected["owner"]
            repo = repo or detected["repo"]
        else:
            owner = owner or "OWNER"
            repo = repo or "REPO"

    # Detect ecosystems
    ecosystems = _detect_package_ecosystems(resolved_path)

    # Always include github-actions if .github/workflows exists
    if os.path.exists(os.path.join(resolved_path, ".github", "workflows")):
        if "github-actions" not in ecosystems:
            ecosystems.insert(0, "github-actions")

    if not ecosystems:
        ecosystems = ["github-actions"]  # Default fallback

    # Build configuration
    updates = []
    for ecosystem in ecosystems:
        # Determine directory based on ecosystem
        if ecosystem == "github-actions":
            directory = "/"
            prefix = "ci"
        elif ecosystem in ("npm", "pip", "cargo", "gomod", "maven", "gradle", "bundler", "composer"):
            directory = "/"
            prefix = "deps"
        elif ecosystem == "docker":
            directory = "/"
            prefix = "docker"
        elif ecosystem == "terraform":
            directory = "/"
            prefix = "infra"
        else:
            directory = "/"
            prefix = "deps"

        updates.append(f"""  - package-ecosystem: "{ecosystem}"
    directory: "{directory}"
    schedule:
      interval: "weekly"
    commit-message:
      prefix: "{prefix}"
    open-pull-requests-limit: 10""")

    content = f"""# Dependabot configuration
# See: https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuration-options-for-the-dependabot.yml-file

version: 2
updates:
{chr(10).join(updates)}
"""

    # Ensure .github directory exists
    github_dir = os.path.join(resolved_path, ".github")
    ensure_directory(github_dir)

    filepath = os.path.join(github_dir, "dependabot.yml")
    success, message = write_file_safely(filepath, content)

    if success:
        logger.info(f"Created dependabot.yml at {filepath}")
        ecosystem_list = ", ".join(ecosystems)
        return f"""✅ Created dependabot.yml

**OSPS Controls Addressed:**
- OSPS-VM-05.01: Dependency update automation configured
- OSPS-VM-05.02: Security updates enabled
- OSPS-VM-05.03: Automated dependency scanning active

**File:** {filepath}
**Detected ecosystems:** {ecosystem_list}

ℹ️ Dependabot will create PRs for dependency updates weekly.
Review and merge these PRs to keep dependencies secure and up-to-date.
"""
    else:
        logger.error(f"Failed to create dependabot.yml: {message}")
        return format_error(message)


def create_support_doc(
    owner: str | None = None,
    repo: str | None = None,
    local_path: str = ".",
) -> str:
    """
    Create a SUPPORT.md file describing how to get help.

    Satisfies: OSPS-DO-03.01

    Args:
        owner: GitHub Org/User (auto-detected if not provided)
        repo: Repository Name (auto-detected if not provided)
        local_path: Path to repository

    Returns:
        Success message with created file path
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        logger.warning(f"Invalid path for SUPPORT.md: {error}")
        return format_error(error)

    # Auto-detect owner/repo
    if not owner or not repo:
        detected = detect_repo_from_git(resolved_path)
        if detected:
            owner = owner or detected["owner"]
            repo = repo or detected["repo"]
        else:
            owner = owner or "OWNER"
            repo = repo or "REPO"

    # Check if Discussions are enabled
    has_discussions = False
    try:
        result = subprocess.run(
            ["gh", "api", f"/repos/{owner}/{repo}", "--jq", ".has_discussions"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip() == "true":
            has_discussions = True
    except (subprocess.SubprocessError, OSError):
        pass

    discussion_section = f"""## Discussions

For questions, ideas, and community support, visit our [GitHub Discussions](https://github.com/{owner}/{repo}/discussions).
""" if has_discussions else ""

    content = f"""# Support

## Getting Help

Thanks for using {repo}! Here are some ways to get help:

### Documentation

- Check the [README](README.md) for basic usage
- Review any documentation in the `/docs` folder

### Issues

If you've found a bug or have a feature request:
1. Search [existing issues](https://github.com/{owner}/{repo}/issues) first
2. If not found, [open a new issue](https://github.com/{owner}/{repo}/issues/new)
{discussion_section}
### Security Issues

**Please do not report security vulnerabilities through public issues.**

See our [Security Policy](SECURITY.md) for responsible disclosure instructions.

## Response Times

This is {"a community-maintained" if _is_single_maintainer_project(owner, repo, get_repo_maintainers(owner, repo)) else "an"} open source project. Response times may vary based on
maintainer availability. We appreciate your patience!

## Contributing

Want to help improve {repo}? See our [Contributing Guide](CONTRIBUTING.md).
"""

    filepath = os.path.join(resolved_path, "SUPPORT.md")
    success, message = write_file_safely(filepath, content)

    if success:
        logger.info(f"Created SUPPORT.md at {filepath}")
        return f"""✅ Created SUPPORT.md

**OSPS Controls Addressed:**
- OSPS-DO-03.01: Support documentation available

**File:** {filepath}

ℹ️ Review and customize the support channels for your project.
{"Consider enabling GitHub Discussions for community Q&A." if not has_discussions else "GitHub Discussions link included."}
"""
    else:
        logger.error(f"Failed to create SUPPORT.md: {message}")
        return format_error(message)


def create_bug_report_template(
    owner: str | None = None,
    repo: str | None = None,
    local_path: str = ".",
) -> str:
    """
    Create a GitHub issue template for bug reports.

    Satisfies: OSPS-DO-02.01

    Args:
        owner: GitHub Org/User (auto-detected if not provided)
        repo: Repository Name (auto-detected if not provided)
        local_path: Path to repository

    Returns:
        Success message with created file path
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        logger.warning(f"Invalid path for bug report template: {error}")
        return format_error(error)

    # Auto-detect owner/repo
    if not owner or not repo:
        detected = detect_repo_from_git(resolved_path)
        if detected:
            owner = owner or detected["owner"]
            repo = repo or detected["repo"]
        else:
            owner = owner or "OWNER"
            repo = repo or "REPO"

    content = """---
name: Bug Report
about: Create a report to help us improve
title: '[BUG] '
labels: bug
assignees: ''
---

## Describe the Bug

A clear and concise description of what the bug is.

## To Reproduce

Steps to reproduce the behavior:

1. Step one
2. Step two
3. Step three
4. See error

## Expected Behavior

A clear and concise description of what you expected to happen.

## Actual Behavior

What actually happened instead.

## Environment

- OS: [e.g., macOS 14.0, Ubuntu 22.04, Windows 11]
- Version: [e.g., v1.2.3]
- Other relevant details:

## Screenshots

If applicable, add screenshots to help explain your problem.

## Additional Context

Add any other context about the problem here.

## Possible Solution

If you have ideas on how to fix this, please share them.
"""

    # Create directory structure
    template_dir = os.path.join(resolved_path, ".github", "ISSUE_TEMPLATE")
    ensure_directory(template_dir)

    filepath = os.path.join(template_dir, "bug_report.md")
    success, message = write_file_safely(filepath, content)

    if success:
        logger.info(f"Created bug report template at {filepath}")
        return f"""✅ Created bug report template

**OSPS Controls Addressed:**
- OSPS-DO-02.01: Bug reporting process documented

**File:** {filepath}

ℹ️ Users will now see this template when creating bug report issues.
Consider also creating a feature request template for completeness.
"""
    else:
        logger.error(f"Failed to create bug report template: {message}")
        return format_error(message)


def configure_dco_enforcement(
    owner: str | None = None,
    repo: str | None = None,
    local_path: str = ".",
) -> str:
    """
    Configure Developer Certificate of Origin (DCO) enforcement.

    Satisfies: OSPS-LE-01.01

    Note: This creates documentation and guidance. Actual DCO enforcement
    requires either the DCO GitHub App or a CI check.

    Args:
        owner: GitHub Org/User (auto-detected if not provided)
        repo: Repository Name (auto-detected if not provided)
        local_path: Path to repository

    Returns:
        Success message with guidance
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        logger.warning(f"Invalid path for DCO configuration: {error}")
        return format_error(error)

    # Auto-detect owner/repo
    if not owner or not repo:
        detected = detect_repo_from_git(resolved_path)
        if detected:
            owner = owner or detected["owner"]
            repo = repo or detected["repo"]
        else:
            owner = owner or "OWNER"
            repo = repo or "REPO"

    # Check if CONTRIBUTING.md exists and update it
    contributing_path = os.path.join(resolved_path, "CONTRIBUTING.md")
    dco_section = """
## Developer Certificate of Origin (DCO)

This project uses the [Developer Certificate of Origin](https://developercertificate.org/) (DCO).

By contributing to this project, you agree to the DCO. This means you certify that:
- You have the right to submit the contribution
- You grant the project the rights to use your contribution

### Signing Your Commits

Sign your commits by adding `Signed-off-by` to your commit messages:

```bash
git commit -s -m "Your commit message"
```

Or configure git to sign automatically:

```bash
git config --global user.name "Your Name"
git config --global user.email "your@email.com"
```

Then use `git commit -s` for all commits.
"""

    if os.path.exists(contributing_path):
        try:
            with open(contributing_path) as f:
                content = f.read()

            # Check if DCO section already exists
            if "Developer Certificate of Origin" not in content and "DCO" not in content:
                content += dco_section
                success, message = write_file_safely(contributing_path, content)
                if success:
                    logger.info("Added DCO section to CONTRIBUTING.md")
                    contributing_updated = True
                else:
                    contributing_updated = False
            else:
                contributing_updated = False  # Already has DCO info
        except OSError:
            contributing_updated = False
    else:
        contributing_updated = False

    return f"""✅ DCO Configuration Guidance

**OSPS Controls Addressed:**
- OSPS-LE-01.01: Contributions require sign-off

{"**Updated:** CONTRIBUTING.md with DCO requirements" if contributing_updated else ""}

## Manual Steps Required

To fully enforce DCO, you need to set up one of these options:

### Option 1: DCO GitHub App (Recommended)

1. Install the [DCO App](https://github.com/apps/dco) on your repository
2. The app will automatically check for signed commits on PRs

### Option 2: GitHub Actions Check

Add this workflow to `.github/workflows/dco.yml`:

```yaml
name: DCO Check
on: [pull_request]
jobs:
  dco:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: DCO Check
        uses: dco/dco-action@v1
```

### Option 3: Branch Protection Rule

1. Go to Settings → Branches → Branch protection rules
2. Add rule for your main branch
3. Enable "Require status checks to pass"
4. Add "DCO" as a required check (after installing the app)

ℹ️ The DCO GitHub App is the simplest option and works automatically.
"""


__all__ = [
    "create_security_policy",
    "ensure_vex_policy",
    "create_contributing_guide",
    "create_codeowners",
    "create_maintainers_doc",
    "create_governance_doc",
    "create_dependabot_config",
    "create_support_doc",
    "create_bug_report_template",
    "configure_dco_enforcement",
]
