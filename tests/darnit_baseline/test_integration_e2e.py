"""End-to-end integration tests for remediation workflow.

These tests verify the COMPLETE flow works correctly, not just individual functions.
They catch issues like:
- Orchestrator not calling functions correctly
- Output not showing prompts to users
- Status codes not propagating correctly
"""

import json
import os
import re
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_git_repo():
    """Create a temporary git repository for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.system(f"cd {tmpdir} && git init -q")
        os.system(f"cd {tmpdir} && git config user.email 'test@test.com'")
        os.system(f"cd {tmpdir} && git config user.name 'Test'")
        (Path(tmpdir) / "README.md").write_text("# Test Project")
        os.system(f"cd {tmpdir} && git add . && git commit -q -m 'init'")
        yield tmpdir


class TestRemediationE2EFlow:
    """Test the complete remediation flow end-to-end."""

    @pytest.mark.integration
    def test_governance_full_flow_prompts_then_creates(self, temp_git_repo, trusted_target):
        """Test complete governance flow: prompt -> confirm -> create."""
        from darnit.server.tools.project_data import confirm_project_data_impl
        from darnit_baseline.remediation.orchestrator import remediate_audit_findings

        # Step 1: Run remediation without confirmation - should prompt
        result1 = remediate_audit_findings(
            local_path=temp_git_repo,
            categories=["governance"],
            dry_run=False,
        )

        assert "BLOCKED: Remediation Cannot Proceed" in result1 or "Needs Confirmation" in result1
        assert "confirm_project_data" in result1
        assert not (Path(temp_git_repo) / "GOVERNANCE.md").exists()

        # Step 2: Confirm maintainers for the named, trusted repository
        # (feature 042, FR-011: a confirmation names its repository).
        owner, repo = trusted_target
        confirm_result = confirm_project_data_impl(
            local_path=temp_git_repo,
            maintainers=["@alice", "@bob"],
            owner=owner,
            repo=repo,
        )
        assert "maintainers: confirmed (in-repository), recorded in .project/darnit.yaml" in confirm_result

        # Step 3: Run remediation again - should create file
        result2 = remediate_audit_findings(
            local_path=temp_git_repo,
            categories=["governance"],
            dry_run=False,
        )

        # Feature 043 FR-019: read the structured outcome, not words or
        # symbols in the report (was: "Applied" or a check-mark emoji).
        run = json.loads(re.findall(r"```json\n(.*?)\n```", result2, re.DOTALL)[-1])
        [outcome] = [o for o in run["outcomes"] if o["control_id"] == "OSPS-GV-01.01"]
        assert ("GOVERNANCE.md", "create") in [(c["path"], c["action"]) for c in outcome["file_changes"]]
        assert outcome["kind"] in ("fixed", "changed_not_passing", "changed_not_verified")
        assert (Path(temp_git_repo) / "GOVERNANCE.md").exists()

        content = (Path(temp_git_repo) / "GOVERNANCE.md").read_text()
        # GOVERNANCE.md should reference MAINTAINERS.md, not embed names
        assert "MAINTAINERS.md" in content
        assert "CODEOWNERS" in content

    @pytest.mark.integration
    def test_security_policy_creates_security_md(self, temp_git_repo):
        """Test that vulnerability_management domain creates SECURITY.md."""
        import yaml

        from darnit.config.context_keys import value_digest
        from darnit_baseline.remediation.orchestrator import remediate_audit_findings

        # Feature 042 (FR-007): the SECURITY.md template reads security_contact,
        # which must be confirmed (was: rendered empty).
        contact = "security@test-project.dev"
        (Path(temp_git_repo) / ".project").mkdir()
        (Path(temp_git_repo) / ".project" / "darnit.yaml").write_text(
            yaml.safe_dump(
                {
                    "context": {"security_contact": contact},
                    "confirmations": {
                        "security_contact": {
                            "value_digest": value_digest("security_contact", contact),
                            "confirmed_by": "maintainer",
                            "confirmed_at": "2026-09-01T00:00:00Z",
                            "last_validated": "2026-09-01T00:00:00Z",
                        }
                    },
                }
            )
        )

        remediate_audit_findings(
            local_path=temp_git_repo,
            categories=["vulnerability_management"],
            dry_run=False,
        )

        assert (Path(temp_git_repo) / "SECURITY.md").exists()

        content = (Path(temp_git_repo) / "SECURITY.md").read_text()
        assert "Security" in content or "Vulnerability" in content
        assert contact in content

    @pytest.mark.integration
    def test_vex_policy_creates_the_policy_document(self, temp_git_repo):
        """OSPS-VM-04.02 creates docs/VEX-POLICY.md, and the result lists the file it wrote.

        Feature 043 FR-017: an apply reports what it changed (was: any of
        applied, would_apply, or manual, from a docstring that predated the
        file_create step).
        """
        from darnit_baseline.remediation.orchestrator import _apply_control_remediation

        result = _apply_control_remediation(
            control_id="OSPS-VM-04.02",
            local_path=temp_git_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        assert result["status"] == "applied"
        assert [(c["path"], c["action"]) for c in result["file_changes"]] == [("docs/VEX-POLICY.md", "create")]
        assert (Path(temp_git_repo) / "docs" / "VEX-POLICY.md").exists()


class TestControlDefinitionConsistency:
    """Test that control definitions are consistent."""

    @pytest.mark.unit
    def test_toml_remediation_coverage(self):
        """Report how many controls have TOML remediation defined."""
        from darnit_baseline.remediation.orchestrator import _get_framework_config

        framework = _get_framework_config()
        assert framework is not None

        total = len(framework.controls)
        with_remediation = sum(
            1 for c in framework.controls.values()
            if c.remediation and c.remediation.handlers
        )

        print(f"\nControls with TOML remediation: {with_remediation}/{total}")
        assert with_remediation >= 18, \
            f"Expected at least 18 controls with remediation, got {with_remediation}"


class TestOutputContainsExpectedContent:
    """Test that tool outputs contain expected content for users."""

    @pytest.mark.unit
    def test_needs_confirmation_output_has_prompt(self, temp_git_repo):
        """Verify needs_confirmation results include the actual prompt."""
        from darnit_baseline.remediation.orchestrator import _apply_control_remediation

        result = _apply_control_remediation(
            control_id="OSPS-GV-01.01",
            local_path=temp_git_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        assert result["status"] == "needs_confirmation"
        assert "result" in result
        assert "confirm_project_data" in result["result"]
        assert "maintainers=" in result["result"]
