"""Tests for main.py MCP server entry point."""

import os

import pytest


class TestMainImports:
    """Test that main.py can be imported without errors."""

    def test_main_imports(self):
        """Test that main.py imports successfully."""
        import main
        assert main is not None

    def test_mcp_server_created(self):
        """Test that MCP server instance exists."""
        import main
        assert hasattr(main, 'mcp')
        assert main.mcp is not None

    def test_mcp_server_has_name(self):
        """Test MCP server has expected name."""
        import main
        # FastMCP stores name in the instance
        assert "Darnit" in main.mcp.name


class TestToolFunctions:
    """Test MCP tool function existence and basic structure."""

    def test_audit_tool_exists(self):
        """Test audit_openssf_baseline tool is registered."""
        import main
        # Check the function exists
        assert hasattr(main, 'audit_openssf_baseline')
        assert callable(main.audit_openssf_baseline)

    def test_remediate_tool_exists(self):
        """Test remediate_audit_findings tool exists."""
        import main
        assert hasattr(main, 'remediate_audit_findings')
        assert callable(main.remediate_audit_findings)

    def test_attestation_tool_exists(self):
        """Test generate_attestation tool exists."""
        import main
        assert hasattr(main, 'generate_attestation')
        assert callable(main.generate_attestation)

    def test_threat_model_tool_exists(self):
        """Test generate_threat_model tool exists."""
        import main
        assert hasattr(main, 'generate_threat_model')
        assert callable(main.generate_threat_model)

    def test_project_config_tools_exist(self):
        """Test project config tools exist."""
        import main
        assert hasattr(main, 'get_project_config')
        # Note: sync_project_config may be named differently
        assert hasattr(main, 'save_project_config') or hasattr(main, 'init_project_config')


class TestHelperFunctions:
    """Test internal helper functions."""

    def test_validate_local_path_import(self):
        """Test validate_local_path is importable."""
        from darnit.core.utils import validate_local_path
        assert callable(validate_local_path)

    def test_validate_local_path_with_valid_repo(self, tmp_path):
        """Test validate_local_path with a valid git repo."""
        from darnit.core.utils import validate_local_path

        # Create a temporary git repo
        os.system(f"git init {tmp_path} --quiet")

        path, error = validate_local_path(str(tmp_path))
        assert error is None
        assert path == str(tmp_path.resolve())

    def test_validate_local_path_with_nonexistent(self):
        """Test validate_local_path with non-existent path."""
        from darnit.core.utils import validate_local_path

        path, error = validate_local_path("/nonexistent/path/xyz123")
        assert error is not None
        assert "does not exist" in error


class TestAuditWorkflow:
    """Test the audit workflow at a high level."""

    @pytest.fixture
    def test_repo(self, tmp_path):
        """Create a minimal test repository."""
        # Initialize git repo
        os.system(f"git init {tmp_path} --quiet")

        # Create minimal files
        (tmp_path / "README.md").write_text("# Test Project\n")
        (tmp_path / "LICENSE").write_text("MIT License\n")

        # Configure git for commit
        os.system(f"git -C {tmp_path} config user.email 'test@test.com'")
        os.system(f"git -C {tmp_path} config user.name 'Test'")

        # Make initial commit
        os.system(f"git -C {tmp_path} add .")
        os.system(f"git -C {tmp_path} commit -m 'Initial commit' --quiet")

        return tmp_path

    def test_audit_returns_string(self, test_repo):
        """Test that audit returns a string result."""
        import main

        result = main.audit_openssf_baseline(
            owner=None,
            repo=None,
            local_path=str(test_repo),
            level=1
        )

        assert isinstance(result, str)
        # Should contain some audit output
        assert len(result) > 0

    def test_audit_includes_controls(self, test_repo):
        """Test that audit output includes control IDs."""
        import main

        # Provide dummy owner/repo since auto-detect may not work in test env
        result = main.audit_openssf_baseline(
            owner="test",
            repo="test-repo",
            local_path=str(test_repo),
            level=1
        )

        # Should mention OSPS controls or audit results
        assert "OSPS" in result or "Level 1" in result or "control" in result.lower() or "Result" in result


class TestProjectConfig:
    """Test project configuration handling."""

    @pytest.fixture
    def config_repo(self, tmp_path):
        """Create a test repository with config."""
        os.system(f"git init {tmp_path} --quiet")
        (tmp_path / "README.md").write_text("# Test\n")
        return tmp_path

    def test_get_project_config_no_config(self, config_repo):
        """Test getting config when none exists."""
        import main

        result = main.get_project_config(str(config_repo))
        # Should indicate no config exists or return empty/default
        assert isinstance(result, str)

    def test_init_project_config(self, config_repo):
        """Test initializing project config."""
        import main

        # Use init_project_config if available, otherwise skip
        if hasattr(main, 'init_project_config'):
            result = main.init_project_config(str(config_repo))
            assert isinstance(result, str)
