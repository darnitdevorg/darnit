import json
import re
import subprocess
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
from darnit.remediation import manifest
from darnit.remediation.executor import RemediationResult
from darnit.remediation.plan import FileChange, PlanItem, content_digest
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

    # Feature 043 (FR-017, FR-019): a successful handler that wrote nothing
    # is reported "unchanged" from the structured result, never as a fix.
    assert "OSPS-GV-01.01" in result_markdown
    run = json.loads(re.findall(r"```json\n(.*?)\n```", result_markdown, re.DOTALL)[-1])
    assert [(o["control_id"], o["kind"]) for o in run["outcomes"]] == [("OSPS-GV-01.01", "unchanged")]
    mock_executor.execute.assert_called_once()

    call_args = mock_executor.execute.call_args[1]
    assert call_args["control_id"] == "OSPS-GV-01.01"
    assert call_args["dry_run"] is False


@patch("darnit_baseline.remediation.orchestrator.RemediationExecutor")
def test_apply_declarative_remediation_leaves_project_update_to_the_executor(
    mock_executor_class,
    mock_framework,
    temp_git_repo,
):
    """The executor is the single writer of project_update (feature 043, research R6).

    It writes project_update through the run manifest after a successful
    apply; the orchestrator writing it again would be a second, unrecorded
    write path.
    """
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
    assert not (temp_git_repo / ".project").exists()


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

    planned = FileChange(path="GOVERNANCE.md", action="create", content="# Governance\n")
    item = PlanItem(control_id="OSPS-GV-01.01", step="file_create[0]", file_changes=[planned], previewable=True)
    mock_executor = mock_executor_class.return_value
    mock_executor.execute.return_value = RemediationResult(
        success=True,
        control_id="OSPS-GV-01.01",
        remediation_type="declarative",
        message="Would execute 1 remediation handler(s)",
        dry_run=True,
        details={},
        plan=[item],
        file_changes=[planned],
    )

    result_markdown = remediate_audit_findings(
        local_path=str(temp_git_repo),
        owner="owner",
        repo="repo",
        dry_run=True,
    )

    # Feature 043 FR-021: the preview lists the planned changes and their
    # digests (was: only the remediation type of each control).
    assert "Would Apply" in result_markdown
    assert "OSPS-GV-01.01" in result_markdown
    assert "`GOVERNANCE.md`: would be created" in result_markdown
    run = json.loads(re.findall(r"```json\n(.*?)\n```", result_markdown, re.DOTALL)[-1])
    assert [p["digest"] for p in run["plan"]] == [item.digest]

    # Verify no file was created by checking test repo
    assert not (temp_git_repo / "GOVERNANCE.md").exists()


# ---------------------------------------------------------
# Phase 4: Side Effects (LLM Enhancement)
# ---------------------------------------------------------


@pytest.fixture
def stub_enhancer():
    with (
        patch("darnit_baseline.remediation.enhancer.is_enhanceable", return_value=True),
        patch("darnit_baseline.remediation.enhancer.get_enhancement_type", return_value="architecture"),
        patch("darnit_baseline.remediation.enhancer.enhance_generated_file", return_value="# Enriched\n") as enhance,
    ):
        yield enhance


def _enhanced(repo, path: str, *, dry_run: bool, run_id: str | None = None, approve=()) -> dict:
    from darnit.remediation.platform import PlatformSession
    from darnit.remediation.platform.policy import ResolvedPolicy

    for key, value in (("commit.gpgsign", "false"), ("core.hooksPath", ".git/hooks")):
        subprocess.run(["git", "config", "--local", key, value], cwd=repo, check=True, capture_output=True)
    config = RemediationConfig(handlers=[HandlerInvocation(handler="file_create", path=path, content="# Generated\n")])
    return _apply_declarative_remediation(
        control_id="OSPS-GV-01.01",
        remediation_config=config,
        templates={},
        local_path=str(repo),
        owner="owner",
        repo="repo",
        dry_run=dry_run,
        enhance_with_llm=True,
        platform=PlatformSession("github.com/owner/repo", policy=ResolvedPolicy(), approvals=approve),
        run_id=run_id,
    )


