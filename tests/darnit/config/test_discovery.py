"""Tests for config discovery module.

Tests for darnit.config.discovery - file/CI/project-name discovery
and config synchronisation helpers.
"""

import json
import os

from darnit.config.discovery import (
    discover_and_create_config,
    discover_ci_config,
    discover_files,
    discover_project_name,
    sync_discovered_to_config,
)
from darnit.config.schema import (
    PathRef,
    SecurityConfig,
    create_minimal_config,
)

# ---------------------------------------------------------------------------
# discover_files
# ---------------------------------------------------------------------------


class TestDiscoverFiles:
    def test_none_file_locations_returns_empty(self, temp_dir):
        result = discover_files(str(temp_dir), None)
        assert result == {}

    def test_empty_file_locations_returns_empty(self, temp_dir):
        result = discover_files(str(temp_dir), {})
        assert result == {}

    def test_discovers_exact_file_match(self, temp_dir):
        (temp_dir / "SECURITY.md").write_text("# Security")

        result = discover_files(
            str(temp_dir),
            {"security.policy": ["SECURITY.md"]},
        )

        assert "security.policy" in result
        assert result["security.policy"] == "SECURITY.md"

    def test_uses_first_matching_pattern(self, temp_dir):
        (temp_dir / "SECURITY.md").write_text("# Security")
        (temp_dir / "security.txt").write_text("security")

        result = discover_files(
            str(temp_dir),
            {"security.policy": ["SECURITY.md", "security.txt"]},
        )

        assert result["security.policy"] == "SECURITY.md"

    def test_skips_ref_when_no_pattern_matches(self, temp_dir):
        result = discover_files(
            str(temp_dir),
            {"security.policy": ["SECURITY.md", "SECURITY.rst"]},
        )

        assert "security.policy" not in result

    def test_discovers_multiple_refs(self, temp_dir):
        (temp_dir / "SECURITY.md").write_text("# Security")
        (temp_dir / "LICENSE").write_text("MIT")

        result = discover_files(
            str(temp_dir),
            {
                "security.policy": ["SECURITY.md"],
                "legal.license": ["LICENSE"],
            },
        )

        assert result["security.policy"] == "SECURITY.md"
        assert result["legal.license"] == "LICENSE"

    def test_glob_pattern_matches_nested_file(self, temp_dir):
        (temp_dir / "docs").mkdir()
        (temp_dir / "docs" / "security.md").write_text("# Security")

        result = discover_files(
            str(temp_dir),
            {"security.policy": ["docs/security.md"]},
        )

        assert "security.policy" in result


# ---------------------------------------------------------------------------
# discover_ci_config
# ---------------------------------------------------------------------------


class TestDiscoverCiConfig:
    def test_no_ci_returns_none(self, temp_dir):
        result = discover_ci_config(str(temp_dir))
        assert result is None

    def test_detects_github_actions(self, temp_dir):
        workflows = temp_dir / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text("name: CI\non: push")

        result = discover_ci_config(str(temp_dir))

        assert result is not None
        assert result.provider == "github"

    def test_github_workflow_list_populated(self, temp_dir):
        workflows = temp_dir / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text("name: CI")
        (workflows / "release.yaml").write_text("name: Release")

        result = discover_ci_config(str(temp_dir))

        assert result is not None
        assert ".github/workflows/ci.yml" in result.workflows
        assert ".github/workflows/release.yaml" in result.workflows

    def test_github_detects_testing_workflow(self, temp_dir):
        workflows = temp_dir / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text("steps:\n  - run: pytest")

        result = discover_ci_config(str(temp_dir))

        assert result is not None
        assert len(result.testing) > 0

    def test_github_detects_dependabot(self, temp_dir):
        (temp_dir / ".github").mkdir()
        (temp_dir / ".github" / "dependabot.yml").write_text("version: 2")
        workflows = temp_dir / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text("name: CI")

        result = discover_ci_config(str(temp_dir))

        assert result is not None
        assert result.dependency_scanning == ".github/dependabot.yml"

    def test_detects_gitlab_ci(self, temp_dir):
        (temp_dir / ".gitlab-ci.yml").write_text("stages: [test]")

        result = discover_ci_config(str(temp_dir))

        assert result is not None
        assert result.provider == "gitlab"

    def test_detects_circleci(self, temp_dir):
        (temp_dir / ".circleci").mkdir()

        result = discover_ci_config(str(temp_dir))

        assert result is not None
        assert result.provider == "circleci"

    def test_detects_jenkins(self, temp_dir):
        (temp_dir / "Jenkinsfile").write_text("pipeline {}")

        result = discover_ci_config(str(temp_dir))

        assert result is not None
        assert result.provider == "jenkins"

    def test_detects_azure_pipelines(self, temp_dir):
        (temp_dir / "azure-pipelines.yml").write_text("trigger: [main]")

        result = discover_ci_config(str(temp_dir))

        assert result is not None
        assert result.provider == "azure"

    def test_github_preferred_over_others(self, temp_dir):
        """GitHub workflows directory takes precedence when detected first."""
        workflows = temp_dir / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text("name: CI")
        (temp_dir / ".gitlab-ci.yml").write_text("stages: [test]")

        result = discover_ci_config(str(temp_dir))

        assert result.provider == "github"


