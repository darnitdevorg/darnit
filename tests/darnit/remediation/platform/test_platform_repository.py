"""The repository whose platform settings a remediation changes (framework-design 4.5, 15.6)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from darnit.remediation.platform import platform_repository
from darnit.remediation.platform.engine import is_supported


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A checkout with no remote."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


@pytest.mark.unit
class TestPlatformRepository:
    def test_named_repository_without_host_is_on_github(self, checkout: Path) -> None:
        repository = platform_repository(str(checkout), "o", "r")

        assert repository == "github.com/o/r"
        assert is_supported(repository)

    def test_named_host_is_kept_and_takes_no_platform_call(self, checkout: Path) -> None:
        repository = platform_repository(str(checkout), "o", "r", "gitlab.com")

        assert repository == "gitlab.com/o/r"
        assert not is_supported(repository)
