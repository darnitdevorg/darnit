"""Legacy models - re-exported from schema.py for backwards compatibility.

This module is deprecated. Import from darnit.config.schema instead.
"""

import warnings

# Re-export everything from schema
from .schema import (
    ArtifactConfig,
    ArtifactsConfig,
    Audit,
    BaselineExtension,
    CIConfig,
    ContributorAgreementConfig,
    ContributorAgreementType,
    # Baseline extension
    ControlOverride,
    ControlStatusValue,
    DependenciesConfig,
    DocumentationConfig,
    ExtendedGovernance,
    ExtendedLegal,
    ExtendedQuality,
    ExtendedSecurity,
    GovernanceConfig,
    LegalConfig,
    # CNCF standard
    MaturityEntry,
    NARef,
    # Reference types
    PathRef,
    # Main config
    ProjectConfig,
    ProjectContext,
    # Enums
    ProjectType,
    ProvenanceFormat,
    RepoRef,
    ResourceRef,
    SBOMFormat,
    SectionRef,
    SecurityConfig,
    SigningMethod,
    UrlRef,
    create_full_config,
    # Factory functions
    create_minimal_config,
    get_path_from_ref,
    parse_resource_ref,
)


# Legacy aliases for backwards compatibility
class ReferenceStatus:
    """Deprecated: Use ControlStatusValue instead."""
    VERIFIED = "verified"
    MISSING = "missing"
    DISCOVERED = "discovered"
    NA = "n/a"
    EXTERNAL = "external"
    UNKNOWN = "unknown"

    def __init__(self) -> None:
        warnings.warn(
            "ReferenceStatus is deprecated, use ControlStatusValue from schema",
            DeprecationWarning,
            stacklevel=2
        )


# Legacy ResourceReference - map to new types
class ResourceReference:
    """Deprecated: Use PathRef, UrlRef, RepoRef, or NARef instead."""

    def __init__(
        self,
        ref_type: str = "path",
        path: str | None = None,
        url: str | None = None,
        repo: str | None = None,
        repo_path: str | None = None,
        repo_ref: str | None = None,
        status: str | None = None,
        reason: str | None = None,
        section: str | None = None,
        format: str | None = None,
        type: str | None = None,
        enabled: bool | None = None,
        method: str | None = None,
    ) -> None:
        warnings.warn(
            "ResourceReference is deprecated, use PathRef/UrlRef/RepoRef from schema",
            DeprecationWarning,
            stacklevel=2
        )
        self.ref_type = ref_type
        self.path = path
        self.url = url
        self.repo = repo
        self.repo_path = repo_path
        self.repo_ref = repo_ref
        self.status = status
        self.reason = reason
        self.section = section
        self.format = format
        self.type = type
        self.enabled = enabled
        self.method = method


class ControlStatus:
    """Deprecated: Use ControlOverride instead."""

    def __init__(self, status: str, reason: str | None = None) -> None:
        warnings.warn(
            "ControlStatus is deprecated, use ControlOverride from schema",
            DeprecationWarning,
            stacklevel=2
        )
        self.status = status
        self.reason = reason


__all__ = [
    # New schema exports
    "ProjectType",
    "ControlStatusValue",
    "ContributorAgreementType",
    "SBOMFormat",
    "SigningMethod",
    "ProvenanceFormat",
    "PathRef",
    "UrlRef",
    "RepoRef",
    "SectionRef",
    "NARef",
    "ResourceRef",
    "parse_resource_ref",
    "get_path_from_ref",
    "MaturityEntry",
    "Audit",
    "SecurityConfig",
    "GovernanceConfig",
    "LegalConfig",
    "DocumentationConfig",
    "ControlOverride",
    "ArtifactConfig",
    "ContributorAgreementConfig",
    "CIConfig",
    "ProjectContext",
    "ExtendedGovernance",
    "ExtendedQuality",
    "ExtendedSecurity",
    "ExtendedLegal",
    "DependenciesConfig",
    "ArtifactsConfig",
    "BaselineExtension",
    "ProjectConfig",
    "create_minimal_config",
    "create_full_config",
    # Legacy (deprecated)
    "ReferenceStatus",
    "ResourceReference",
    "ControlStatus",
]
