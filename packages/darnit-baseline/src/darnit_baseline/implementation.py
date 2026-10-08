"""OpenSSF Baseline implementation for darnit.

This module provides the OSPSBaselineImplementation class that implements
the darnit ComplianceImplementation protocol for OpenSSF Baseline (OSPS v2025.10.10).
"""

from pathlib import Path


class OSPSBaselineImplementation:
    """OpenSSF Baseline (OSPS v2025.10.10) implementation for darnit.

    This implementation provides 62 controls across 3 maturity levels:
    - Level 1: 24 controls (basic security hygiene)
    - Level 2: 19 controls (intermediate security)
    - Level 3: 19 controls (advanced security)
    """

    @property
    def name(self) -> str:
        return "openssf-baseline"

    @property
    def display_name(self) -> str:
        return "OpenSSF Baseline"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def spec_version(self) -> str:
        return "OSPS v2026.02.19"

    def get_framework_config_path(self) -> Path | None:
        """Get path to the OpenSSF Baseline framework TOML file.

        Resolved via ``importlib.resources`` so it works under both editable
        installs (``uv sync``) and wheel installs (``uv tool install`` / ``pip
        install``). The TOML is placed inside the installed package by the
        ``force-include`` entry in ``pyproject.toml``.
        """
        from importlib.resources import files

        resource = files(__package__) / "openssf-baseline.toml"
        path = Path(str(resource))
        if not path.is_file():
            raise FileNotFoundError(
                f"openssf-baseline.toml not found in installed darnit_baseline "
                f"package at {path}. This indicates a broken build; check the "
                f"wheel's force-include configuration."
            )
        return path

    def get_audit_profiles(self) -> dict | None:
        """Return named audit profiles from TOML config.

        Returns:
            Dict mapping profile name to AuditProfileConfig, or None if no profiles defined.
        """
        from darnit.config.merger import load_framework_by_name

        config = load_framework_by_name("openssf-baseline")
        if config.audit_profiles:
            return dict(config.audit_profiles)
        return None

    def register_handlers(self) -> None:
        """Register handlers with the handler registry.

        This explicitly registers all tool handlers with the registry.
        The handlers are then available by short name in TOML configurations.

        This method can be called multiple times (e.g., after clearing the registry
        in tests) to re-register handlers.
        """
        from darnit.core.handlers import get_handler_registry

        from . import tools

        # Set plugin context so handlers know which plugin registered them
        registry = get_handler_registry()
        registry.set_plugin_context(self.name)

        # Explicitly register each handler
        # This allows re-registration after registry.clear() in tests
        handlers = [
            ("audit_openssf_baseline", tools.audit_openssf_baseline),
            ("list_org_repos", tools.list_org_repos),
            ("audit_org", tools.audit_org),
            ("list_available_checks", tools.list_available_checks),
            ("get_project_config", tools.get_project_config),
            ("create_security_policy", tools.create_security_policy),
            ("enable_branch_protection", tools.enable_branch_protection),
            ("init_project_config", tools.init_project_config),
            ("confirm_project_data", tools.confirm_project_data_tool()),
            ("get_pending_data", tools.get_pending_data),
            ("generate_threat_model", tools.generate_threat_model),
            ("generate_attestation", tools.generate_attestation),
            ("remediate_audit_findings", tools.remediate_audit_findings),
            ("create_remediation_branch", tools.create_remediation_branch),
            ("commit_remediation_changes", tools.commit_remediation_changes),
            ("create_remediation_pr", tools.create_remediation_pr),
            ("get_remediation_status", tools.get_remediation_status),
            ("create_test_repository", tools.create_test_repository),
        ]

        for name, handler in handlers:
            registry.register_handler(name, handler)

        # Clear plugin context
        registry.set_plugin_context(None)

        # Register sieve remediation handlers
        from darnit.sieve.handler_registry import get_sieve_handler_registry

        from .branch_protection import github_branch_protection_handler
        from .threat_model.remediation import generate_threat_model_handler

        sieve_registry = get_sieve_handler_registry()
        sieve_registry.set_plugin_context(self.name)
        sieve_registry.register(
            "generate_threat_model",
            phase="deterministic",
            handler_fn=generate_threat_model_handler,
            description="Generate dynamic STRIDE threat model",
            # RFC-0001 Stage 1: threat-model generation observes ground
            # truth (file produced or not).
            ceiling={"pass", "fail"},
            # Feature 043 (framework-design 4.2): it writes its files itself,
            # so it is reported as not previewable and runs in a batch apply
            # only when its plan item digest is approved.
            supports_plan=False,
            # template is resolved to content by the remediation executor.
            settings={"path", "overwrite", "content", "template", "shallow_threshold", "max_findings"},
        )
        # Feature 032: ruleset-aware branch-protection verdict. Observes
        # ground truth (queries GitHub for protection state), so it may
        # conclude either way (feature 041 data-model.md).
        sieve_registry.register(
            "github_branch_protection",
            phase="deterministic",
            handler_fn=github_branch_protection_handler,
            description="Ruleset-aware branch-protection verdict",
            ceiling={"pass", "fail"},
            settings={"requirement", "required_approvals_minimum", "owner", "repo", "branch"},
        )
        sieve_registry.set_plugin_context(None)


__all__ = ["OSPSBaselineImplementation"]
