"""Pytest configuration and shared fixtures."""

import shutil
import subprocess
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for tests."""
    tmp = tempfile.mkdtemp(prefix="darnit_test_")
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def temp_git_repo(temp_dir: Path) -> Generator[Path, None, None]:
    """Create a temporary git repository for tests."""
    # Initialize git repo
    subprocess.run(
        ["git", "init"],
        cwd=temp_dir,
        capture_output=True,
        check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=temp_dir,
        capture_output=True,
        check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=temp_dir,
        capture_output=True,
        check=True
    )

    # Create initial commit
    readme = temp_dir / "README.md"
    readme.write_text("# Test Repository\n")
    subprocess.run(
        ["git", "add", "."],
        cwd=temp_dir,
        capture_output=True,
        check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=temp_dir,
        capture_output=True,
        check=True
    )

    yield temp_dir


@pytest.fixture
def sample_security_md() -> str:
    """Sample SECURITY.md content."""
    return """# Security Policy

## Reporting a Vulnerability

Please report security vulnerabilities to security@example.com.

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x     | :white_check_mark: |
| < 1.0   | :x:                |
"""


@pytest.fixture
def sample_project_files(temp_git_repo: Path, sample_security_md: str) -> Path:
    """Create a temp repo with common project files."""
    # Create SECURITY.md
    (temp_git_repo / "SECURITY.md").write_text(sample_security_md)

    # Create LICENSE
    (temp_git_repo / "LICENSE").write_text("MIT License\n\nCopyright 2024\n")

    # Create CONTRIBUTING.md
    (temp_git_repo / "CONTRIBUTING.md").write_text("# Contributing\n\nWelcome!\n")

    # Create .github directory
    github_dir = temp_git_repo / ".github"
    github_dir.mkdir(exist_ok=True)

    # Create dependabot.yml
    (github_dir / "dependabot.yml").write_text("""version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "weekly"
""")

    return temp_git_repo
