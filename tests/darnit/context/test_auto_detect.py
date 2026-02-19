"""Tests for darnit.context.auto_detect module."""

import os

from darnit.context.auto_detect import (
    _extract_hostname,
    collect_auto_context,
    detect_ci_provider,
    detect_languages,
    detect_platform,
    detect_primary_language,
)


class TestExtractHostname:
    def test_https_github(self):
        assert _extract_hostname("https://github.com/owner/repo.git") == "github.com"

    def test_ssh_github(self):
        assert _extract_hostname("git@github.com:owner/repo.git") == "github.com"

    def test_https_gitlab(self):
        assert _extract_hostname("https://gitlab.com/owner/repo.git") == "gitlab.com"

    def test_ssh_gitlab(self):
        assert _extract_hostname("git@gitlab.com:owner/repo.git") == "gitlab.com"

    def test_https_bitbucket(self):
        assert _extract_hostname("https://bitbucket.org/owner/repo.git") == "bitbucket.org"

    def test_invalid_url(self):
        assert _extract_hostname("not-a-url") is None


class TestDetectPlatform:
    def test_detects_github_from_origin(self, tmp_path):
        """detect_platform returns 'github' for a repo with github.com origin."""
        # Set up a bare git repo with an origin remote
        os.system(f"git init {tmp_path} --quiet")
        os.system(f"git -C {tmp_path} remote add origin https://github.com/owner/repo.git")

        assert detect_platform(str(tmp_path)) == "github"

    def test_detects_gitlab_from_origin(self, tmp_path):
        os.system(f"git init {tmp_path} --quiet")
        os.system(f"git -C {tmp_path} remote add origin https://gitlab.com/owner/repo.git")

        assert detect_platform(str(tmp_path)) == "gitlab"

    def test_prefers_upstream_over_origin(self, tmp_path):
        os.system(f"git init {tmp_path} --quiet")
        os.system(f"git -C {tmp_path} remote add origin https://gitlab.com/owner/repo.git")
        os.system(f"git -C {tmp_path} remote add upstream https://github.com/owner/repo.git")

        assert detect_platform(str(tmp_path)) == "github"

    def test_returns_none_for_no_remotes(self, tmp_path):
        os.system(f"git init {tmp_path} --quiet")
        assert detect_platform(str(tmp_path)) is None

    def test_returns_none_for_non_git_dir(self, tmp_path):
        assert detect_platform(str(tmp_path)) is None


class TestDetectCIProvider:
    def test_github_actions(self, tmp_path):
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text("on: push")

        assert detect_ci_provider(str(tmp_path)) == "github"

    def test_github_actions_empty_dir(self, tmp_path):
        """Empty .github/workflows/ dir (no .yml files) should not match."""
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)

        assert detect_ci_provider(str(tmp_path)) is None

    def test_gitlab_ci(self, tmp_path):
        (tmp_path / ".gitlab-ci.yml").write_text("stages: [build]")

        assert detect_ci_provider(str(tmp_path)) == "gitlab"

    def test_jenkinsfile(self, tmp_path):
        (tmp_path / "Jenkinsfile").write_text("pipeline {}")

        assert detect_ci_provider(str(tmp_path)) == "jenkins"

    def test_circleci(self, tmp_path):
        circleci = tmp_path / ".circleci"
        circleci.mkdir()
        (circleci / "config.yml").write_text("version: 2")

        assert detect_ci_provider(str(tmp_path)) == "circleci"

    def test_no_ci(self, tmp_path):
        assert detect_ci_provider(str(tmp_path)) is None


class TestDetectPrimaryLanguage:
    def test_python_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]")
        assert detect_primary_language(str(tmp_path)) == "python"

    def test_go_mod(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com")
        assert detect_primary_language(str(tmp_path)) == "go"

    def test_rust_cargo(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text("[package]")
        assert detect_primary_language(str(tmp_path)) == "rust"

    def test_javascript_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        assert detect_primary_language(str(tmp_path)) == "javascript"

    def test_typescript_override(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.json").write_text("{}")
        assert detect_primary_language(str(tmp_path)) == "typescript"

    def test_java_pom(self, tmp_path):
        (tmp_path / "pom.xml").write_text("<project/>")
        assert detect_primary_language(str(tmp_path)) == "java"

    def test_no_language(self, tmp_path):
        assert detect_primary_language(str(tmp_path)) is None


class TestDetectLanguages:
    def test_single_language(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com")
        assert detect_languages(str(tmp_path)) == ["go"]

    def test_multi_language(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com")
        (tmp_path / "package.json").write_text("{}")
        assert detect_languages(str(tmp_path)) == ["go", "javascript"]

    def test_typescript_refinement(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.json").write_text("{}")
        assert detect_languages(str(tmp_path)) == ["typescript"]

    def test_multi_language_with_typescript(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com")
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.json").write_text("{}")
        assert detect_languages(str(tmp_path)) == ["go", "typescript"]

    def test_no_manifests(self, tmp_path):
        assert detect_languages(str(tmp_path)) == []

    def test_deduplication_python(self, tmp_path):
        """Multiple Python manifests should produce a single 'python' entry."""
        (tmp_path / "pyproject.toml").write_text("[project]")
        (tmp_path / "setup.py").write_text("from setuptools import setup")
        assert detect_languages(str(tmp_path)) == ["python"]

    def test_deduplication_java(self, tmp_path):
        """Multiple Java manifests should produce a single 'java' entry."""
        (tmp_path / "pom.xml").write_text("<project/>")
        (tmp_path / "build.gradle").write_text("plugins {}")
        assert detect_languages(str(tmp_path)) == ["java"]


class TestCollectAutoContext:
    def test_collects_all(self, tmp_path):
        # Set up git + GitHub remote + Python + GitHub Actions
        os.system(f"git init {tmp_path} --quiet")
        os.system(f"git -C {tmp_path} remote add origin https://github.com/owner/repo.git")
        (tmp_path / "pyproject.toml").write_text("[project]")
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text("on: push")

        result = collect_auto_context(str(tmp_path))

        assert result["platform"] == "github"
        assert result["ci_provider"] == "github"
        assert result["primary_language"] == "python"
        assert result["languages"] == ["python"]

    def test_languages_always_included(self, tmp_path):
        """languages key is always present, even as empty list."""
        result = collect_auto_context(str(tmp_path))
        assert result["languages"] == []

    def test_omits_undetectable(self, tmp_path):
        """Keys with None detection are omitted from the result."""
        os.system(f"git init {tmp_path} --quiet")
        os.system(f"git -C {tmp_path} remote add origin https://github.com/owner/repo.git")
        # No language files, no CI files

        result = collect_auto_context(str(tmp_path))
        assert result["platform"] == "github"
        assert result["languages"] == []
        assert "ci_provider" not in result
        assert "primary_language" not in result
