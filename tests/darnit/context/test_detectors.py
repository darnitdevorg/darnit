"""Tests for forge, CI, and build system detectors.

These tests use tmp_path to create fake repos with the right files
and verify the detectors return the expected values.
No real git repos or network calls needed.
"""

from pathlib import Path
from unittest.mock import patch

from darnit.context.detectors import detect_build_system, detect_ci, detect_forge


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
        with patch("subprocess.run", side_effect=Exception("git error")):
            result = detect_forge(str(tmp_path))
        assert result == "unknown"


class TestDetectCI:
    """Tests for detect_ci()."""

    def test_github_actions(self, tmp_path: Path) -> None:
        """Returns 'github_actions' when .github/workflows/ exists."""
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        assert detect_ci(str(tmp_path)) == "github_actions"

    def test_circleci(self, tmp_path: Path) -> None:
        """Returns 'circleci' when .circleci/config.yml exists."""
        (tmp_path / ".circleci").mkdir()
        (tmp_path / ".circleci" / "config.yml").write_text("version: 2.1")
        assert detect_ci(str(tmp_path)) == "circleci"

    def test_jenkins(self, tmp_path: Path) -> None:
        """Returns 'jenkins' when Jenkinsfile exists."""
        (tmp_path / "Jenkinsfile").write_text("pipeline {}")
        assert detect_ci(str(tmp_path)) == "jenkins"

    def test_gitlab_ci(self, tmp_path: Path) -> None:
        """Returns 'gitlab_ci' when .gitlab-ci.yml exists."""
        (tmp_path / ".gitlab-ci.yml").write_text("stages: []")
        assert detect_ci(str(tmp_path)) == "gitlab_ci"

    def test_azure_pipelines(self, tmp_path: Path) -> None:
        """Returns 'azure_pipelines' when azure-pipelines.yml exists."""
        (tmp_path / "azure-pipelines.yml").write_text("trigger: []")
        assert detect_ci(str(tmp_path)) == "azure_pipelines"

    def test_travis(self, tmp_path: Path) -> None:
        """Returns 'travis' when .travis.yml exists."""
        (tmp_path / ".travis.yml").write_text("language: python")
        assert detect_ci(str(tmp_path)) == "travis"

    def test_no_ci_found(self, tmp_path: Path) -> None:
        """Returns 'unknown' when no CI config files exist."""
        assert detect_ci(str(tmp_path)) == "unknown"

    def test_github_actions_takes_priority(self, tmp_path: Path) -> None:
        """GitHub Actions wins when multiple CI configs exist."""
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        (tmp_path / "Jenkinsfile").write_text("pipeline {}")
        assert detect_ci(str(tmp_path)) == "github_actions"


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
