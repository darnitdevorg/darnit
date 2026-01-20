"""Configuration management for darnit framework.

This module provides configuration loading and management for .project.yaml
files following the CNCF .project specification with OpenSSF Baseline extension.
"""

from .schema import (
    # Enums
    ProjectType,
    ControlStatusValue,
    ContributorAgreementType,
    SBOMFormat,
    SigningMethod,
    ProvenanceFormat,
    # Reference types
    PathRef,
    UrlRef,
    RepoRef,
    SectionRef,
    NARef,
    ResourceRef,
    parse_resource_ref,
    get_path_from_ref,
    # CNCF standard
    MaturityEntry,
    Audit,
    SecurityConfig,
    GovernanceConfig,
    LegalConfig,
    DocumentationConfig,
    # Baseline extension
    ControlOverride,
    ArtifactConfig,
    ContributorAgreementConfig,
    CIConfig,
    ProjectContext,
    ExtendedGovernance,
    ExtendedQuality,
    ExtendedSecurity,
    ExtendedLegal,
    DependenciesConfig,
    ArtifactsConfig,
    BaselineExtension,
    # Main config
    ProjectConfig,
    # Factory functions
    create_minimal_config,
    create_full_config,
)

from .loader import (
    # Core functions
    load_project_config,
    save_project_config,
    get_project_config,
    init_project_config,
    config_exists,
    get_config_path,
    get_extension_path,
    list_extension_files,
    clear_config_cache,
    # Extension registry
    ExtensionSpec,
    EXTENSION_REGISTRY,
    get_extension_by_key,
    get_default_extension,
    # Constants
    PROJECT_DIR,
    PROJECT_FILE,
    EXTENSION_FILE,
    CNCF_STANDARD_FIELDS,
)

from .discovery import (
    discover_files,
    discover_ci_config,
    discover_project_name,
    sync_discovered_to_config,
)

# Framework and user configuration schemas
from .framework_schema import (
    FrameworkConfig,
    FrameworkMetadata,
    FrameworkDefaults,
    ControlConfig,
    CheckConfig,
    RemediationConfig,
    PassesConfig,
    DeterministicPassConfig,
    ExecPassConfig,
    PatternPassConfig,
    LLMPassConfig,
    ManualPassConfig,
    AdapterType,
    PassPhase,
)

from .user_schema import (
    UserConfig,
    UserSettings,
    ControlOverride as UserControlOverride,
    ControlGroup,
    CustomControl,
    ControlStatus as UserControlStatus,
    create_user_config,
    create_user_config_with_kusari,
)

from .merger import (
    EffectiveConfig,
    EffectiveControl,
    merge_configs,
    merge_control,
    deep_merge,
    load_framework_config,
    load_user_config,
    load_effective_config,
    load_effective_config_by_name,
    load_effective_config_auto,
    load_framework_by_name,
    resolve_framework_path,
    list_available_frameworks,
    validate_framework_config,
    validate_user_config,
)

from .control_loader import (
    load_controls_from_effective,
    load_controls_from_framework,
    load_controls_from_toml,
    load_controls_by_name,
    register_controls_from_config,
    control_from_effective,
    control_from_framework,
)

# Legacy exports (deprecated)
from .models import (
    ReferenceStatus,
    ResourceReference,
    ControlStatus,
)

__all__ = [
    # Enums
    "ProjectType",
    "ControlStatusValue",
    "ContributorAgreementType",
    "SBOMFormat",
    "SigningMethod",
    "ProvenanceFormat",
    # Reference types
    "PathRef",
    "UrlRef",
    "RepoRef",
    "SectionRef",
    "NARef",
    "ResourceRef",
    "parse_resource_ref",
    "get_path_from_ref",
    # CNCF standard
    "MaturityEntry",
    "Audit",
    "SecurityConfig",
    "GovernanceConfig",
    "LegalConfig",
    "DocumentationConfig",
    # Baseline extension
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
    # Main config
    "ProjectConfig",
    # Factory functions
    "create_minimal_config",
    "create_full_config",
    # Loader - core
    "load_project_config",
    "save_project_config",
    "get_project_config",
    "init_project_config",
    "config_exists",
    "get_config_path",
    "get_extension_path",
    "list_extension_files",
    "clear_config_cache",
    # Loader - extension registry
    "ExtensionSpec",
    "EXTENSION_REGISTRY",
    "get_extension_by_key",
    "get_default_extension",
    # Loader - constants
    "PROJECT_DIR",
    "PROJECT_FILE",
    "EXTENSION_FILE",
    "CNCF_STANDARD_FIELDS",
    # Discovery
    "discover_files",
    "discover_ci_config",
    "discover_project_name",
    "sync_discovered_to_config",
    # Legacy (deprecated)
    "ReferenceStatus",
    "ResourceReference",
    "ControlStatus",
    # Framework configuration schema
    "FrameworkConfig",
    "FrameworkMetadata",
    "FrameworkDefaults",
    "ControlConfig",
    "CheckConfig",
    "RemediationConfig",
    "PassesConfig",
    "DeterministicPassConfig",
    "ExecPassConfig",
    "PatternPassConfig",
    "LLMPassConfig",
    "ManualPassConfig",
    "AdapterType",
    "PassPhase",
    # User configuration schema
    "UserConfig",
    "UserSettings",
    "UserControlOverride",
    "ControlGroup",
    "CustomControl",
    "UserControlStatus",
    "create_user_config",
    "create_user_config_with_kusari",
    # Configuration merger
    "EffectiveConfig",
    "EffectiveControl",
    "merge_configs",
    "merge_control",
    "deep_merge",
    "load_framework_config",
    "load_user_config",
    "load_effective_config",
    "load_effective_config_by_name",
    "load_effective_config_auto",
    "load_framework_by_name",
    "resolve_framework_path",
    "list_available_frameworks",
    "validate_framework_config",
    "validate_user_config",
    # Control loader
    "load_controls_from_effective",
    "load_controls_from_framework",
    "load_controls_from_toml",
    "load_controls_by_name",
    "register_controls_from_config",
    "control_from_effective",
    "control_from_framework",
]
