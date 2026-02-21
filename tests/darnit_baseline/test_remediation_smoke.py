"""Smoke tests for remediation functions.

These tests verify that the remediation orchestrator and TOML-based
remediation system can be imported and called without import errors
or immediate crashes.
"""

import os
import tempfile
from pathlib import Path

import pytest


class TestRemediationOrchestratorExecution:
    """Test that the remediation orchestrator works end-to-end."""

    @pytest.mark.unit
    def test_domain_prefixes_defined(self):
        """Test that DOMAIN_PREFIXES has expected domain names."""
        from darnit_baseline.remediation.orchestrator import DOMAIN_PREFIXES

        expected_domains = [
            "access_control",
            "build_release",
            "documentation",
            "governance",
            "legal",
            "quality",
            "security_architecture",
            "vulnerability_management",
        ]

        for domain in expected_domains:
            assert domain in DOMAIN_PREFIXES, f"Missing domain: {domain}"
            assert DOMAIN_PREFIXES[domain].startswith("OSPS-")

    @pytest.fixture
    def temp_repo(self):
        """Create a temporary directory that looks like a git repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize as a git repo
            os.system(f"cd {tmpdir} && git init -q")
            os.system(f"cd {tmpdir} && git config user.email 'test@test.com'")
            os.system(f"cd {tmpdir} && git config user.name 'Test'")
            # Create a dummy file and commit
            (Path(tmpdir) / "README.md").write_text("# Test")
            os.system(f"cd {tmpdir} && git add . && git commit -q -m 'init'")
            yield tmpdir

    @pytest.mark.unit
    def test_remediate_audit_findings_dry_run(self, temp_repo):
        """Test remediate_audit_findings in dry-run mode."""
        from darnit_baseline.remediation.orchestrator import remediate_audit_findings

        result = remediate_audit_findings(
            local_path=temp_repo,
            categories=["vulnerability_management"],
            dry_run=True,
        )
        assert isinstance(result, str)
        assert "Preview" in result or "dry run" in result.lower() or "would" in result.lower()

    @pytest.mark.unit
    def test_remediate_all_categories_dry_run(self, temp_repo):
        """Test remediate_audit_findings with all categories in dry-run mode."""
        from darnit_baseline.remediation.orchestrator import remediate_audit_findings

        result = remediate_audit_findings(
            local_path=temp_repo,
            categories=["all"],
            dry_run=True,
        )
        assert isinstance(result, str)
        # Should not crash and should return something meaningful
        assert len(result) > 0

    @pytest.mark.unit
    def test_apply_control_remediation_dry_run(self, temp_repo):
        """Test _apply_control_remediation for controls that don't require API."""
        from darnit_baseline.remediation.orchestrator import (
            _apply_control_remediation,
            _get_framework_config,
        )

        framework = _get_framework_config()
        assert framework is not None

        # Test a few controls that have TOML remediation and don't need API
        for control_id, control in sorted(framework.controls.items()):
            if not control.remediation or not control.remediation.handlers:
                continue
            if control.remediation.requires_api:
                continue

            result = _apply_control_remediation(
                control_id=control_id,
                local_path=temp_repo,
                owner="test-owner",
                repo="test-repo",
                dry_run=True,
            )
            assert isinstance(result, dict), f"Control {control_id} didn't return dict"
            assert "control_id" in result, f"Control {control_id} missing 'control_id' key"
            assert "status" in result, f"Control {control_id} missing 'status' key"
            break  # One is enough for a smoke test


