"""Configuration loading and saving for .project/ directory.

This module handles loading and saving CNCF .project configuration files
with extension fields in separate files.

Structure:
    .project/
    ├── project.yaml   # CNCF standard fields (name, security, governance, etc.)
    ├── darnit.yaml    # Darnit extension (controls, context, artifacts, etc.)
    └── <other>.yaml   # Future extensions (security.yaml, compliance.yaml, etc.)

Extension files are registered in EXTENSION_REGISTRY and can be added without
modifying the core loading/saving logic.
"""

import os
from dataclasses import dataclass
from typing import Any

import yaml
from pydantic import ValidationError

from darnit.config.schema import (
    ProjectConfig,
    create_minimal_config,
)
from darnit.core.logging import get_logger

logger = get_logger("config.loader")


# =============================================================================
# Constants
# =============================================================================

PROJECT_DIR = ".project"
PROJECT_FILE = "project.yaml"

# CNCF standard fields (go in project.yaml)
CNCF_STANDARD_FIELDS = {
    "name", "description", "schema_version", "type",
    "maturity_log", "repositories", "website", "artwork",
    "social", "mailing_lists", "audits",
    "security", "governance", "legal", "documentation",
}


# =============================================================================
# Extension Registry
# =============================================================================

@dataclass
class ExtensionSpec:
    """Specification for an extension file."""
    filename: str
    schema_key: str  # Key in ProjectConfig (e.g., "x-openssf-baseline")
    header: list[str]  # Comment lines for file header
    is_default: bool = False  # If True, catches all non-CNCF fields


# Registry of extension files
# Order matters: default extension should be last
EXTENSION_REGISTRY: list[ExtensionSpec] = [
    ExtensionSpec(
        filename="darnit.yaml",
        schema_key="x-openssf-baseline",
        header=[
            ".project/darnit.yaml - Darnit Extension",
            "",
            "Extension fields for security tooling (OpenSSF Baseline, etc.)",
            "Standard CNCF .project fields are in project.yaml",
        ],
        is_default=True,  # Catches all non-CNCF, non-extension fields
    ),
    # Future extensions can be added here:
    # ExtensionSpec(
    #     filename="security.yaml",
    #     schema_key="x-security",
    #     header=["Security scanning configuration"],
    # ),
]


def get_extension_by_key(schema_key: str) -> ExtensionSpec | None:
    """Get extension spec by schema key."""
    for ext in EXTENSION_REGISTRY:
        if ext.schema_key == schema_key:
            return ext
    return None


def get_default_extension() -> ExtensionSpec | None:
    """Get the default extension (catches unmatched fields)."""
    for ext in EXTENSION_REGISTRY:
        if ext.is_default:
            return ext
    return None


# Legacy exports for backward compatibility
EXTENSION_FILE = "darnit.yaml"


# =============================================================================
# Cache
# =============================================================================

_config_cache: dict[str, ProjectConfig] = {}


# =============================================================================
# Custom YAML Dumper
# =============================================================================

class CleanDumper(yaml.SafeDumper):
    """YAML dumper with clean multiline string handling."""
    pass


def _str_representer(dumper: yaml.SafeDumper, data: str) -> yaml.Node:
    """Represent multiline strings with literal block style."""
    if '\n' in data:
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)


CleanDumper.add_representer(str, _str_representer)


# =============================================================================
# Loading Functions
# =============================================================================

def _load_yaml_file(path: str) -> dict[str, Any] | None:
    """Load a YAML file and return its contents."""
    try:
        with open(path, encoding='utf-8') as f:
            data = yaml.safe_load(f)
        return data if data else None
    except (yaml.YAMLError, OSError) as e:
        logger.debug(f"Failed to load {path}: {e}")
        return None


def load_project_config(local_path: str) -> ProjectConfig | None:
    """Load project configuration from .project/ directory.

    Loads project.yaml and all registered extension files, merging them
    into a single ProjectConfig.

    Args:
        local_path: Path to the repository root

    Returns:
        ProjectConfig if found and valid, None otherwise
    """
    project_dir = os.path.join(local_path, PROJECT_DIR)

    if not os.path.isdir(project_dir):
        logger.debug(f"No .project/ directory in {local_path}")
        return None

    # Load main project.yaml
    project_path = os.path.join(project_dir, PROJECT_FILE)
    if not os.path.exists(project_path):
        logger.debug(f"No project.yaml in {project_dir}")
        return None

    project_data = _load_yaml_file(project_path)
    if not project_data:
        return None

    # Load all registered extension files
    for ext in EXTENSION_REGISTRY:
        ext_path = os.path.join(project_dir, ext.filename)
        ext_data = _load_yaml_file(ext_path)
        if ext_data:
            project_data[ext.schema_key] = ext_data
            logger.debug(f"Loaded extension {ext.filename} as {ext.schema_key}")

    logger.debug(f"Loaded config from {project_path}")

    try:
        config = ProjectConfig.model_validate(project_data)
        config.config_path = project_path
        config.local_path = local_path
        return config
    except ValidationError as e:
        logger.warning(f"Schema validation failed for {project_path}: {e}")
        return None


# =============================================================================
# Saving Functions
# =============================================================================