def _enhanced_apply(repo, path: str, run_id: str, approve=()) -> dict:
    return _enhanced(repo, path, dry_run=False, run_id=run_id, approve=approve)


def _enhancement_item(preview: dict) -> dict:
    [item] = [i for i in preview["plan"] if i["step"].startswith("llm_enhance[")]
    return item


def test_llm_enhancement_never_touches_a_file_that_already_existed(stub_enhancer, temp_git_repo):
    """framework-design 4.3, scenario "Customizing a file that already existed"."""
    readme = temp_git_repo / "README.md"
    before = readme.read_bytes()

    result = _enhanced_apply(temp_git_repo, "README.md", manifest.new_run_id())

    assert readme.read_bytes() == before
    assert result["enhanced"] is False
    stub_enhancer.assert_not_called()


def test_preview_lists_the_enhancement_as_an_item_that_cannot_be_previewed(stub_enhancer, temp_git_repo):
    """FR-023: the LLM's output cannot be computed in advance, so it is its own item needing approval."""
    preview = _enhanced(temp_git_repo, "ARCHITECTURE.md", dry_run=True)

    item = _enhancement_item(preview)
    assert item["previewable"] is False and item["requires_individual_approval"] is True
    assert content_digest("# Generated\n") in item["step"]
    assert item["digest"] not in {i["digest"] for i in preview["plan"] if i is not item}
    assert not (temp_git_repo / "ARCHITECTURE.md").exists()
    stub_enhancer.assert_not_called()


def test_unapproved_enhancement_keeps_the_template_content_and_commits(stub_enhancer, temp_git_repo):
    from darnit.server.tools.git_operations import commit_remediation_changes_impl

    run_id = manifest.new_run_id()
    item = _enhancement_item(_enhanced(temp_git_repo, "ARCHITECTURE.md", dry_run=True))

    result = _enhanced_apply(temp_git_repo, "ARCHITECTURE.md", run_id)

    stub_enhancer.assert_not_called()
    assert result["enhanced"] is False
    assert result["enhancement_needs_approval"] == [item["digest"]]
    assert item["digest"] in {i["digest"] for i in result["plan"]}
    assert (temp_git_repo / "ARCHITECTURE.md").read_text(encoding="utf-8") == "# Generated\n"
    run = manifest.load_run("github.com/owner/repo", run_id)
    assert {f.path: f.after_digest for f in run.files} == {"ARCHITECTURE.md": content_digest("# Generated\n")}

    committed = commit_remediation_changes_impl(local_path=str(temp_git_repo), run_id=run_id, owner="owner", repo="repo")

    assert committed.startswith("Changes committed successfully"), committed
    shown = subprocess.run(
        ["git", "show", "HEAD:ARCHITECTURE.md"], cwd=temp_git_repo, capture_output=True, text=True, check=True
    ).stdout
    assert shown == "# Generated\n"


def test_llm_enhancement_of_a_created_file_is_recorded_and_committable(stub_enhancer, temp_git_repo):
    from darnit.server.tools.git_operations import commit_remediation_changes_impl

    run_id = manifest.new_run_id()
    item = _enhancement_item(_enhanced(temp_git_repo, "ARCHITECTURE.md", dry_run=True))

    result = _enhanced_apply(temp_git_repo, "ARCHITECTURE.md", run_id, approve=[item["digest"]])

    assert result["enhanced"] is True
    assert result["enhancement_needs_approval"] == []
    assert item["digest"] in {a["digest"] for a in result["approvals"]}
    assert (temp_git_repo / "ARCHITECTURE.md").read_text(encoding="utf-8") == "# Enriched\n"
    [created] = [c for c in result["file_changes"] if c["path"] == "ARCHITECTURE.md"]
    assert (created["action"], created["content"]) == ("create", "# Enriched\n")
    run = manifest.load_run("github.com/owner/repo", run_id)
    assert {f.path: f.after_digest for f in run.files} == {"ARCHITECTURE.md": content_digest("# Enriched\n")}

    committed = commit_remediation_changes_impl(local_path=str(temp_git_repo), run_id=run_id, owner="owner", repo="repo")

    assert committed.startswith("Changes committed successfully"), committed
    assert "ARCHITECTURE.md" in committed
