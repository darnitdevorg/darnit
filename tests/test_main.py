"""Tests for darnit MCP server creation and CLI."""

import os

import pytest


class TestServerFactory:
    """Test that MCP server can be created from framework TOML."""

    def test_server_creates_from_framework(self):
        """Test that server can be created from openssf-baseline framework."""
        import tomllib

        from darnit.server.factory import create_server_from_dict
        from darnit_baseline import get_framework_path

        path = get_framework_path()
        with open(path, "rb") as f:
            config = tomllib.load(f)

        server = create_server_from_dict(config)
        assert server is not None
        assert "openssf-baseline" in server.name.lower() or "darnit" in server.name.lower()

    def test_framework_path_exists(self):
        """Test that framework TOML path is valid."""
        from darnit_baseline import get_framework_path

        path = get_framework_path()
        assert path.exists()
        assert path.suffix == ".toml"

    def test_framework_has_mcp_config(self):
        """Test that framework TOML has MCP configuration."""
        import tomllib

        from darnit_baseline import get_framework_path

        path = get_framework_path()
        with open(path, "rb") as f:
            config = tomllib.load(f)

        assert "mcp" in config
        assert "name" in config["mcp"]
        assert "tools" in config["mcp"]


class TestToolFunctions:
    """Test MCP tool functions from darnit_baseline package."""

    def test_audit_tool_exists(self):
        """Test audit_openssf_baseline tool is available."""
        from darnit_baseline.tools import audit_openssf_baseline
        assert callable(audit_openssf_baseline)

    def test_remediate_tool_exists(self):
        """Test remediate_audit_findings tool exists."""
        from darnit_baseline.tools import remediate_audit_findings
        assert callable(remediate_audit_findings)

    def test_attestation_tool_exists(self):
        """Test generate_attestation tool exists."""
        from darnit_baseline.tools import generate_attestation
        assert callable(generate_attestation)

    def test_threat_model_tool_exists(self):
        """Test generate_threat_model tool exists."""
        from darnit_baseline.tools import generate_threat_model
        assert callable(generate_threat_model)

    def test_project_config_tools_exist(self):
        """Test project config tools exist."""
        from darnit_baseline.tools import get_project_config, init_project_config
        assert callable(get_project_config)
        assert callable(init_project_config)


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
        from darnit_baseline.tools import audit_openssf_baseline

        result = audit_openssf_baseline(
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
        from darnit_baseline.tools import audit_openssf_baseline

        # Provide dummy owner/repo since auto-detect may not work in test env
        result = audit_openssf_baseline(
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
        from darnit_baseline.tools import get_project_config

        result = get_project_config(str(config_repo))
        # Should indicate no config exists or return empty/default
        assert isinstance(result, str)

    def test_init_project_config(self, config_repo):
        """Test initializing project config."""
        from darnit_baseline.tools import init_project_config

        result = init_project_config(str(config_repo))
        assert isinstance(result, str)


class TestCLI:
    """Test darnit CLI commands."""

    def test_cli_help(self):
        """Test that CLI --help works."""
        import subprocess
        result = subprocess.run(
            ["uv", "run", "darnit", "--help"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert "darnit" in result.stdout.lower()

    def test_cli_serve_help(self):
        """Test that serve subcommand help works."""
        import subprocess
        result = subprocess.run(
            ["uv", "run", "darnit", "serve", "--help"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert "framework" in result.stdout.lower()

    def test_cli_list_frameworks(self):
        """Test that list command shows available frameworks."""
        import subprocess
        result = subprocess.run(
            ["uv", "run", "darnit", "list"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert "openssf-baseline" in result.stdout.lower()
