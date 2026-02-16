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


