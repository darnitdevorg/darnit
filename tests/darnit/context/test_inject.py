from __future__ import annotations

from unittest.mock import MagicMock, patch

from darnit.context.inject import (
    create_check_context_with_project,
    get_project_value,
    has_project_value,
    inject_project_context,
)
from darnit.sieve.models import CheckContext


class TestInjectProjectContext:
    """Tests for inject_project_context function."""

    def test_inject_project_context_success(self):
        """Test successful injection of project context."""
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
        )

        mock_context_data = {
            "project.name": "Test Project",
            "project.security.policy_path": ".github/SECURITY.md",
            "project.maintainers": ["@alice", "@bob"],
        }

        with patch("darnit.context.inject.DotProjectMapper") as mock_mapper_class:
            mock_mapper = MagicMock()
            mock_mapper.get_context.return_value = mock_context_data
            mock_mapper_class.return_value = mock_mapper

            inject_project_context(context)

            assert context.project_context == mock_context_data
            mock_mapper_class.assert_called_once_with("/tmp/repo", owner="test-org")
            mock_mapper.get_context.assert_called_once()

    def test_inject_project_context_empty_owner(self):
        """Test injection with empty owner string."""
        context = CheckContext(
            owner="",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
        )

        mock_context_data = {"project.name": "Test Project"}

        with patch("darnit.context.inject.DotProjectMapper") as mock_mapper_class:
            mock_mapper = MagicMock()
            mock_mapper.get_context.return_value = mock_context_data
            mock_mapper_class.return_value = mock_mapper

            inject_project_context(context)

            assert context.project_context == mock_context_data
            mock_mapper_class.assert_called_once_with("/tmp/repo", owner="")

    def test_inject_project_context_missing_owner_attribute(self):
        """Test injection when context has no owner attribute."""
        context = CheckContext(
            owner=None,
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
        )

        mock_context_data = {"project.security.policy_path": "SECURITY.md"}

        with patch("darnit.context.inject.DotProjectMapper") as mock_mapper_class:
            mock_mapper = MagicMock()
            mock_mapper.get_context.return_value = mock_context_data
            mock_mapper_class.return_value = mock_mapper

            inject_project_context(context)

            assert context.project_context == mock_context_data
            mock_mapper_class.assert_called_once_with("/tmp/repo", owner="")

    def test_inject_project_context_empty_dict(self):
        """Test injection when no project context is available."""
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
        )

        with patch("darnit.context.inject.DotProjectMapper") as mock_mapper_class:
            mock_mapper = MagicMock()
            mock_mapper.get_context.return_value = {}
            mock_mapper_class.return_value = mock_mapper

            inject_project_context(context)

            assert context.project_context == {}

    def test_inject_project_context_mapper_exception(self):
        """Test injection handles DotProjectMapper exceptions gracefully."""
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
        )

        with patch("darnit.context.inject.DotProjectMapper") as mock_mapper_class:
            mock_mapper_class.side_effect = RuntimeError("Config read failed")

            inject_project_context(context)

            assert context.project_context == {}

    def test_inject_project_context_get_context_exception(self):
        """Test injection handles get_context exceptions gracefully."""
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
        )

        with patch("darnit.context.inject.DotProjectMapper") as mock_mapper_class:
            mock_mapper = MagicMock()
            mock_mapper.get_context.side_effect = ValueError("Invalid YAML")
            mock_mapper_class.return_value = mock_mapper

            inject_project_context(context)

            assert context.project_context == {}

    def test_inject_project_context_logging_on_success(self, caplog):
        """Test logging on successful injection with context."""
        import logging

        caplog.set_level(logging.DEBUG)
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
        )

        mock_context_data = {
            "project.name": "Test",
            "project.security.policy_path": "SECURITY.md",
        }

        with patch("darnit.context.inject.DotProjectMapper") as mock_mapper_class:
            mock_mapper = MagicMock()
            mock_mapper.get_context.return_value = mock_context_data
            mock_mapper_class.return_value = mock_mapper

            inject_project_context(context)

            assert any("Injected 2 .project/" in record.message for record in caplog.records)

    def test_inject_project_context_logging_on_empty(self, caplog):
        """Test logging when no project context is available."""
        import logging

        caplog.set_level(logging.DEBUG)
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
        )

        with patch("darnit.context.inject.DotProjectMapper") as mock_mapper_class:
            mock_mapper = MagicMock()
            mock_mapper.get_context.return_value = {}
            mock_mapper_class.return_value = mock_mapper

            inject_project_context(context)

            assert any("No .project/ context available" in record.message for record in caplog.records)

    def test_inject_project_context_logging_on_exception(self, caplog):
        """Test logging when exception occurs during injection."""
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
        )

        with patch("darnit.context.inject.DotProjectMapper") as mock_mapper_class:
            mock_mapper_class.side_effect = OSError("Permission denied")

            inject_project_context(context)

            assert any("Failed to inject .project/ context" in record.message for record in caplog.records)


