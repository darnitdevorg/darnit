"""File and configuration discovery for darnit framework."""

import glob as glob_module
import json
import os
import re

from darnit.config.schema import (
    CIConfig,
    DependenciesConfig,
    DocumentationConfig,
    ExtendedGovernance,
    ExtendedQuality,
    GovernanceConfig,
    LegalConfig,
    PathRef,
    ProjectConfig,
    SecurityConfig,
)
from darnit.core.logging import get_logger

logger = get_logger("config.discovery")


def discover_files(
    local_path: str,
    file_locations: dict[str, list[str]] | None = None
) -> dict[str, str]:
    """Discover existing files that map to .project.yaml references.

    Args:
        local_path: Path to the repository
        file_locations: Mapping of ref_path -> list of possible file patterns.
                       If None, returns empty dict.

    Returns:
        Dict of ref_path -> discovered_file_path
    """
    if file_locations is None:
        return {}

    discovered = {}

    for ref_path, patterns in file_locations.items():
        for pattern in patterns:
            full_pattern = os.path.join(local_path, pattern)
            matches = glob_module.glob(full_pattern)
            if matches:
                # Use first match, relative path
                rel_path = os.path.relpath(matches[0], local_path)
                discovered[ref_path] = rel_path
                break

    return discovered


def discover_ci_config(local_path: str) -> CIConfig | None:
    """Discover CI/CD configuration from the repository.

    Args:
        local_path: Path to the repository

    Returns:
        CIConfig if CI is detected, None otherwise
    """
    # Detect GitHub Actions
    github_workflows = os.path.join(local_path, ".github", "workflows")
    if os.path.isdir(github_workflows):
        config = CIConfig(provider="github")

        workflows = []
        for f in os.listdir(github_workflows):
            if f.endswith(('.yml', '.yaml')):
                workflows.append(f".github/workflows/{f}")

        config.workflows = workflows

        # Detect specific workflow capabilities
        for workflow_path in workflows:
            full_path = os.path.join(local_path, workflow_path)
            try:
                with open(full_path, encoding='utf-8') as f:
                    content = f.read()

                # Detect testing
                if re.search(r'(npm test|pytest|cargo test|go test|jest|mocha)', content, re.IGNORECASE):
                    if workflow_path not in config.testing:
                        config.testing.append(workflow_path)

                # Detect code quality
                if re.search(r'(eslint|flake8|pylint|rubocop|clippy|golangci)', content, re.IGNORECASE):
                    if workflow_path not in config.code_quality:
                        config.code_quality.append(workflow_path)

                # Detect security scanning
                if re.search(r'(codeql|snyk|trivy|grype|bandit|safety)', content, re.IGNORECASE):
                    if workflow_path not in config.security_scanning:
                        config.security_scanning.append(workflow_path)

            except OSError:
                continue

        # Check for dependabot
        for dependabot_name in ["dependabot.yml", "dependabot.yaml"]:
            dependabot_path = os.path.join(local_path, ".github", dependabot_name)
            if os.path.exists(dependabot_path):
                config.dependency_scanning = f".github/{dependabot_name}"
                break

        return config

    # Detect GitLab CI
    if os.path.exists(os.path.join(local_path, ".gitlab-ci.yml")):
        return CIConfig(provider="gitlab")

    # Detect CircleCI
    if os.path.isdir(os.path.join(local_path, ".circleci")):
        return CIConfig(provider="circleci")

    # Detect Jenkins
    if os.path.exists(os.path.join(local_path, "Jenkinsfile")):
        return CIConfig(provider="jenkins")

    # Detect Azure Pipelines
    if os.path.exists(os.path.join(local_path, "azure-pipelines.yml")):
        return CIConfig(provider="azure")

    return None


def discover_project_name(local_path: str) -> str | None:
    """Try to discover the project name from various sources.

    Args:
        local_path: Path to the repository

    Returns:
        Discovered project name or None
    """
    # Try package.json
    try:
        pkg_path = os.path.join(local_path, "package.json")
        if os.path.exists(pkg_path):
            with open(pkg_path) as f:
                data = json.load(f)
                if "name" in data:
                    return data["name"]
    except (OSError, json.JSONDecodeError):
        pass

    # Try pyproject.toml
    try:
        import tomllib
        pyproj_path = os.path.join(local_path, "pyproject.toml")
        if os.path.exists(pyproj_path):
            with open(pyproj_path, 'rb') as f:
                data = tomllib.load(f)
                if "project" in data and "name" in data["project"]:
                    return data["project"]["name"]
    except (OSError, ImportError):
        pass

    # Try Cargo.toml
    try:
        import tomllib
        cargo_path = os.path.join(local_path, "Cargo.toml")
        if os.path.exists(cargo_path):
            with open(cargo_path, 'rb') as f:
                data = tomllib.load(f)
                if "package" in data and "name" in data["package"]:
                    return data["package"]["name"]
    except (OSError, ImportError):
        pass

    # Try go.mod
    try:
        go_mod_path = os.path.join(local_path, "go.mod")
        if os.path.exists(go_mod_path):
            with open(go_mod_path) as f:
                first_line = f.readline().strip()
                if first_line.startswith("module "):
                    module_path = first_line[7:].strip()
                    # Return last part of module path
                    return module_path.split("/")[-1]
    except OSError:
        pass

    # Fall back to directory name
    return os.path.basename(os.path.abspath(local_path))