def _split_config_data(
    data: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Split config data into CNCF fields and extension files.

    Returns:
        Tuple of (project_data, extension_files)
        where extension_files is {filename: data}
    """
    project_data = {}
    extension_files: dict[str, dict[str, Any]] = {}
    default_ext = get_default_extension()

    for key, value in data.items():
        if key in CNCF_STANDARD_FIELDS:
            # CNCF standard field -> project.yaml
            project_data[key] = value
        else:
            # Check if this is a known extension key
            ext = get_extension_by_key(key)
            if ext:
                # Known extension -> flatten into its file
                if isinstance(value, dict):
                    if ext.filename not in extension_files:
                        extension_files[ext.filename] = {}
                    extension_files[ext.filename].update(value)
            elif default_ext:
                # Unknown field -> default extension file
                if default_ext.filename not in extension_files:
                    extension_files[default_ext.filename] = {}
                extension_files[default_ext.filename][key] = value

    return project_data, extension_files


def _write_yaml_file(path: str, data: dict[str, Any], header_lines: list[str]) -> None:
    """Write data to a YAML file with header comments."""
    with open(path, 'w', encoding='utf-8') as f:
        for line in header_lines:
            f.write(f"# {line}\n")
        f.write("\n")

        yaml.dump(
            data,
            f,
            Dumper=CleanDumper,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )


def save_project_config(config: ProjectConfig, local_path: str) -> str:
    """Save project configuration to .project/ directory.

    Creates project.yaml and extension files as needed.

    Args:
        config: ProjectConfig to save
        local_path: Path to the repository root

    Returns:
        Path to the saved project.yaml file
    """
    project_dir = os.path.join(local_path, PROJECT_DIR)
    os.makedirs(project_dir, exist_ok=True)

    # Export config to dict
    data = config.model_dump(
        mode='json',
        by_alias=True,
        exclude_none=True,
        exclude={'config_path', 'local_path', '_type_exclusions'}
    )

    # Split data into project.yaml and extension files
    project_data, extension_files = _split_config_data(data)

    # Write project.yaml (CNCF standard fields)
    project_path = os.path.join(project_dir, PROJECT_FILE)
    _write_yaml_file(
        project_path,
        project_data,
        [
            ".project/project.yaml - CNCF Project Configuration",
            "https://github.com/cncf/automation/tree/main/utilities/dot-project",
            "",
            "This file contains standard CNCF .project fields.",
            "Extension fields are in separate files (darnit.yaml, etc.)",
        ]
    )

    # Write each extension file
    for ext in EXTENSION_REGISTRY:
        if ext.filename in extension_files:
            ext_path = os.path.join(project_dir, ext.filename)
            _write_yaml_file(ext_path, extension_files[ext.filename], ext.header)
            logger.debug(f"Wrote extension file {ext.filename}")

    return project_path


# =============================================================================
# Utility Functions
# =============================================================================

def get_project_config(
    local_path: str,
    force_reload: bool = False
) -> ProjectConfig | None:
    """Get project config, using cache if available."""
    abs_path = os.path.abspath(local_path)

    if not force_reload and abs_path in _config_cache:
        return _config_cache[abs_path]

    config = load_project_config(abs_path)
    if config:
        _config_cache[abs_path] = config

    return config


def clear_config_cache():
    """Clear the configuration cache."""
    _config_cache.clear()


def init_project_config(
    local_path: str,
    name: str | None = None,
    project_type: str = "software",
    description: str = ""
) -> ProjectConfig:
    """Initialize a new project configuration with discovered values."""
    from darnit.config.discovery import discover_project_name
    from darnit.context.detectors import detect_forge, detect_ci, detect_build_system
    from darnit.config.schema import BaselineExtension, ProjectContext

    project_name = name or discover_project_name(local_path) or "unnamed"

    config = create_minimal_config(
        name=project_name,
        description=description,
        project_type=project_type,
    )
    config.local_path = local_path

    # Auto-detect forge, CI, and build system
    forge = detect_forge(local_path)
    ci = detect_ci(local_path)
    build = detect_build_system(local_path)

    logger.debug(f"Detected forge={forge}, ci={ci}, build={build}")

    # Write detected values into the config
    if config.x_openssf_baseline is None:
        config.x_openssf_baseline = BaselineExtension()
    if config.x_openssf_baseline.context is None:
        config.x_openssf_baseline.context = ProjectContext()

    context = config.x_openssf_baseline.context
    if context.ci_provider is None and ci != "unknown":
        context.ci_provider = ci

    return config


def config_exists(local_path: str) -> bool:
    """Check if .project/project.yaml exists."""
    project_path = os.path.join(local_path, PROJECT_DIR, PROJECT_FILE)
    return os.path.exists(project_path)


def get_config_path(local_path: str) -> str | None:
    """Get path to .project/project.yaml if it exists."""
    project_path = os.path.join(local_path, PROJECT_DIR, PROJECT_FILE)
    if os.path.exists(project_path):
        return project_path
    return None


def get_extension_path(local_path: str, extension: str | None = None) -> str | None:
    """Get path to an extension file.

    Args:
        local_path: Path to the repository root
        extension: Extension filename (default: darnit.yaml)

    Returns:
        Path to extension file if it exists, None otherwise
    """
    filename = extension or EXTENSION_FILE
    ext_path = os.path.join(local_path, PROJECT_DIR, filename)
    if os.path.exists(ext_path):
        return ext_path
    return None


def list_extension_files(local_path: str) -> list[str]:
    """List all extension files that exist in .project/ directory.

    Returns:
        List of extension filenames that exist
    """
    project_dir = os.path.join(local_path, PROJECT_DIR)
    existing = []
    for ext in EXTENSION_REGISTRY:
        if os.path.exists(os.path.join(project_dir, ext.filename)):
            existing.append(ext.filename)
    return existing
