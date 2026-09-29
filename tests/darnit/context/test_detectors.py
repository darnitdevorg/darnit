"""Tests for forge and build system detectors.

These tests use tmp_path to create fake repos with the right files
and verify the detectors return the expected values.
No real git repos or network calls needed.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

from darnit.context.detectors import detect_build_system, detect_forge


class TestDetectForge:
    """Tests for detect_forge()."""

    def test_github_remote(self, tmp_path: Path) -> None:
        """Returns 'github' when origin points to github.com."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = "https://github.com/org/repo.git\n"
            mock_run.return_value.returncode = 0
            result = detect_forge(str(tmp_path))
        assert result == "github"

    def test_gitlab_remote(self, tmp_path: Path) -> None:
        """Returns 'gitlab' when origin points to gitlab.com."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = "https://gitlab.com/org/repo.git\n"
            mock_run.return_value.returncode = 0
            result = detect_forge(str(tmp_path))
        assert result == "gitlab"

    def test_bitbucket_remote(self, tmp_path: Path) -> None:
        """Returns 'bitbucket' when origin points to bitbucket.org."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = "https://bitbucket.org/org/repo.git\n"
            mock_run.return_value.returncode = 0
            result = detect_forge(str(tmp_path))
        assert result == "bitbucket"

    def test_unknown_remote(self, tmp_path: Path) -> None:
        """Returns 'unknown' for unrecognised forge URLs."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = "https://mygitserver.internal/repo.git\n"
            mock_run.return_value.returncode = 0
            result = detect_forge(str(tmp_path))
        assert result == "unknown"

    def test_git_not_available(self, tmp_path: Path) -> None:
        """Returns 'unknown' gracefully when git is not installed."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = detect_forge(str(tmp_path))
        assert result == "unknown"

    def test_git_command_fails(self, tmp_path: Path) -> None:
        """Returns 'unknown' gracefully when git remote fails."""
        with patch("subprocess.run", side_effect=OSError("git error")):
            result = detect_forge(str(tmp_path))
        assert result == "unknown"

    def test_git_command_times_out(self, tmp_path: Path) -> None:
        """Returns 'unknown' when git remote lookup times out."""
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=10),
        ):
            result = detect_forge(str(tmp_path))

        assert result == "unknown"


class TestDetectBuildSystem:
    """Tests for detect_build_system()."""

    def test_rust_cargo(self, tmp_path: Path) -> None:
        """Returns 'cargo' when Cargo.toml exists."""
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "mylib"')
        assert detect_build_system(str(tmp_path)) == "cargo"

    def test_go_modules(self, tmp_path: Path) -> None:
        """Returns 'go' when go.mod exists."""
        (tmp_path / "go.mod").write_text("module example.com/myapp")
        assert detect_build_system(str(tmp_path)) == "go"

    def test_maven(self, tmp_path: Path) -> None:
        """Returns 'maven' when pom.xml exists."""
        (tmp_path / "pom.xml").write_text("<project></project>")
        assert detect_build_system(str(tmp_path)) == "maven"

    def test_gradle(self, tmp_path: Path) -> None:
        """Returns 'gradle' when build.gradle exists."""
        (tmp_path / "build.gradle").write_text("apply plugin: 'java'")
        assert detect_build_system(str(tmp_path)) == "gradle"

    def test_python_modern(self, tmp_path: Path) -> None:
        """Returns 'python' when pyproject.toml exists."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'myapp'")
        assert detect_build_system(str(tmp_path)) == "python"

    def test_python_legacy(self, tmp_path: Path) -> None:
        """Returns 'python' when setup.py exists (no pyproject.toml)."""
        (tmp_path / "setup.py").write_text("from setuptools import setup")
        assert detect_build_system(str(tmp_path)) == "python"

    def test_npm(self, tmp_path: Path) -> None:
        """Returns 'npm' when package.json exists."""
        (tmp_path / "package.json").write_text('{"name": "myapp"}')
        assert detect_build_system(str(tmp_path)) == "npm"

    def test_make(self, tmp_path: Path) -> None:
        """Returns 'make' when Makefile exists and nothing else."""
        (tmp_path / "Makefile").write_text("all:\n\techo hello")
        assert detect_build_system(str(tmp_path)) == "make"

    def test_no_build_system(self, tmp_path: Path) -> None:
        """Returns 'unknown' when no build files exist."""
        assert detect_build_system(str(tmp_path)) == "unknown"

    def test_cargo_takes_priority_over_make(self, tmp_path: Path) -> None:
        """Cargo wins over Makefile — more specific signal."""
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "mylib"')
        (tmp_path / "Makefile").write_text("all:\n\techo hello")
        assert detect_build_system(str(tmp_path)) == "cargo"