def _set_config_path(config: ProjectConfig, section: str, field: str, path: str):
    """Set a path reference in the config.

    Handles both standard CNCF sections and x-openssf-baseline extension.
    """
    # Standard sections
    if section == "security":
        if config.security is None:
            config.security = SecurityConfig()
        setattr(config.security, field, PathRef(path=path))
    elif section == "governance":
        if config.governance is None:
            config.governance = GovernanceConfig()
        setattr(config.governance, field, PathRef(path=path))
    elif section == "legal":
        if config.legal is None:
            config.legal = LegalConfig()
        setattr(config.legal, field, PathRef(path=path))
    elif section == "documentation":
        if config.documentation is None:
            config.documentation = DocumentationConfig()
        setattr(config.documentation, field, PathRef(path=path))
    else:
        # Try extension sections
        ext = config.get_extension()

        if section == "governance" and field in ("maintainers", "code_of_conduct"):
            if ext.governance is None:
                ext.governance = ExtendedGovernance()
            setattr(ext.governance, field, PathRef(path=path))
        elif section == "quality":
            if ext.quality is None:
                ext.quality = ExtendedQuality()
            setattr(ext.quality, field, PathRef(path=path))
        elif section == "dependencies":
            if ext.dependencies is None:
                ext.dependencies = DependenciesConfig()
            setattr(ext.dependencies, field, path)


def sync_discovered_to_config(
    config: ProjectConfig,
    local_path: str,
    file_locations: dict[str, list[str]] | None = None,
    fix: bool = False
) -> list[str]:
    """Synchronize discovered files with project configuration.

    Args:
        config: The project configuration to sync
        local_path: Path to the repository
        file_locations: Mapping of ref_path -> list of possible file patterns
        fix: If True, add discovered files to config

    Returns:
        List of changes (discovered but not in config, or in config but missing)
    """
    changes = []
    discovered = discover_files(local_path, file_locations)

    for ref_path, file_path in discovered.items():
        # Parse section.field from ref_path
        parts = ref_path.split(".", 1)
        if len(parts) != 2:
            continue

        section, field = parts

        # Check if already in config
        existing = config.get_path(section, field)

        if existing is None:
            changes.append(f"DISCOVERED: {ref_path} -> {file_path}")
            if fix:
                _set_config_path(config, section, field, file_path)

        elif existing != file_path:
            # Check if declared path exists
            if not os.path.exists(os.path.join(local_path, existing)):
                changes.append(f"MISMATCH: {ref_path} declared as {existing} but found {file_path}")

    # Check for declared references that don't exist
    sections_to_check = [
        ("security", config.security),
        ("governance", config.governance),
        ("legal", config.legal),
        ("documentation", config.documentation),
    ]

    for section_name, section_obj in sections_to_check:
        if section_obj is None:
            continue

        for field_name in section_obj.model_fields:
            ref = getattr(section_obj, field_name, None)
            if ref and isinstance(ref, PathRef):
                full_path = os.path.join(local_path, ref.path)
                if not os.path.exists(full_path):
                    changes.append(f"MISSING: {section_name}.{field_name} -> {ref.path}")

    # Sync CI config
    ci_discovered = discover_ci_config(local_path)
    if ci_discovered:
        ext = config.get_extension()
        if ext.ci is None:
            changes.append("DISCOVERED: CI configuration")
            if fix:
                ext.ci = ci_discovered

    return changes


def discover_and_create_config(
    local_path: str,
    file_locations: dict[str, list[str]] | None = None,
    name: str | None = None,
    project_type: str = "software"
) -> ProjectConfig:
    """Discover files and create a new config with discovered values.

    Args:
        local_path: Path to the repository
        file_locations: Mapping of ref_path -> list of possible file patterns
        name: Project name (auto-detected if not provided)
        project_type: Type of project

    Returns:
        New ProjectConfig with discovered files populated
    """
    from darnit.config.schema import create_minimal_config

    project_name = name or discover_project_name(local_path) or "unnamed"

    config = create_minimal_config(
        name=project_name,
        project_type=project_type,
    )
    config.local_path = local_path

    # Sync discovered files
    sync_discovered_to_config(config, local_path, file_locations, fix=True)

    return config