class TestCreateCheckContextWithProject:
    """Tests for create_check_context_with_project function."""

    def test_create_check_context_basic(self):
        """Test creating CheckContext with basic parameters."""
        mock_context_data = {"project.name": "Test Project"}

        with patch("darnit.context.inject.DotProjectMapper") as mock_mapper_class:
            mock_mapper = MagicMock()
            mock_mapper.get_context.return_value = mock_context_data
            mock_mapper_class.return_value = mock_mapper

            context = create_check_context_with_project(
                owner="test-org",
                repo="test-repo",
                local_path="/tmp/repo",
                default_branch="main",
                control_id="OSPS-AC-01.01",
            )

            assert isinstance(context, CheckContext)
            assert context.owner == "test-org"
            assert context.repo == "test-repo"
            assert context.local_path == "/tmp/repo"
            assert context.default_branch == "main"
            assert context.control_id == "OSPS-AC-01.01"
            assert context.project_context == mock_context_data

    def test_create_check_context_with_metadata(self):
        """Test creating CheckContext with control metadata."""
        metadata = {"level": 1, "severity": "HIGH"}
        mock_context_data = {"project.security.policy_path": "SECURITY.md"}

        with patch("darnit.context.inject.DotProjectMapper") as mock_mapper_class:
            mock_mapper = MagicMock()
            mock_mapper.get_context.return_value = mock_context_data
            mock_mapper_class.return_value = mock_mapper

            context = create_check_context_with_project(
                owner="my-org",
                repo="my-repo",
                local_path="/tmp/my-repo",
                default_branch="main",
                control_id="OSPS-CM-01.01",
                control_metadata=metadata,
            )

            assert context.control_metadata == metadata
            assert context.project_context == mock_context_data

    def test_create_check_context_without_metadata(self):
        """Test creating CheckContext without metadata defaults to empty dict."""
        with patch("darnit.context.inject.DotProjectMapper") as mock_mapper_class:
            mock_mapper = MagicMock()
            mock_mapper.get_context.return_value = {}
            mock_mapper_class.return_value = mock_mapper

            context = create_check_context_with_project(
                owner="test-org",
                repo="test-repo",
                local_path="/tmp/repo",
                default_branch="main",
                control_id="OSPS-AC-01.01",
                control_metadata=None,
            )

            assert context.control_metadata == {}

    def test_create_check_context_injects_context(self):
        """Test that created context has project_context injected."""
        mock_context_data = {
            "project.name": "Test",
            "project.maintainers": ["@alice"],
            "project.security.policy_path": "SECURITY.md",
        }

        with patch("darnit.context.inject.DotProjectMapper") as mock_mapper_class:
            mock_mapper = MagicMock()
            mock_mapper.get_context.return_value = mock_context_data
            mock_mapper_class.return_value = mock_mapper

            context = create_check_context_with_project(
                owner="test-org",
                repo="test-repo",
                local_path="/tmp/repo",
                default_branch="main",
                control_id="OSPS-AC-01.01",
            )

            assert len(context.project_context) == 3
            assert context.project_context["project.name"] == "Test"
            assert context.project_context["project.maintainers"] == ["@alice"]


class TestGetProjectValue:
    """Tests for get_project_value function."""

    def test_get_project_value_exists(self):
        """Test retrieving an existing project context value."""
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
            project_context={
                "project.security.policy_path": "SECURITY.md",
                "project.maintainers": ["@alice"],
            },
        )

        value = get_project_value(context, "project.security.policy_path")
        assert value == "SECURITY.md"

    def test_get_project_value_missing_with_default(self):
        """Test retrieving missing value with default."""
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
            project_context={"project.name": "Test"},
        )

        value = get_project_value(context, "project.missing.value", default="DEFAULT")
        assert value == "DEFAULT"

    def test_get_project_value_missing_without_default(self):
        """Test retrieving missing value without default returns None."""
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
            project_context={},
        )

        value = get_project_value(context, "project.missing.value")
        assert value is None

    def test_get_project_value_empty_project_context(self):
        """Test retrieving value from empty project_context."""
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
            project_context={},
        )

        value = get_project_value(context, "project.any.key", default="FALLBACK")
        assert value == "FALLBACK"

    def test_get_project_value_list_type(self):
        """Test retrieving list value from project_context."""
        maintainers = ["@alice", "@bob", "@charlie"]
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
            project_context={"project.maintainers": maintainers},
        )

        value = get_project_value(context, "project.maintainers")
        assert value == maintainers
        assert isinstance(value, list)

    def test_get_project_value_dict_type(self):
        """Test retrieving dict value from project_context."""
        repo_info = {"url": "https://github.com/test/repo", "visibility": "public"}
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
            project_context={"project.repo": repo_info},
        )

        value = get_project_value(context, "project.repo")
        assert value == repo_info
        assert isinstance(value, dict)

    def test_get_project_value_numeric_type(self):
        """Test retrieving numeric value from project_context."""
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
            project_context={"project.version": 42},
        )

        value = get_project_value(context, "project.version")
        assert value == 42
        assert isinstance(value, int)


