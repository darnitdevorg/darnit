"""Pytest configuration and shared fixtures."""

import shutil
import subprocess
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_operator_config(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    """Keep the developer's own operator configuration and confirmations out of every test (feature 040)."""
    from darnit.config.operator import loader
    from darnit.trust import confirmations

    missing = tmp_path_factory.mktemp("operator-config") / "absent"
    monkeypatch.setattr(loader, "user_config_dir", lambda: missing)
    data_root = tmp_path_factory.mktemp("data-root") / "darnit"
    monkeypatch.setattr(confirmations, "user_data_root", lambda: data_root)
    loader.set_launch_options(None, strict=False)
    yield
    loader.set_launch_options(None, strict=False)


TRUSTED_OWNER, TRUSTED_REPO = "test-owner", "test-repo"
_CI_VARS = ("GITHUB_ACTIONS", "GITLAB_CI", "CI", "JENKINS_URL", "TF_BUILD", "BUILDKITE", "CIRCLECI", "TRAVIS")


@pytest.fixture
def trusted_target(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    """An operator configuration trusting github.com/test-owner/test-repo, outside CI.

    Confirmations of context values name the repository and are written into
    it only when the operator trusts it (feature 042, FR-011).
    """
    from darnit.config.operator import loader

    for var in _CI_VARS:
        monkeypatch.delenv(var, raising=False)
    path = tmp_path_factory.mktemp("trusting-operator") / "config.toml"
    path.write_text(f'schema_version = 1\n\n[trust]\nrepos = ["github.com/{TRUSTED_OWNER}/{TRUSTED_REPO}"]\n')
    path.chmod(0o600)
    loader.set_launch_options(path, strict=False)
    return TRUSTED_OWNER, TRUSTED_REPO


@pytest.fixture(autouse=True)
def _restore_control_registry() -> Generator[None, None, None]:
    """Audits register framework controls in a process-wide registry (#442); keep them out of later tests."""
    from darnit.sieve.registry import get_control_registry
    from darnit.tools import audit

    registry = get_control_registry()
    saved_specs = dict(registry._specs)
    saved_registered = set(audit._toml_controls_registered)
    yield
    registry._specs.clear()
    registry._specs.update(saved_specs)
    audit._toml_controls_registered.clear()
    audit._toml_controls_registered.update(saved_registered)


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