# ---------------------------------------------------------------------------
# discover_project_name
# ---------------------------------------------------------------------------


class TestDiscoverProjectName:
    def test_falls_back_to_directory_name(self, temp_dir):
        result = discover_project_name(str(temp_dir))

        assert result == os.path.basename(str(temp_dir))

    def test_reads_name_from_package_json(self, temp_dir):
        pkg = {"name": "my-js-project", "version": "1.0.0"}
        (temp_dir / "package.json").write_text(json.dumps(pkg))

        result = discover_project_name(str(temp_dir))

        assert result == "my-js-project"

    def test_ignores_malformed_package_json(self, temp_dir):
        (temp_dir / "package.json").write_text("not json {{{")

        # Should fall back to directory name without raising
        result = discover_project_name(str(temp_dir))

        assert result == os.path.basename(str(temp_dir))

    def test_reads_name_from_pyproject_toml(self, temp_dir):
        (temp_dir / "pyproject.toml").write_text(
            "[project]\nname = 'my-python-lib'\nversion = '0.1.0'\n"
        )

        result = discover_project_name(str(temp_dir))

        assert result == "my-python-lib"

    def test_reads_name_from_cargo_toml(self, temp_dir):
        (temp_dir / "Cargo.toml").write_text(
            "[package]\nname = 'my-rust-crate'\nversion = '0.1.0'\n"
        )

        result = discover_project_name(str(temp_dir))

        assert result == "my-rust-crate"

    def test_reads_module_name_from_go_mod(self, temp_dir):
        (temp_dir / "go.mod").write_text("module github.com/example/my-go-app\n\ngo 1.21\n")

        result = discover_project_name(str(temp_dir))

        assert result == "my-go-app"

    def test_package_json_takes_priority_over_pyproject(self, temp_dir):
        (temp_dir / "package.json").write_text(json.dumps({"name": "js-name"}))
        (temp_dir / "pyproject.toml").write_text("[project]\nname = 'py-name'\n")

        result = discover_project_name(str(temp_dir))

        assert result == "js-name"


# ---------------------------------------------------------------------------
# sync_discovered_to_config
# ---------------------------------------------------------------------------


class TestSyncDiscoveredToConfig:
    def test_reports_discovered_file_not_in_config(self, temp_dir):
        (temp_dir / "SECURITY.md").write_text("# Security")
        config = create_minimal_config(name="test-project")

        changes = sync_discovered_to_config(
            config,
            str(temp_dir),
            {"security.policy": ["SECURITY.md"]},
        )

        assert any("DISCOVERED" in c for c in changes)

    def test_fix_adds_discovered_file_to_config(self, temp_dir):
        (temp_dir / "SECURITY.md").write_text("# Security")
        config = create_minimal_config(name="test-project")

        sync_discovered_to_config(
            config,
            str(temp_dir),
            {"security.policy": ["SECURITY.md"]},
            fix=True,
        )

        assert config.security is not None
        assert config.security.policy is not None

    def test_reports_missing_declared_file(self, temp_dir):
        config = create_minimal_config(name="test-project")
        config.security = SecurityConfig(policy=PathRef(path="SECURITY.md"))

        changes = sync_discovered_to_config(
            config,
            str(temp_dir),
            {},
        )

        assert any("MISSING" in c for c in changes)

    def test_no_changes_when_config_matches_filesystem(self, temp_dir):
        (temp_dir / "SECURITY.md").write_text("# Security")
        config = create_minimal_config(name="test-project")
        config.security = SecurityConfig(policy=PathRef(path="SECURITY.md"))

        changes = sync_discovered_to_config(
            config,
            str(temp_dir),
            {"security.policy": ["SECURITY.md"]},
        )

        # No DISCOVERED or MISSING for this ref — already in config and exists
        policy_changes = [c for c in changes if "security.policy" in c]
        assert len(policy_changes) == 0

    def test_reports_ci_discovery(self, temp_dir):
        workflows = temp_dir / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text("name: CI")
        config = create_minimal_config(name="test-project")

        changes = sync_discovered_to_config(config, str(temp_dir))

        assert any("CI" in c for c in changes)


# ---------------------------------------------------------------------------
# discover_and_create_config
# ---------------------------------------------------------------------------


class TestDiscoverAndCreateConfig:
    def test_creates_config_with_discovered_name_from_package_json(self, temp_dir):
        (temp_dir / "package.json").write_text(json.dumps({"name": "cool-project"}))

        config = discover_and_create_config(str(temp_dir))

        assert config.name == "cool-project"

    def test_creates_config_with_provided_name(self, temp_dir):
        config = discover_and_create_config(str(temp_dir), name="explicit-name")

        assert config.name == "explicit-name"

    def test_config_local_path_set(self, temp_dir):
        config = discover_and_create_config(str(temp_dir))

        assert config.local_path == str(temp_dir)

    def test_discovered_files_added_to_config(self, temp_dir):
        (temp_dir / "SECURITY.md").write_text("# Security")

        config = discover_and_create_config(
            str(temp_dir),
            file_locations={"security.policy": ["SECURITY.md"]},
        )

        assert config.security is not None
        assert config.security.policy is not None
