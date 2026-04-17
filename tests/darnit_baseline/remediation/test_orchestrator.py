from unittest.mock import patch

import pytest

from darnit.config.framework_schema import (
    ControlConfig,
    FrameworkConfig,
    FrameworkMetadata,
    HandlerInvocation,
    RemediationConfig,
    TemplateConfig,
)
from darnit.remediation.executor import RemediationResult
from darnit_baseline.remediation.orchestrator import (
    _apply_declarative_remediation,
    remediate_audit_findings,
)


@pytest.fixture
def mock_framework() -> FrameworkConfig:
    """Provide a minimal FrameworkConfig for testing orchestrator."""
    framework = FrameworkConfig(
        metadata=FrameworkMetadata(name="Test", display_name="Test", version="1.0"),
        controls={
            "OSPS-GV-01.01": ControlConfig(
                name="Governance",
                description="Test Governance Control",
                level="1",
                passes=[],
                remediation=RemediationConfig(
                    type="declarative",
                    strategy="first_match",
                    handlers=[HandlerInvocation(handler="file_create", path="GOVERNANCE.md", template="test_template")],
                    project_update={"governance": "updated"},
                ),
            ),
            "OSPS-AC-01.01": ControlConfig(
                name="Access Control",
                description="Test Access Control - Error Path",
                level="1",
                passes=[],
                remediation=RemediationConfig(
                    type="declarative",
                    strategy="all",
                    handlers=[
                        HandlerInvocation(handler="error_handler"),
                        HandlerInvocation(handler="file_create", path="NEVER.md"),
                    ],
                ),
            ),
        },
        templates={"test_template": TemplateConfig(content="Test content with vars: {{ project.governance }}")},
    )
    return framework


# ---------------------------------------------------------
# Phase 1: Happy Path & Template Resolution / Executor
# ---------------------------------------------------------


@patch("darnit_baseline.remediation.orchestrator._get_framework_config")
@patch("darnit_baseline.remediation.orchestrator.RemediationExecutor")
@patch("darnit.core.audit_cache.read_audit_cache")
@patch("darnit_baseline.remediation.orchestrator._preflight_context_check")
def test_remediate_audit_findings_happy_path(
    mock_preflight,
    mock_read_cache,
    mock_executor_class,
    mock_get_framework,
    mock_framework,
    temp_git_repo,
):
    """Test successful remediation of a single failing control."""
    # Setup mocks
    mock_get_framework.return_value = mock_framework

    mock_read_cache.return_value = {
        "results": [
            {"id": "OSPS-GV-01.01", "status": "FAIL"},
            {"id": "OSPS-AC-01.01", "status": "PASS"},  # Should be ignored
        ]
    }

    # Pre-flight check passes
    mock_preflight.return_value = (True, [])

    # Mock executor.execute
    mock_executor = mock_executor_class.return_value
    mock_executor.execute.return_value = RemediationResult(
        success=True,
        control_id="OSPS-GV-01.01",
        remediation_type="declarative",
        message="Created GOVERNANCE.md",
        dry_run=False,
        details={"handlers": [{"handler": "file_create", "status": "pass"}]},
    )

    # Execute
    result_markdown = remediate_audit_findings(
        local_path=str(temp_git_repo), owner="test-owner", repo="test-repo", dry_run=False, enhance_with_llm=False
    )

    # Assert
    assert "✅" in result_markdown
    assert "OSPS-GV-01.01" in result_markdown
    mock_executor.execute.assert_called_once()

    call_args = mock_executor.execute.call_args[1]
    assert call_args["control_id"] == "OSPS-GV-01.01"
    assert call_args["dry_run"] is False


@patch("darnit_baseline.remediation.orchestrator._apply_project_update")
@patch("darnit_baseline.remediation.orchestrator.RemediationExecutor")
def test_apply_declarative_remediation_project_update(
    mock_executor_class,
    mock_apply_project_update,
    mock_framework,
    temp_git_repo,
):
    """Test that a successful declarative remediation applies project_update config."""
    # We want to verify _apply_project_update actually mutates the yaml
    mock_executor = mock_executor_class.return_value
    mock_executor.execute.return_value = RemediationResult(
        success=True,
        control_id="OSPS-GV-01.01",
        remediation_type="declarative",
        message="Success",
        dry_run=False,
        details={},
    )

    control = mock_framework.controls["OSPS-GV-01.01"]

    result = _apply_declarative_remediation(
        control_id="OSPS-GV-01.01",
        remediation_config=control.remediation,
        templates=mock_framework.templates,
        local_path=str(temp_git_repo),
        owner="owner",
        repo="repo",
        dry_run=False,
    )

    assert result["status"] == "applied"

    # Verify the project update function was called
    mock_apply_project_update.assert_called_once_with(
        str(temp_git_repo), mock_framework.controls["OSPS-GV-01.01"].remediation.project_update, "OSPS-GV-01.01"
    )


