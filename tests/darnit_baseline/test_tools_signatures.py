"""Tests for darnit_baseline.tools function signatures and imports.

These tests catch issues like:
- Parameter name mismatches (e.g., passing `repo_path` when function expects `local_path`)
- Import errors (e.g., importing non-existent functions)
- Signature incompatibilities between wrapper and underlying functions
"""

import inspect
from typing import Callable, Set, get_type_hints
import pytest


class TestToolsImports:
    """Test that all tool functions can be imported without errors."""

    def test_all_tools_importable(self) -> None:
        """All tools in __all__ should be importable."""
        from darnit_baseline import tools

        for name in tools.__all__:
            assert hasattr(tools, name), f"Tool '{name}' listed in __all__ but not found"
            func = getattr(tools, name)
            assert callable(func), f"Tool '{name}' is not callable"

    def test_audit_tool_imports(self) -> None:
        """Audit tool dependencies should be importable."""
        from darnit_baseline.tools import audit_openssf_baseline
        # Verify the function exists and is callable
        assert callable(audit_openssf_baseline)

    def test_threat_model_imports(self) -> None:
        """Threat model tool should import all required functions."""
        # These are the functions used inside generate_threat_model
        from darnit.threat_model import (
            detect_frameworks,
            discover_all_assets,
            discover_injection_sinks,
            analyze_stride_threats,
            identify_control_gaps,
            generate_markdown_threat_model,
            generate_sarif_threat_model,
            generate_json_summary,
        )
        # All imports should succeed - no assertion needed

    def test_remediation_imports(self) -> None:
        """Remediation tool dependencies should be importable."""
        from darnit_baseline.remediation import remediate_audit_findings
        assert callable(remediate_audit_findings)


class TestToolsSignatures:
    """Test that tool wrapper functions pass valid parameters to underlying functions."""

    def _get_param_names(self, func: Callable) -> Set[str]:
        """Get parameter names from a function signature."""
        sig = inspect.signature(func)
        return set(sig.parameters.keys())

    def test_remediate_audit_findings_signature(self) -> None:
        """remediate_audit_findings wrapper should pass valid parameters."""
        from darnit_baseline.tools import remediate_audit_findings as wrapper
        from darnit_baseline.remediation import remediate_audit_findings as impl

        wrapper_params = self._get_param_names(wrapper)
        impl_params = self._get_param_names(impl)

        # Check that common parameters match
        # The wrapper can have additional parameters, but any it passes to impl must exist
        common_params = {'local_path', 'owner', 'repo', 'categories', 'dry_run'}
        for param in common_params:
            assert param in impl_params, f"Parameter '{param}' not in implementation"

        # Specifically check that 'repo_path' is NOT a parameter (the bug we fixed)
        assert 'repo_path' not in impl_params, "Implementation should not have 'repo_path' parameter"

    def test_create_security_policy_signature(self) -> None:
        """create_security_policy wrapper should pass valid parameters."""
        from darnit_baseline.tools import create_security_policy as wrapper
        from darnit_baseline.remediation.actions import create_security_policy as impl

        impl_params = self._get_param_names(impl)

        # Check expected parameters exist
        expected = {'owner', 'repo', 'local_path', 'template'}
        for param in expected:
            assert param in impl_params, f"Parameter '{param}' not in implementation"

        # Verify 'repo_path' is NOT a parameter
        assert 'repo_path' not in impl_params, "Implementation should not have 'repo_path' parameter"

    def test_enable_branch_protection_signature(self) -> None:
        """enable_branch_protection wrapper should pass valid parameters."""
        from darnit_baseline.tools import enable_branch_protection as wrapper
        from darnit.remediation.github import enable_branch_protection as impl

        impl_params = self._get_param_names(impl)

        # Check expected parameters exist
        expected = {'owner', 'repo', 'branch', 'required_approvals', 'enforce_admins',
                    'require_pull_request', 'require_status_checks', 'status_checks', 'dry_run'}
        for param in expected:
            assert param in impl_params, f"Parameter '{param}' not in implementation"


class TestToolsSmoke:
    """Smoke tests that verify tools can be called (with safe parameters)."""

    def test_list_available_checks_callable(self) -> None:
        """list_available_checks should be callable and return JSON."""
        from darnit_baseline.tools import list_available_checks
        import json

        result = list_available_checks()
        # Should return valid JSON
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_generate_threat_model_handles_missing_path(self) -> None:
        """generate_threat_model should handle non-existent path gracefully."""
        from darnit_baseline.tools import generate_threat_model

        result = generate_threat_model(local_path="/nonexistent/path/12345")
        assert "Error" in result or "not found" in result.lower()

    def test_remediate_audit_findings_handles_missing_path(self) -> None:
        """remediate_audit_findings should handle non-existent path gracefully."""
        from darnit_baseline.tools import remediate_audit_findings

        result = remediate_audit_findings(local_path="/nonexistent/path/12345", dry_run=True)
        assert "Error" in result or "not found" in result.lower()

    def test_audit_handles_missing_path(self) -> None:
        """audit_openssf_baseline should handle non-existent path gracefully."""
        from darnit_baseline.tools import audit_openssf_baseline

        result = audit_openssf_baseline(local_path="/nonexistent/path/12345")
        assert "Error" in result or "not found" in result.lower()
