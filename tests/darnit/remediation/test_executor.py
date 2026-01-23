"""Tests for the declarative remediation executor."""

import os
import tempfile
import pytest
from pathlib import Path

from darnit.remediation.executor import RemediationExecutor, RemediationResult
from darnit.config.framework_schema import (
    RemediationConfig,
    FileCreateRemediationConfig,
    ExecRemediationConfig,
    ApiCallRemediationConfig,
    TemplateConfig,
)


class TestRemediationResult:
    """Test RemediationResult dataclass."""

    def test_success_result(self):
        """Test creating a success result."""
        result = RemediationResult(
            success=True,
            message="File created: SECURITY.md",
            control_id="OSPS-VM-02.01",
            remediation_type="file_create",
            dry_run=False,
            details={"path": "SECURITY.md"},
        )
        assert result.success
        assert "File created" in result.message
        assert result.control_id == "OSPS-VM-02.01"

    def test_dry_run_result(self):
        """Test dry run result."""
        result = RemediationResult(
            success=True,
            message="Would create file: SECURITY.md",
            control_id="OSPS-VM-02.01",
            remediation_type="file_create",
            dry_run=True,
            details={"path": "SECURITY.md"},
        )
        assert result.dry_run
        assert "Would" in result.message

    def test_to_markdown(self):
        """Test markdown formatting."""
        result = RemediationResult(
            success=True,
            message="Created file",
            control_id="TEST-01",
            remediation_type="file_create",
            dry_run=False,
            details={"path": "test.md"},
        )
        md = result.to_markdown()
        assert "✅" in md
        assert "Created file" in md


class TestRemediationExecutor:
    """Test RemediationExecutor class."""

    def test_init_with_detection(self):
        """Test executor initialization."""
        executor = RemediationExecutor(
            local_path=".",
            owner="test-owner",
            repo="test-repo",
        )
        assert executor.owner == "test-owner"
        assert executor.repo == "test-repo"

    def test_variable_substitution(self):
        """Test variable substitution in templates."""
        executor = RemediationExecutor(
            local_path="/tmp/test",
            owner="myorg",
            repo="myrepo",
            default_branch="main",
        )

        text = "Contact security@$OWNER.github.io for $REPO issues"
        result = executor._substitute(text, "TEST-01")

        assert "security@myorg.github.io" in result
        assert "myrepo issues" in result

    def test_command_substitution(self):
        """Test variable substitution in commands."""
        executor = RemediationExecutor(
            local_path="/tmp/test-repo",
            owner="testorg",
            repo="testrepo",
            default_branch="main",
        )

        command = ["gh", "api", "/repos/$OWNER/$REPO/branches/$BRANCH"]
        result = executor._substitute_command(command, "TEST-01")

        assert result == ["gh", "api", "/repos/testorg/testrepo/branches/main"]


class TestFileCreateRemediation:
    """Test file creation remediations."""

    def test_file_create_dry_run(self):
        """Test file creation in dry run mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            templates = {
                "test_template": TemplateConfig(
                    content="# Test File\n\nContent for $REPO"
                )
            }

            executor = RemediationExecutor(
                local_path=tmpdir,
                owner="testorg",
                repo="testrepo",
                templates=templates,
            )

            config = RemediationConfig(
                file_create=FileCreateRemediationConfig(
                    path="TEST.md",
                    template="test_template",
                )
            )

            result = executor.execute("TEST-01", config, dry_run=True)

            assert result.success
            assert result.dry_run
            assert result.remediation_type == "file_create"
            assert "Would create" in result.message
            # File should NOT be created in dry run
            assert not os.path.exists(os.path.join(tmpdir, "TEST.md"))

    def test_file_create_actual(self):
        """Test actual file creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            templates = {
                "test_template": TemplateConfig(
                    content="# Test File\n\nContent for $REPO by $OWNER"
                )
            }

            executor = RemediationExecutor(
                local_path=tmpdir,
                owner="testorg",
                repo="testrepo",
                templates=templates,
            )

            config = RemediationConfig(
                file_create=FileCreateRemediationConfig(
                    path="TEST.md",
                    template="test_template",
                )
            )

            result = executor.execute("TEST-01", config, dry_run=False)

            assert result.success
            assert not result.dry_run
            assert result.remediation_type == "file_create"

            # Verify file was created
            file_path = os.path.join(tmpdir, "TEST.md")
            assert os.path.exists(file_path)

            with open(file_path) as f:
                content = f.read()
            assert "testrepo" in content
            assert "testorg" in content

    def test_file_create_no_overwrite(self):
        """Test that existing files are not overwritten when overwrite=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create existing file
            existing_path = os.path.join(tmpdir, "EXISTING.md")
            with open(existing_path, "w") as f:
                f.write("Original content")

            templates = {
                "test_template": TemplateConfig(content="New content")
            }

            executor = RemediationExecutor(
                local_path=tmpdir,
                templates=templates,
            )

            config = RemediationConfig(
                file_create=FileCreateRemediationConfig(
                    path="EXISTING.md",
                    template="test_template",
                    overwrite=False,
                )
            )

            result = executor.execute("TEST-01", config, dry_run=False)

            assert not result.success
            assert "already exists" in result.message

            # Verify original content is preserved
            with open(existing_path) as f:
                assert f.read() == "Original content"

    def test_file_create_with_dirs(self):
        """Test file creation with directory creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            templates = {
                "test_template": TemplateConfig(content="Template content")
            }

            executor = RemediationExecutor(
                local_path=tmpdir,
                templates=templates,
            )

            config = RemediationConfig(
                file_create=FileCreateRemediationConfig(
                    path=".github/ISSUE_TEMPLATE/bug.md",
                    template="test_template",
                    create_dirs=True,
                )
            )

            result = executor.execute("TEST-01", config, dry_run=False)

            assert result.success
            file_path = os.path.join(tmpdir, ".github/ISSUE_TEMPLATE/bug.md")
            assert os.path.exists(file_path)