class TestHasProjectValue:
    """Tests for has_project_value function."""

    def test_has_project_value_exists(self):
        """Test checking for existing project value."""
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
            project_context={"project.security.policy_path": "SECURITY.md"},
        )

        assert has_project_value(context, "project.security.policy_path") is True

    def test_has_project_value_missing(self):
        """Test checking for missing project value."""
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
            project_context={"project.name": "Test"},
        )

        assert has_project_value(context, "project.missing.value") is False

    def test_has_project_value_empty_context(self):
        """Test checking for value in empty project_context."""
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
            project_context={},
        )

        assert has_project_value(context, "project.anything") is False

    def test_has_project_value_multiple_keys(self):
        """Test checking multiple keys in project_context."""
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
            project_context={
                "project.security.policy_path": "SECURITY.md",
                "project.maintainers": ["@alice"],
                "project.name": "Test Project",
            },
        )

        assert has_project_value(context, "project.security.policy_path") is True
        assert has_project_value(context, "project.maintainers") is True
        assert has_project_value(context, "project.name") is True
        assert has_project_value(context, "project.other.key") is False

    def test_has_project_value_with_none_value(self):
        """Test checking for key with None value."""
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
            project_context={"project.optional_field": None},
        )

        assert has_project_value(context, "project.optional_field") is True

    def test_has_project_value_with_empty_value(self):
        """Test checking for key with empty string value."""
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
            project_context={"project.empty_field": ""},
        )

        assert has_project_value(context, "project.empty_field") is True


class TestIntegrationScenarios:
    """Integration tests with multiple functions working together."""

    def test_full_workflow_create_and_query(self):
        """Test full workflow: create context and query values."""
        mock_context_data = {
            "project.name": "MyProject",
            "project.security.policy_path": "SECURITY.md",
            "project.maintainers": ["@alice", "@bob"],
        }

        with patch("darnit.context.inject.DotProjectMapper") as mock_mapper_class:
            mock_mapper = MagicMock()
            mock_mapper.get_context.return_value = mock_context_data
            mock_mapper_class.return_value = mock_mapper

            context = create_check_context_with_project(
                owner="test-org",
                repo="test-repo",
                local_path="/tmp/repo",
                default_branch="main",
                control_id="OSPS-AC-01.01",
            )

            assert has_project_value(context, "project.name") is True
            assert get_project_value(context, "project.name") == "MyProject"
            assert get_project_value(context, "project.security.policy_path") == "SECURITY.md"
            assert get_project_value(context, "project.maintainers") == [
                "@alice",
                "@bob",
            ]
            assert has_project_value(context, "project.missing") is False

    def test_workflow_with_exception_fallback(self):
        """Test workflow when context injection fails gracefully."""
        with patch("darnit.context.inject.DotProjectMapper") as mock_mapper_class:
            mock_mapper_class.side_effect = RuntimeError("File not found")

            context = create_check_context_with_project(
                owner="test-org",
                repo="test-repo",
                local_path="/tmp/repo",
                default_branch="main",
                control_id="OSPS-AC-01.01",
            )

            assert context.project_context == {}
            assert has_project_value(context, "project.anything") is False
            assert get_project_value(context, "project.anything", "DEFAULT") == "DEFAULT"

    def test_workflow_manual_injection_then_query(self):
        """Test manually injecting context and then querying."""
        context = CheckContext(
            owner="test-org",
            repo="test-repo",
            local_path="/tmp/repo",
            default_branch="main",
            control_id="OSPS-AC-01.01",
        )

        mock_context_data = {"project.security.policy_path": "SECURITY.md"}

        with patch("darnit.context.inject.DotProjectMapper") as mock_mapper_class:
            mock_mapper = MagicMock()
            mock_mapper.get_context.return_value = mock_context_data
            mock_mapper_class.return_value = mock_mapper

            inject_project_context(context)

            assert has_project_value(context, "project.security.policy_path") is True
            assert get_project_value(context, "project.security.policy_path") == "SECURITY.md"
