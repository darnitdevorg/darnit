"""Pytest fixtures for darnit-testchecks tests."""

import tempfile
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture
def temp_repo() -> Generator[Path, None, None]:
    """Create a temporary directory simulating a repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def minimal_repo(temp_repo: Path) -> Path:
    """Create a minimal repo with just README and LICENSE."""
    (temp_repo / "README.md").write_text("# Test Project\n")
    (temp_repo / "LICENSE").write_text("MIT License\n")
    return temp_repo


@pytest.fixture
def complete_repo(temp_repo: Path) -> Path:
    """Create a repo that passes all Level 1 checks."""
    # Level 1 files
    (temp_repo / "README.md").write_text("# Test Project\n\nA test project.\n")
    (temp_repo / "LICENSE").write_text("MIT License\n")
    (temp_repo / "CHANGELOG.md").write_text("# Changelog\n\n## v1.0.0\n- Initial release\n")
    (temp_repo / ".gitignore").write_text(
        "# Environment\n.env\n*.key\n*.pem\n__pycache__/\n"
    )

    # Level 2 files
    (temp_repo / ".editorconfig").write_text("[*]\nindent_style = space\n")
    (temp_repo / ".pre-commit-config.yaml").write_text("repos:\n  - repo: local\n")

    # Level 3 files - CI config
    workflows_dir = temp_repo / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "ci.yml").write_text(
        "name: CI\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: pytest\n"
    )

    # Source code without violations
    src_dir = temp_repo / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text(
        '"""Main module."""\n\nimport logging\n\nlogger = logging.getLogger(__name__)\n\n'
        'def hello():\n    """Say hello."""\n    logger.info("Hello")\n'
    )

    return temp_repo


@pytest.fixture
def repo_with_violations(temp_repo: Path) -> Path:
    """Create a repo with code quality violations."""
    (temp_repo / "README.md").write_text("# Test\n")
    (temp_repo / "LICENSE").write_text("MIT\n")
    (temp_repo / ".gitignore").write_text("*.pyc\n")  # Missing .env, *.key

    # Python file with violations
    (temp_repo / "app.py").write_text(
        '# TODO: fix this later\n'
        'print("Hello world")\n'
        'password = "secret123"\n'
    )

    return temp_repo


@pytest.fixture
def user_config_content() -> str:
    """Sample user config that skips some controls."""
    return '''
version = "1.0"
extends = "testchecks"

[controls."TEST-QA-01"]
status = "n/a"
reason = "TODOs are acceptable"

[controls."TEST-QA-02"]
status = "n/a"
reason = "Print statements OK in scripts"
'''