class TestExecRemediation:
    """Test command execution remediations."""

    def test_exec_dry_run(self):
        """Test command execution in dry run mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = RemediationExecutor(
                local_path=tmpdir,
                owner="testorg",
                repo="testrepo",
            )

            config = RemediationConfig(
                exec=ExecRemediationConfig(
                    command=["echo", "Hello", "$OWNER"],
                )
            )

            result = executor.execute("TEST-01", config, dry_run=True)

            assert result.success
            assert result.dry_run
            assert result.remediation_type == "exec"
            assert "Would execute" in result.message

    def test_exec_actual(self):
        """Test actual command execution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = RemediationExecutor(
                local_path=tmpdir,
                owner="testorg",
                repo="testrepo",
            )

            config = RemediationConfig(
                exec=ExecRemediationConfig(
                    command=["echo", "test output"],
                    success_exit_codes=[0],
                )
            )

            result = executor.execute("TEST-01", config, dry_run=False)

            assert result.success
            assert not result.dry_run
            assert result.remediation_type == "exec"
            assert result.details.get("exit_code") == 0

    def test_exec_failure(self):
        """Test command execution failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = RemediationExecutor(local_path=tmpdir)

            config = RemediationConfig(
                exec=ExecRemediationConfig(
                    command=["false"],  # Always exits with 1
                    success_exit_codes=[0],
                )
            )

            result = executor.execute("TEST-01", config, dry_run=False)

            assert not result.success
            assert result.details.get("exit_code") == 1


class TestApiCallRemediation:
    """Test API call remediations."""

    def test_api_call_dry_run(self):
        """Test API call in dry run mode."""
        executor = RemediationExecutor(
            local_path=".",
            owner="testorg",
            repo="testrepo",
            default_branch="main",
        )

        config = RemediationConfig(
            api_call=ApiCallRemediationConfig(
                method="PUT",
                endpoint="/repos/$OWNER/$REPO/branches/$BRANCH/protection",
            )
        )

        result = executor.execute("OSPS-AC-03.01", config, dry_run=True)

        assert result.success
        assert result.dry_run
        assert result.remediation_type == "api_call"
        assert "Would call GitHub API" in result.message
        assert "/repos/testorg/testrepo/branches/main/protection" in result.details["endpoint"]


class TestNoRemediationConfig:
    """Test handling of missing remediation configs."""

    def test_legacy_handler_reference(self):
        """Test that legacy handler references return appropriate message."""
        executor = RemediationExecutor(local_path=".")

        config = RemediationConfig(
            handler="some_legacy_function"
        )

        result = executor.execute("TEST-01", config, dry_run=True)

        assert not result.success
        assert result.remediation_type == "handler"
        assert "Legacy handler" in result.message

    def test_no_action_configured(self):
        """Test handling when no remediation action is configured."""
        executor = RemediationExecutor(local_path=".")

        config = RemediationConfig()

        result = executor.execute("TEST-01", config, dry_run=True)

        assert not result.success
        assert result.remediation_type == "none"
        assert "No remediation action" in result.message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
