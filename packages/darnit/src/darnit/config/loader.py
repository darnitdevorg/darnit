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
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from darnit.config.schema import (
    BaselineExtension,
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

PROJECT_FILE_HEADER = [
    ".project/project.yaml - CNCF Project Configuration",
    "https://github.com/cncf/automation/tree/main/utilities/dot-project",
    "",
    "This file contains standard CNCF .project fields.",
    "Extension fields are in separate files (darnit.yaml, etc.)",
]

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

@dataclass(frozen=True)
class ProjectFile:
    """One ``.project/`` file: absent, valid, or present but invalid (feature 042, FR-019)."""

    path: str
    state: Literal["absent", "valid", "invalid"]
    data: dict[str, Any] | None = None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectFiles:
    """The project file and darnit's extension file, each checked independently."""

    local_path: str
    project: ProjectFile
    extension: ProjectFile

    @property
    def invalid(self) -> bool:
        return self.project.state == "invalid" or self.extension.state == "invalid"

    @property
    def errors(self) -> list[str]:
        return [
            f"{os.path.join(PROJECT_DIR, os.path.basename(f.path))}: {error}"
            for f in (self.project, self.extension)
            for error in f.errors
        ]

    @property
    def config(self) -> ProjectConfig | None:
        """The merged ProjectConfig read-only callers use, or None."""
        if self.project.data is None:
            return None
        project_data = dict(self.project.data)
        if self.extension.data:
            project_data[get_default_extension().schema_key] = self.extension.data
        try:
            config = ProjectConfig.model_validate(project_data)
        except ValidationError as e:
            logger.warning(f"Schema validation failed for {self.project.path}: {e}")
            return None
        config.config_path = self.project.path
        config.local_path = self.local_path
        return config


def _validation_errors(exc: ValidationError) -> tuple[str, ...]:
    return tuple(f"{'.'.join(str(p) for p in err['loc']) or '(file)'}: {err['msg']}" for err in exc.errors())


def _check_file(path: str, model: type, *, empty_is_valid: bool) -> ProjectFile:
    if not os.path.exists(path):
        return ProjectFile(path, "absent")
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        return ProjectFile(path, "invalid", errors=(f"unreadable: {e}",))
    if data is None:
        if empty_is_valid:
            return ProjectFile(path, "valid", {})
        return ProjectFile(path, "invalid", errors=("the file is empty",))
    if not isinstance(data, dict):
        return ProjectFile(path, "invalid", errors=(f"expected a mapping, found {type(data).__name__}",))
    try:
        model.model_validate(data)
    except ValidationError as e:
        return ProjectFile(path, "invalid", data, _validation_errors(e))
    return ProjectFile(path, "valid", data)


def load_project_config_checked(local_path: str) -> ProjectFiles:
    """Check ``.project/project.yaml`` and ``.project/darnit.yaml`` independently.

    A writer MUST refuse when either file is present but invalid, and report
    ``errors`` to the caller instead of replacing the file (FR-019, FR-020).
    """
    project_dir = os.path.join(local_path, PROJECT_DIR)
    extension = get_default_extension()
    return ProjectFiles(
        local_path=local_path,
        project=_check_file(os.path.join(project_dir, PROJECT_FILE), ProjectConfig, empty_is_valid=False),
        extension=_check_file(os.path.join(project_dir, extension.filename), BaselineExtension, empty_is_valid=True),
    )


def load_project_config(local_path: str) -> ProjectConfig | None:
    """Load project configuration from .project/ directory.

    Loads project.yaml and all registered extension files, merging them
    into a single ProjectConfig. Read-only; writers use
    :func:`load_project_config_checked`.

    Args:
        local_path: Path to the repository root

    Returns:
        ProjectConfig if found and valid, None otherwise
    """
    files = load_project_config_checked(local_path)
    if files.project.state == "absent":
        logger.debug(f"No project.yaml in {os.path.join(local_path, PROJECT_DIR)}")
    return files.config


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
    _write_yaml_file(project_path, project_data, PROJECT_FILE_HEADER)

    # Write each extension file
    for ext in EXTENSION_REGISTRY:
        if ext.filename in extension_files:
            ext_path = os.path.join(project_dir, ext.filename)
            _write_yaml_file(ext_path, extension_files[ext.filename], ext.header)
            logger.debug(f"Wrote extension file {ext.filename}")

    return project_path


def _block_indentation(text: str) -> tuple[int, int]:
    """(mapping indent, sequence dash offset) of a block-style YAML document; (2, 0) when it shows neither."""
    mapping: int | None = None
    offset: int | None = None
    parent: tuple[int, bool] | None = None
    for line in text.splitlines():
        content = line.split(" #", 1)[0].rstrip()
        stripped = content.lstrip(" ")
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(content) - len(stripped)
        is_item = stripped == "-" or stripped.startswith("- ")
        if parent is not None and indent > parent[0] and not parent[1]:
            if is_item and offset is None:
                offset = indent - parent[0]
            elif not is_item and mapping is None:
                mapping = indent - parent[0]
        parent = (indent, is_item) if stripped.endswith(":") else None
        if mapping is not None and offset is not None:
            break
    return mapping or 2, offset or 0


def update_yaml_file(path: str, mutate: Callable[[Any], Any], header_lines: list[str] | None = None) -> bool:
    """Round-trip ``path`` through ruamel.yaml, changing only what ``mutate`` changes.

    Comments, ordering, indentation, and keys ``mutate`` does not touch are
    preserved. A new file starts with ``header_lines`` as comments. Nothing
    is written when ``mutate`` returns False; returns whether the file was written.
    """
    text = render_yaml_update(path, mutate, header_lines)
    if text is None:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def render_yaml_update(path: str, mutate: Callable[[Any], Any], header_lines: list[str] | None = None) -> str | None:
    """The text :func:`update_yaml_file` would write to ``path``, or None when it would write nothing."""
    from io import StringIO

    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap

    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    yaml_rt.width = 4096
    prefix = ""
    data = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        mapping, offset = _block_indentation(text)
        yaml_rt.indent(mapping=mapping, sequence=offset + 2, offset=offset)
        data = yaml_rt.load(text)
        if data is None:
            prefix = text
    elif header_lines:
        prefix = "".join(f"# {line}".rstrip() + "\n" for line in header_lines) + "\n"
    if data is None:
        data = CommentedMap()
    if mutate(data) is False:
        return None

    body = StringIO()
    if data:
        yaml_rt.dump(data, body)
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    return prefix + body.getvalue()


def update_extension_file(local_path: str, mutate: Callable[[Any], None]) -> str:
    """Round-trip update of ``.project/darnit.yaml``; returns its path."""
    extension = get_default_extension()
    path = os.path.join(local_path, PROJECT_DIR, extension.filename)
    update_yaml_file(path, mutate, extension.header)
    return path


class ProjectFilesInvalid(ValueError):
    """A ``.project/`` file is present but unreadable or invalid; nothing was written (FR-019)."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _set_path(node: Any, source: Any, parts: list[str]) -> bool:
    """Copy ``source``'s value at ``parts`` into ``node``, creating only the missing keys; True if ``node`` changed."""
    for i, part in enumerate(parts):
        if not isinstance(source, dict) or part not in source:
            return False
        source = source[part]
        if i == len(parts) - 1 or not isinstance(node.get(part), dict):
            if node.get(part) == source:
                return False
            node[part] = source
            return True
        node = node[part]
    return False


def _set_paths(targets: list[tuple[list[str], Any]]) -> Callable[[Any], bool]:
    def mutate(data: Any) -> bool:
        changed = [_set_path(data, source, parts) for parts, source in targets]
        return any(changed)

    return mutate


def update_project_config(
    local_path: str,
    paths: list[str],
    mutate: Callable[[ProjectConfig], None],
    *,
    create: bool = True,
) -> list[str]:
    """Write only the dotted ``paths`` that ``mutate`` sets on the project configuration (FR-019, FR-020).

    ``mutate`` receives the current :class:`ProjectConfig` (for coercion to the
    schema's types, e.g. a path string to ``{path: ...}``). Each path is then
    written into the file it belongs to -- CNCF fields to ``project.yaml``,
    everything else to ``darnit.yaml`` -- through :func:`update_yaml_file`, so
    comments, ordering, and fields darnit does not own are preserved. An
    absent ``project.yaml`` is created (with ``name`` only) when ``create``.

    Returns:
        The files written.

    Raises:
        ProjectFilesInvalid: a ``.project/`` file is present but invalid.
    """
    written = []
    for path, text in render_project_config_update(local_path, paths, mutate, create=create).items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        written.append(path)
    return written


def render_project_config_update(
    local_path: str,
    paths: list[str],
    mutate: Callable[[ProjectConfig], None],
    *,
    create: bool = True,
) -> dict[str, str]:
    """The files :func:`update_project_config` would write, mapped to their new text; writes nothing.

    Raises:
        ProjectFilesInvalid: a ``.project/`` file is present but invalid.
    """
    files = load_project_config_checked(local_path)
    if files.invalid:
        raise ProjectFilesInvalid(files.errors)
    extension = get_default_extension()
    if files.project.state == "absent":
        if not create:
            return {}
        from darnit.config.discovery import discover_project_name

        name = discover_project_name(local_path) or "unnamed"
        config = ProjectConfig.model_validate({"name": name, extension.schema_key: files.extension.data or {}})
        paths = ["name", *paths]
    else:
        config = files.config
        if config is None:
            raise ProjectFilesInvalid([f"{files.project.path}: does not validate together with {extension.filename}"])

    mutate(config)
    dumped = config.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_unset=True)

    in_extension = dumped.get(extension.schema_key, {})
    project_targets: list[tuple[list[str], Any]] = []
    extension_targets: list[tuple[list[str], Any]] = []
    for path in paths:
        parts = path.split(".")
        if parts[0] in CNCF_STANDARD_FIELDS:
            project_targets.append((parts, dumped))
        elif parts[0] == extension.schema_key:
            extension_targets.append((parts[1:], in_extension))
        else:
            extension_targets.append((parts, dumped if parts[0] in dumped else in_extension))

    rendered: dict[str, str] = {}
    for targets, path, header in (
        (project_targets, os.path.join(local_path, PROJECT_DIR, PROJECT_FILE), PROJECT_FILE_HEADER),
        (extension_targets, os.path.join(local_path, PROJECT_DIR, extension.filename), extension.header),
    ):
        if not targets:
            continue
        text = render_yaml_update(path, _set_paths(targets), header)
        if text is not None:
            rendered[path] = text
    return rendered


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
    """Build a minimal project configuration in memory; nothing is detected or written."""
    from darnit.config.discovery import discover_project_name

    project_name = name or discover_project_name(local_path) or "unnamed"

    config = create_minimal_config(
        name=project_name,
        description=description,
        project_type=project_type,
    )
    config.local_path = local_path
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