# ---------------------------------------------------------
# Phase 3: Error Recovery
# ---------------------------------------------------------


@patch("darnit_baseline.remediation.orchestrator.RemediationExecutor")
def test_apply_declarative_remediation_error_recovery(
    mock_executor_class,
    mock_framework,
    temp_git_repo,
):
    """Test that handler exceptions are cleanly caught and turned into error statuses."""
    mock_executor = mock_executor_class.return_value
    mock_executor.execute.side_effect = ValueError("Jinja template rendering failed")

    control = mock_framework.controls["OSPS-GV-01.01"]

    # This should not raise an exception
    result = _apply_declarative_remediation(
        control_id="OSPS-GV-01.01",
        remediation_config=control.remediation,
        templates=mock_framework.templates,
        local_path=str(temp_git_repo),
        owner="owner",
        repo="repo",
        dry_run=False,
    )

    assert result["status"] == "error"
    assert "Jinja template rendering failed" in result["message"]


# ---------------------------------------------------------
# Phase 5: Dry Run Mode
# ---------------------------------------------------------


@patch("darnit_baseline.remediation.orchestrator._get_framework_config")
@patch("darnit.core.audit_cache.read_audit_cache")
@patch("darnit_baseline.remediation.orchestrator._preflight_context_check")
@patch("darnit_baseline.remediation.orchestrator.RemediationExecutor")
def test_remediate_audit_findings_dry_run(
    mock_executor_class,
    mock_preflight,
    mock_read_cache,
    mock_get_framework,
    mock_framework,
    temp_git_repo,
):
    """Test that dry_run=True sets the would_apply status and prevents changes."""
    mock_get_framework.return_value = mock_framework
    mock_read_cache.return_value = {"results": [{"id": "OSPS-GV-01.01", "status": "FAIL"}]}
    mock_preflight.return_value = (True, [])

    mock_executor = mock_executor_class.return_value
    mock_executor.execute.return_value = RemediationResult(
        success=True,
        control_id="OSPS-GV-01.01",
        remediation_type="declarative",
        message="Would create GOVERNANCE.md",
        dry_run=True,
        details={},
    )

    result_markdown = remediate_audit_findings(
        local_path=str(temp_git_repo),
        owner="owner",
        repo="repo",
        dry_run=True,
    )

    # The output should contain preview formatting
    assert "Would Apply" in result_markdown
    assert "OSPS-GV-01.01" in result_markdown
    # dry run only shows type in output, message is in result details
    assert "declarative" in result_markdown

    # Verify no file was created by checking test repo
    assert not (temp_git_repo / "GOVERNANCE.md").exists()


# ---------------------------------------------------------
# Phase 4: Side Effects (LLM Enhancement)
# ---------------------------------------------------------


@patch("darnit_baseline.remediation.orchestrator.RemediationExecutor")
@patch("darnit_baseline.remediation.enhancer.is_enhanceable")
@patch("darnit_baseline.remediation.enhancer.get_enhancement_type")
@patch("darnit_baseline.remediation.enhancer.enhance_generated_file")
def test_apply_declarative_remediation_llm_enhancement(
    mock_enhance,
    mock_get_type,
    mock_is_enhanceable,
    mock_executor_class,
    mock_framework,
    temp_git_repo,
):
    """Test that successful creation triggers LLM enhancement if enabled."""
    mock_executor = mock_executor_class.return_value
    mock_executor.execute.return_value = RemediationResult(
        success=True,
        control_id="OSPS-GV-01.01",
        remediation_type="file_create",
        message="Created GOVERNANCE.md",
        dry_run=False,
        details={},
    )

    # Needs a real file to trigger `os.path.isfile(abs_path)` in orchestrator
    test_file = temp_git_repo / "GOVERNANCE.md"
    test_file.write_text("Base content")

    # Setup LLM mocks
    mock_is_enhanceable.return_value = True
    mock_get_type.return_value = "governance"
    mock_enhance.return_value = "Enriched content output from LLM"

    control = mock_framework.controls["OSPS-GV-01.01"]

    # Since we can't write to model_extra statically, we replace the handler object
    control.remediation.handlers[0] = HandlerInvocation(**{"handler": "file_create", "path": "GOVERNANCE.md"})

    result = _apply_declarative_remediation(
        control_id="OSPS-GV-01.01",
        remediation_config=control.remediation,
        templates=mock_framework.templates,
        local_path=str(temp_git_repo),
        owner="owner",
        repo="repo",
        dry_run=False,
        enhance_with_llm=True,
    )

    assert result["enhanced"] is True
    mock_enhance.assert_called_once()

    # Verify the file was updated with enriched content
    assert test_file.read_text() == "Enriched content output from LLM"
