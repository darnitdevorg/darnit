"""Pytest fixtures for darnit-plugins tests."""

import sys
from pathlib import Path

import pytest

# Add package paths for testing without installation
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "darnit" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """Create a minimal temporary repository."""
    (tmp_path / ".git").mkdir()
    return tmp_path


@pytest.fixture
def repo_with_deps(tmp_path: Path) -> Path:
    """Create a repository with dependency files."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "package.json").write_text('{"dependencies": {"lodash": "^4.0.0"}}')
    (tmp_path / "requirements.txt").write_text("requests>=2.28.0\n")
    return tmp_path
