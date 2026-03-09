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


class TestHelperFunctions:
    """Test internal helper functions."""

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

    def test_cli_version(self):
        """Test that --version flag prints the version."""
        import subprocess
        result = subprocess.run(
            ["uv", "run", "darnit", "--version"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert "darnit" in result.stdout.lower()

    def test_cli_version_short_flag(self):
        """Test that -V flag prints the version."""
        import subprocess
        result = subprocess.run(
            ["uv", "run", "darnit", "-V"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert "darnit" in result.stdout.lower()

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
