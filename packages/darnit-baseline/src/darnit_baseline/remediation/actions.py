"""File creation remediation actions.

This module contains functions that create compliance-related files
like SECURITY.md, CONTRIBUTING.md, GOVERNANCE.md, etc.
"""

import os
from typing import Optional

from darnit.core.logging import get_logger
from darnit.core.utils import validate_local_path, detect_repo_from_git
from darnit.tools import write_file_safely
from darnit.remediation.helpers import get_repo_maintainers

logger = get_logger("remediation.actions")


def create_security_policy(
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    local_path: str = ".",
    template: str = "standard"
) -> str:
    """
    Create a SECURITY.md file for vulnerability reporting.

    Satisfies: OSPS-VM-01.01, OSPS-VM-02.01, OSPS-VM-03.01

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
"""

    filepath = os.path.join(resolved_path, "SECURITY.md")
    success, message = write_file_safely(filepath, content)

    if success:
        logger.info(f"Created SECURITY.md at {filepath}")
        return f"""✅ Created SECURITY.md

**OSPS Controls Addressed:**
- OSPS-VM-01.01: Security contact defined
- OSPS-VM-02.01: Vulnerability reporting process
- OSPS-VM-03.01: Response timeline documented

**File:** {filepath}
"""
    else:
        logger.error(f"Failed to create SECURITY.md: {message}")
        return f"❌ {message}"


def create_contributing_guide(
    owner: Optional[str] = None,
    repo: Optional[str] = None,
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


__all__ = [
    "create_security_policy",
    "create_contributing_guide",
]
