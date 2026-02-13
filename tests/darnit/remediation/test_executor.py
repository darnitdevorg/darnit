"""Tests for the declarative remediation executor."""

import tempfile

import pytest

from darnit.config.framework_schema import (
    HandlerInvocation,
    RemediationConfig,
)
from darnit.remediation.executor import RemediationExecutor, RemediationResult


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

    def test_context_list_substitution_uses_spaces(self):
        """Test that list context values are joined with spaces (not commas).

        This is important for CODEOWNERS format which requires space-separated owners.
        """
        executor = RemediationExecutor(
            local_path="/tmp/test",
            owner="myorg",
            repo="myrepo",
        )
        executor._context_values = {
            "maintainers": ["@alice", "@bob", "@charlie"],
        }

        text = "* ${context.maintainers}"
        result = executor._substitute(text, "TEST-01")

        assert result == "* @alice @bob @charlie"

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


class TestHandlerPipelineRemediation:
    """Test handler pipeline based remediations."""

    def test_handler_dry_run(self):
        """Test handler pipeline in dry run mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = RemediationExecutor(
                local_path=tmpdir,
                owner="testorg",
                repo="testrepo",
            )

            config = RemediationConfig(
                handlers=[
                    HandlerInvocation(
                        handler="file_create",
                        path="TEST.md",
                        template="test_template",
                    ),
                ],
            )

            result = executor.execute("TEST-01", config, dry_run=True)

            assert result.success
            assert result.dry_run
            assert result.remediation_type == "handler_pipeline"
            assert "Would execute" in result.message

    def test_multiple_handlers_dry_run(self):
        """Test multiple handlers in dry run mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = RemediationExecutor(
                local_path=tmpdir,
                owner="testorg",
                repo="testrepo",
            )

            config = RemediationConfig(
                handlers=[
                    HandlerInvocation(
                        handler="file_create",
                        path="README.md",
                        template="readme_template",
                    ),
                    HandlerInvocation(
                        handler="file_create",
                        path="LICENSE",
                        template="license_template",
                    ),
                ],
            )

            result = executor.execute("TEST-01", config, dry_run=True)

            assert result.success
            assert result.dry_run
            assert "2 remediation handler(s)" in result.message

    def test_unknown_handler_fails(self):
        """Test that referencing an unknown handler returns failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = RemediationExecutor(
                local_path=tmpdir,
                owner="testorg",
                repo="testrepo",
            )

            config = RemediationConfig(
                handlers=[
                    HandlerInvocation(
                        handler="nonexistent_handler",
                    ),
                ],
            )

            # Dry run skips handler lookup, so test non-dry-run
            result = executor.execute("TEST-01", config, dry_run=False)

            assert not result.success
            details = result.details.get("handlers", [])
            assert any("not found" in h.get("message", "") for h in details)


class TestNoRemediationConfig:
    """Test handling of missing remediation configs."""

    def test_no_handlers_configured(self):
        """Test handling when no remediation handlers are configured."""
        executor = RemediationExecutor(local_path=".")

        config = RemediationConfig()

        result = executor.execute("TEST-01", config, dry_run=True)

        assert not result.success
        assert result.remediation_type == "none"
        assert "No remediation handlers configured" in result.message

    def test_empty_handlers_list(self):
        """Test handling when handlers list is explicitly empty."""
        executor = RemediationExecutor(local_path=".")

        config = RemediationConfig(handlers=[])

        result = executor.execute("TEST-01", config, dry_run=True)

        assert not result.success
        assert result.remediation_type == "none"


class TestHandlerInconclusiveHandling:
    """Test that INCONCLUSIVE from manual handlers does not cause failure."""

    def test_file_create_pass_plus_manual_inconclusive_succeeds(self):
        """Remediation with file_create (PASS) + manual (INCONCLUSIVE) returns success=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = RemediationExecutor(
                local_path=tmpdir,
                owner="testorg",
                repo="testrepo",
            )

            config = RemediationConfig(
                handlers=[
                    HandlerInvocation(
                        handler="file_create",
                        path="TEST.md",
                        content="# Test file",
                    ),
                    HandlerInvocation(
                        handler="manual",
                        steps=["Review the created file"],
                    ),
                ],
            )

            result = executor.execute("TEST-01", config, dry_run=False)

            assert result.success
            assert result.remediation_type == "handler_pipeline"
            handlers = result.details.get("handlers", [])
            assert len(handlers) == 2
            assert handlers[0]["status"] == "pass"
            assert handlers[1]["status"] == "inconclusive"

    def test_handler_returning_fail_causes_failure(self):
        """Remediation with a handler returning FAIL returns success=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = RemediationExecutor(
                local_path=tmpdir,
                owner="testorg",
                repo="testrepo",
            )

            # file_create with no content and no template → ERROR
            config = RemediationConfig(
                handlers=[
                    HandlerInvocation(
                        handler="file_create",
                        path="TEST.md",
                    ),
                ],
            )

            result = executor.execute("TEST-01", config, dry_run=False)

            assert not result.success

    def test_only_manual_handlers_succeeds(self):
        """Remediation with only manual handlers (INCONCLUSIVE) returns success=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = RemediationExecutor(
                local_path=tmpdir,
                owner="testorg",
                repo="testrepo",
            )

            config = RemediationConfig(
                handlers=[
                    HandlerInvocation(
                        handler="manual",
                        steps=["Step 1: Do something", "Step 2: Verify"],
                    ),
                ],
            )

            result = executor.execute("TEST-01", config, dry_run=False)

            assert result.success
            handlers = result.details.get("handlers", [])
            assert len(handlers) == 1
            assert handlers[0]["status"] == "inconclusive"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
