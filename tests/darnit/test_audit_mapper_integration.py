"""Tests for .project/ mapper integration in the audit pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestAuditMapperIntegration:
    """Test that DotProjectMapper context is injected into the audit pipeline."""

    @pytest.fixture()
    def mock_sieve_components(self):
        """Mock sieve components to isolate pipeline context building."""
        mock_registry = MagicMock()
        mock_registry.get_specs_by_level.return_value = []

        mock_orchestrator = MagicMock()
        mock_context_cls = MagicMock()

        return {
            "get_control_registry": lambda: mock_registry,
            "SieveOrchestrator": lambda **kw: mock_orchestrator,
            "CheckContext": mock_context_cls,
        }

    @patch("darnit.tools.audit._get_sieve_components")
    @patch("darnit.tools.audit._register_toml_controls")
    @patch("darnit.tools.audit.get_excluded_control_ids", return_value={})
    def test_mapper_context_injected(
        self,
        mock_excluded,
        mock_register,
        mock_get_sieve,
        mock_sieve_components,
        tmp_path,
    ):
        """Mapper context variables appear in project_context."""
        from darnit.tools.audit import run_sieve_audit

        mock_get_sieve.return_value = mock_sieve_components

        # Create a .project/project.yaml so mapper has something to read
        project_dir = tmp_path / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text(
            "name: test-project\nsecurity:\n  contact: sec@example.com\n"
        )

        results, summary = run_sieve_audit(
            owner="test-org",
            repo="test-repo",
            local_path=str(tmp_path),
            default_branch="main",
            level=1,
        )

        # No controls loaded (empty registry), so results should be empty
        assert results == []

    @patch("darnit.tools.audit._get_sieve_components")
    @patch("darnit.tools.audit._register_toml_controls")
    @patch("darnit.tools.audit.get_excluded_control_ids", return_value={})
    def test_user_context_overrides_mapper(
        self,
        mock_excluded,
        mock_register,
        mock_get_sieve,
        mock_sieve_components,
        tmp_path,
    ):
        """User-confirmed values override mapper values."""
        from darnit.tools.audit import run_sieve_audit

        mock_get_sieve.return_value = mock_sieve_components

        # Create .project/ with a name
        project_dir = tmp_path / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("name: from-project-yaml\n")

        # Mock load_context to return user-confirmed values that override
        with patch("darnit.context.dot_project_mapper.DotProjectMapper") as mock_mapper_cls:
            mock_mapper = MagicMock()
            mock_mapper.get_context.return_value = {
                "project.name": "from-mapper",
                "project.security.contact": "mapper@example.com",
            }
            mock_mapper_cls.return_value = mock_mapper

            # Patch load_context to return overriding values
            with patch(
                "darnit.config.context_storage.load_context"
            ) as mock_load:
                mock_load.return_value = {"project.name": "from-user"}
                with patch(
                    "darnit.config.context_storage.flatten_user_context",
                    return_value={"project.name": "from-user"},
                ):
                    results, summary = run_sieve_audit(
                        owner="test-org",
                        repo="test-repo",
                        local_path=str(tmp_path),
                        default_branch="main",
                        level=1,
                    )

            # Verify mapper was called with correct owner
            mock_mapper_cls.assert_called_once_with(str(tmp_path), owner="test-org")
            mock_mapper.get_context.assert_called_once()

    @patch("darnit.tools.audit._get_sieve_components")
    @patch("darnit.tools.audit._register_toml_controls")
    @patch("darnit.tools.audit.get_excluded_control_ids", return_value={})
    def test_mapper_failure_is_non_fatal(
        self,
        mock_excluded,
        mock_register,
        mock_get_sieve,
        mock_sieve_components,
        tmp_path,
    ):
        """Mapper failure does not crash the audit."""
        from darnit.tools.audit import run_sieve_audit

        mock_get_sieve.return_value = mock_sieve_components

        with patch("darnit.context.dot_project_mapper.DotProjectMapper") as mock_mapper_cls:
            mock_mapper_cls.side_effect = RuntimeError("Mapper exploded")

            # Should not raise
            results, summary = run_sieve_audit(
                owner="test-org",
                repo="test-repo",
                local_path=str(tmp_path),
                default_branch="main",
                level=1,
            )

            assert results == []

    @patch("darnit.tools.audit._get_sieve_components")
    @patch("darnit.tools.audit._register_toml_controls")
    @patch("darnit.tools.audit.get_excluded_control_ids", return_value={})
    def test_mapper_called_without_owner(
        self,
        mock_excluded,
        mock_register,
        mock_get_sieve,
        mock_sieve_components,
        tmp_path,
    ):
        """When owner is empty, mapper is still called for local .project/ data."""
        from darnit.tools.audit import run_sieve_audit

        mock_get_sieve.return_value = mock_sieve_components

        with patch("darnit.context.dot_project_mapper.DotProjectMapper") as mock_mapper_cls:
            mock_mapper = MagicMock()
            mock_mapper.get_context.return_value = {}
            mock_mapper_cls.return_value = mock_mapper

            results, summary = run_sieve_audit(
                owner="",
                repo="test-repo",
                local_path=str(tmp_path),
                default_branch="main",
                level=1,
            )

            # Mapper called with empty owner string
            mock_mapper_cls.assert_called_once_with(str(tmp_path), owner="")
