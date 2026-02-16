"""Map .project/ configuration to sieve context variables.

This module bridges the .project/ reader with the sieve context system,
mapping structured .project/ data to flat context variables that can be
used in checks and remediation.

Context variable naming convention:
- project.* - Direct .project/ fields
- project.security.* - Security section fields
- project.governance.* - Governance section fields
- project.maintainers - Maintainer list

Example:
    from darnit.context.dot_project_mapper import DotProjectMapper

    mapper = DotProjectMapper("/path/to/repo")
    context = mapper.get_context()

    # Access mapped values
    security_policy_path = context.get("project.security.policy_path")
    maintainers = context.get("project.maintainers", [])
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from darnit.context.dot_project import DotProjectReader, ProjectConfig

logger = logging.getLogger(__name__)


class DotProjectMapper:
    """Maps .project/ configuration to context variables.

    This class reads .project/ files and flattens them into a dictionary
    of context variables that can be injected into the sieve pipeline.
    """

    def __init__(self, repo_path: str | Path):
        """Initialize mapper with repository path.

        Args:
            repo_path: Path to the repository root
        """
        self.repo_path = Path(repo_path)
        self.reader = DotProjectReader(repo_path)
        self._config: ProjectConfig | None = None
        self._context: dict[str, Any] | None = None

    @property
    def config(self) -> ProjectConfig:
        """Get the parsed .project/ configuration."""
        if self._config is None:
            self._config = self.reader.read()
        return self._config

    def get_context(self) -> dict[str, Any]:
        """Get all context variables from .project/ configuration.

        Returns:
            Dictionary of context variables with dotted keys
        """
        if self._context is not None:
            return self._context

        config = self.config
        context: dict[str, Any] = {}

        # Core project fields
        if config.name:
            context["project.name"] = config.name
        if config.description:
            context["project.description"] = config.description
        if config.schema_version:
            context["project.schema_version"] = config.schema_version
        if config.type:
            context["project.type"] = config.type
        if config.slug:
            context["project.slug"] = config.slug
        if config.project_lead:
            context["project.project_lead"] = config.project_lead
        if config.cncf_slack_channel:
            context["project.cncf_slack_channel"] = config.cncf_slack_channel
        if config.website:
            context["project.website"] = config.website
        if config.repositories:
            context["project.repositories"] = config.repositories
        if config.adopters:
            context["project.adopters_path"] = config.adopters.path
        if config.package_managers:
            context["project.package_managers"] = config.package_managers

        # Maintainers (high priority for remediation)
        if config.maintainers:
            context["project.maintainers"] = config.maintainers

        # Security section
        if config.security:
            self._map_security(config.security, context)

        # Governance section
        if config.governance:
            self._map_governance(config.governance, context)

        # Legal section
        if config.legal:
            self._map_legal(config.legal, context)

        # Documentation section
        if config.documentation:
            self._map_documentation(config.documentation, context)

        # Landscape section
        if config.landscape:
            if config.landscape.category:
                context["project.landscape.category"] = config.landscape.category
            if config.landscape.subcategory:
                context["project.landscape.subcategory"] = config.landscape.subcategory

        # Extensions
        if config.extensions:
            self._map_extensions(config.extensions, context)

        # Social links
        if config.social:
            for platform, handle in config.social.items():
                context[f"project.social.{platform}"] = handle

        # Mailing lists
        if config.mailing_lists:
            context["project.mailing_lists"] = config.mailing_lists

        self._context = context
        return context

    def _map_security(self, security: Any, context: dict[str, Any]) -> None:
        """Map security section to context variables."""
        if security.policy:
            context["project.security.policy_path"] = security.policy.path
        if security.threat_model:
            context["project.security.threat_model_path"] = security.threat_model.path
        if security.contact:
            context["project.security.contact"] = security.contact

        # Include any extra fields
        for key, value in security._extra.items():
            context[f"project.security.{key}"] = value

    def _map_governance(self, governance: Any, context: dict[str, Any]) -> None:
        """Map governance section to context variables."""
        # Original fields
        if governance.contributing:
            context["project.governance.contributing_path"] = governance.contributing.path
        if governance.codeowners:
            context["project.governance.codeowners_path"] = governance.codeowners.path
        if governance.governance_doc:
            context["project.governance.governance_doc_path"] = governance.governance_doc.path

        # New PathRef fields
        pathref_fields = [
            "gitvote_config",
            "vendor_neutrality_statement",
            "decision_making_process",
            "roles_and_teams",
            "code_of_conduct",
            "sub_project_list",
            "sub_project_docs",
            "contributor_ladder",
            "change_process",
            "comms_channels",
            "community_calendar",
            "contributor_guide",
        ]
        for field_name in pathref_fields:
            ref = getattr(governance, field_name, None)
            if ref:
                context[f"project.governance.{field_name}_path"] = ref.path

        # Maintainer lifecycle nested struct
        if governance.maintainer_lifecycle:
            ml = governance.maintainer_lifecycle
            if ml.onboarding_doc:
                context["project.governance.maintainer_lifecycle.onboarding_doc_path"] = (
                    ml.onboarding_doc.path
                )
            if ml.progression_ladder:
                context["project.governance.maintainer_lifecycle.progression_ladder_path"] = (
                    ml.progression_ladder.path
                )
            if ml.offboarding_policy:
                context["project.governance.maintainer_lifecycle.offboarding_policy_path"] = (
                    ml.offboarding_policy.path
                )
            if ml.mentoring_program:
                context["project.governance.maintainer_lifecycle.mentoring_program"] = (
                    ml.mentoring_program
                )

        # Include any extra fields
        for key, value in governance._extra.items():
            context[f"project.governance.{key}"] = value

    def _map_legal(self, legal: Any, context: dict[str, Any]) -> None:
        """Map legal section to context variables."""
        if legal.license:
            context["project.legal.license_path"] = legal.license.path

        # Identity type nested struct
        if legal.identity_type:
            it = legal.identity_type
            context["project.legal.identity_type.has_dco"] = it.has_dco
            context["project.legal.identity_type.has_cla"] = it.has_cla
            if it.dco_url:
                context["project.legal.identity_type.dco_url_path"] = it.dco_url.path
            if it.cla_url:
                context["project.legal.identity_type.cla_url_path"] = it.cla_url.path

        # Include any extra fields
        for key, value in legal._extra.items():
            context[f"project.legal.{key}"] = value

    def _map_documentation(self, documentation: Any, context: dict[str, Any]) -> None:
        """Map documentation section to context variables."""
        if documentation.readme:
            context["project.documentation.readme_path"] = documentation.readme.path
        if documentation.support:
            context["project.documentation.support_path"] = documentation.support.path
        if documentation.architecture:
            context["project.documentation.architecture_path"] = documentation.architecture.path
        if documentation.api:
            context["project.documentation.api_path"] = documentation.api.path

        # Include any extra fields
        for key, value in documentation._extra.items():
            context[f"project.documentation.{key}"] = value

    def _map_extensions(
        self, extensions: dict[str, Any], context: dict[str, Any]
    ) -> None:
        """Map extensions section to context variables."""
        for ext_name, ext_config in extensions.items():
            # Extension metadata
            if ext_config.metadata:
                for key, value in ext_config.metadata.items():
                    context[f"project.extensions.{ext_name}.metadata.{key}"] = value

            # Extension config
            if ext_config.config:
                for key, value in ext_config.config.items():
                    context[f"project.extensions.{ext_name}.config.{key}"] = value

    def has_security_policy(self) -> bool:
        """Check if a security policy path is defined."""
        return self.config.security is not None and self.config.security.policy is not None

    def has_codeowners(self) -> bool:
        """Check if a CODEOWNERS path is defined."""
        return (
            self.config.governance is not None
            and self.config.governance.codeowners is not None
        )

    def has_maintainers(self) -> bool:
        """Check if maintainers are defined."""
        return len(self.config.maintainers) > 0

    def get_security_policy_path(self) -> str | None:
        """Get the security policy path if defined."""
        if self.config.security and self.config.security.policy:
            return self.config.security.policy.path
        return None

    def get_codeowners_path(self) -> str | None:
        """Get the CODEOWNERS path if defined."""
        if self.config.governance and self.config.governance.codeowners:
            return self.config.governance.codeowners.path
        return None

    def get_darnit_extension_config(self) -> dict[str, Any]:
        """Get darnit-specific extension configuration."""
        if "darnit" in self.config.extensions:
            return self.config.extensions["darnit"].config
        return {}
