"""Shared fixtures for darnit-example tests."""

import pytest

from darnit.sieve.models import CheckContext


@pytest.fixture
def make_context(tmp_path):
    """Factory fixture that creates a CheckContext pointing at a temp directory.

    Usage:
        ctx = make_context()                    # empty project
        ctx = make_context({"README.md": "# Hi"})  # project with files
    """

    def _make(files: dict[str, str] | None = None) -> CheckContext:
        if files:
            for name, content in files.items():
                filepath = tmp_path / name
                filepath.parent.mkdir(parents=True, exist_ok=True)
                filepath.write_text(content, encoding="utf-8")

        return CheckContext(
            owner="test-owner",
            repo="test-repo",
            local_path=str(tmp_path),
            default_branch="main",
            control_id="TEST",
        )

    return _make


@pytest.fixture
def empty_project(tmp_path):
    """A temporary directory with no files (empty project)."""
    return str(tmp_path)


@pytest.fixture
def full_project(tmp_path):
    """A temporary directory with all hygiene files present."""
    files = {
        "README.md": "# Test Project\n\nThis is a test project for validating hygiene controls.\n\n## Installation\n\nRun `pip install test`.\n\n## Usage\n\nJust use it.\n",
        "LICENSE": "MIT License\n\nCopyright 2024\n",
        "SECURITY.md": "# Security Policy\n\n## Reporting\n\nEmail security@example.com\n",
        ".gitignore": "*.pyc\n__pycache__/\n",
        ".editorconfig": "root = true\n\n[*]\nindent_style = space\n",
        "CONTRIBUTING.md": "# Contributing\n\nPRs welcome.\n",
        ".github/workflows/ci.yml": "name: CI\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n",
    }
    for name, content in files.items():
        filepath = tmp_path / name
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")
    return str(tmp_path)
