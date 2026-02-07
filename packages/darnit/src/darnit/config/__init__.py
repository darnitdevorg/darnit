"""Configuration management for darnit framework.

This module provides configuration loading and management for .project.yaml
files following the CNCF .project specification with OpenSSF Baseline extension.
"""

from .context_schema import (
    BaselineExtension as CNCFBaselineExtension,
)

# Context schema (interactive context collection)
from .context_schema import (
    BaselineExtensionConfig,
    CNCFProjectConfig,
    ContextByCategory,
    ContextCategory,
    ContextDefinition,
    ContextPromptRequest,
    # Enums
    ContextSource,
    ContextType,
    # Core models
    ContextValue,
    # CNCF extension models
    ExtensionMetadata,
    ProjectExtensions,
)

# Context storage abstraction layer
from .context_storage import (
    get_context_definitions,
    get_context_value,
    get_pending_context,
    get_raw_value,
    is_context_confirmed,
    load_context,
    save_context_value,
    save_context_values,
)
from .control_loader import (
    control_from_effective,
    control_from_framework,
    load_controls_by_name,
    load_controls_from_effective,
    load_controls_from_framework,
    load_controls_from_toml,
    register_controls_from_config,
)
from .discovery import (
    discover_ci_config,
    discover_files,
    discover_project_name,
    sync_discovered_to_config,
)

# Framework and user configuration schemas
from .framework_schema import (
    AdapterType,
    CheckConfig,
    # Context definitions (interactive context collection)
    ContextDefinitionConfig,
    ControlConfig,
    DeterministicPassConfig,
    ExecPassConfig,
    FrameworkConfig,
    FrameworkContextConfig,
    FrameworkDefaults,
    FrameworkMetadata,
    LLMPassConfig,
    # Locator configuration (evidence location)
    LocatorConfig,
    LocatorLLMHints,
    ManualPassConfig,
    ManualRemediationConfig,
    OutputMapping,
    PassesConfig,
    PassPhase,
    PatternPassConfig,
    RemediationConfig,
)
from .loader import (
    CNCF_STANDARD_FIELDS,
    EXTENSION_FILE,
    EXTENSION_REGISTRY,
    # Constants
    PROJECT_DIR,
    PROJECT_FILE,
    # Extension registry
    ExtensionSpec,
    clear_config_cache,
    config_exists,
    get_config_path,
    get_default_extension,
    get_extension_by_key,
    get_extension_path,
    get_project_config,
    init_project_config,
    list_extension_files,
    # Core functions
    load_project_config,
    save_project_config,
)
from .merger import (
    EffectiveConfig,
    EffectiveControl,
    deep_merge,
    list_available_frameworks,
    load_effective_config,
    load_effective_config_auto,
    load_effective_config_by_name,
    load_framework_by_name,
    load_framework_config,
    load_user_config,
    merge_configs,
    merge_control,
    resolve_framework_path,
    validate_framework_config,
    validate_user_config,
)
from .resolver import (
    resolve_file_for_control,
    sync_discovered_file_to_config,
    update_config_after_file_create,
)
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
from .user_schema import (
    ControlGroup,
    CustomControl,
    UserConfig,
    UserSettings,
    create_user_config,
    create_user_config_with_kusari,
)
from .user_schema import (
    ControlOverride as UserControlOverride,
)
from .user_schema import (
    ControlStatus as UserControlStatus,
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
    # Config-aware resolver
    "resolve_file_for_control",
    "update_config_after_file_create",
    "sync_discovered_file_to_config",
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
    "ManualRemediationConfig",
    "AdapterType",
    "PassPhase",
    # Locator configuration (evidence location)
    "LocatorConfig",
    "LocatorLLMHints",
    "OutputMapping",
    # Context definitions (interactive context collection)
    "ContextDefinitionConfig",
    "FrameworkContextConfig",
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
    # Context schema (interactive context collection)
    "ContextSource",
    "ContextType",
    "ContextValue",
    "ContextDefinition",
    "ContextPromptRequest",
    "ContextByCategory",
    "ContextCategory",
    "ExtensionMetadata",
    "BaselineExtensionConfig",
    "CNCFBaselineExtension",
    "ProjectExtensions",
    "CNCFProjectConfig",
    # Context storage abstraction layer
    "load_context",
    "get_context_value",
    "get_raw_value",
    "is_context_confirmed",
    "save_context_value",
    "save_context_values",
    "get_context_definitions",
    "get_pending_context",
]
