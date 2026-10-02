"""Config-aware file resolution for controls.

This module provides functions to resolve file paths for controls by:
1. Checking .project/ configuration references first
2. Falling back to pattern-based discovery
3. Updating .project/ after remediation creates files

This enables bidirectional synchronization between checks/remediation
and .project/ configuration.
"""

import os
import types
from typing import Any

from pydantic import BaseModel

from darnit.config.discovery import discover_files
from darnit.config.loader import (
    ProjectFilesInvalid,
    get_default_extension,
    load_project_config,
    load_project_config_checked,
    render_project_config_update,
)
from darnit.config.schema import BaselineExtension, PathRef, ProjectConfig
from darnit.core.logging import get_logger

logger = get_logger("config.resolver")


def resolve_file_for_control(
    local_path: str,
    control_id: str,
    file_locations: dict[str, list[str]],
    control_reference_mapping: dict[str, str],
) -> tuple[str | None, str]:
    """Resolve file path for a control, checking .project/ first.

    This function implements a two-phase lookup:
    1. First, check if there's a reference in .project/ configuration
    2. If no reference, fall back to pattern-based file discovery

    Args:
        local_path: Repository path
        control_id: OSPS control ID (e.g., "OSPS-DO-02.01")
        file_locations: Mapping of ref_path -> possible file patterns
        control_reference_mapping: Mapping of control_id -> ref_path (e.g., "security.policy")

    Returns:
        Tuple of (file_path, source) where source is:
        - "config": Found via .project/ reference
        - "discovered": Found via pattern discovery
        - "none": Not found
    """
    # Get the reference path for this control (e.g., "security.policy")
    ref_path = control_reference_mapping.get(control_id)

    # 1. Try .project/ reference first
    config = load_project_config(local_path)
    if config and ref_path:
        parts = ref_path.split(".", 1)
        if len(parts) == 2:
            section, field = parts
            config_path = config.get_path(section, field)
            if config_path:
                full_path = os.path.join(local_path, config_path)
                if os.path.exists(full_path):
                    logger.debug(
                        f"Control {control_id}: resolved via .project/ reference: {config_path}"
                    )
                    return config_path, "config"
                else:
                    logger.debug(
                        f"Control {control_id}: .project/ reference {config_path} does not exist"
                    )

    # 2. Fall back to pattern discovery
    if ref_path and ref_path in file_locations:
        discovered = discover_files(local_path, {ref_path: file_locations[ref_path]})
        if ref_path in discovered:
            discovered_path = discovered[ref_path]
            logger.debug(
                f"Control {control_id}: discovered file {discovered_path} (not in .project/)"
            )
            return discovered_path, "discovered"

    logger.debug(f"Control {control_id}: no file found")
    return None, "none"


def _model_field(model: type[BaseModel], name: str) -> type[BaseModel] | None:
    """The model type of ``model``'s field ``name`` (unwrapping ``X | None``), or None."""
    info = model.model_fields.get(name)
    if info is None:
        return None
    annotation: Any = info.annotation
    candidates = annotation.__args__ if isinstance(annotation, types.UnionType) else (annotation,)
    return next((c for c in candidates if isinstance(c, type) and issubclass(c, BaseModel)), None)


def reference_key(reference: str) -> str | None:
    """The dotted ``.project/`` key that holds the file path for ``reference`` (``<section>.<field>``), or None.

    A standard CNCF path field is its own key; a path field of the darnit
    extension is prefixed with the extension's schema key. Only fields typed
    as a path reference qualify (feature 043, framework-design 4.3).
    """
    section, sep, field = reference.partition(".")
    if not sep or not section or not field or "." in field:
        return None
    extension = get_default_extension()
    prefix = f"{extension.schema_key}." if extension else None
    for model, key_prefix in ((ProjectConfig, ""), (BaselineExtension, prefix)):
        section_model = _model_field(model, section)
        if key_prefix is not None and section_model is not None and _model_field(section_model, field) is PathRef:
            return f"{key_prefix}{section}.{field}"
    return None


def _set_reference(config: ProjectConfig, key: str, path: str) -> None:
    extension = get_default_extension()
    parts = key.split(".")
    target: BaseModel = config
    if extension and parts[0] == extension.schema_key:
        target, parts = config.get_extension(), parts[1:]
    section, field = parts
    holder = getattr(target, section)
    if holder is None:
        section_model = _model_field(type(target), section)
        assert section_model is not None
        holder = section_model()
        setattr(target, section, holder)
    setattr(holder, field, PathRef(path=path))


def render_reference_update(
    local_path: str, reference: str, created_file_path: str
) -> tuple[dict[str, str], str | None]:
    """The ``.project/`` files that would record ``created_file_path`` under ``reference``; writes nothing.

    A reference is recorded only into an empty field (FR-015). Returns the
    files mapped to their new text (empty when nothing needs writing) and,
    when the reference is not recorded, why: the field already names another
    file, ``reference`` is not a project path field, or ``.project/`` is
    invalid. A field already holding ``created_file_path`` needs nothing.
    """
    key = reference_key(reference)
    if key is None:
        return {}, f"{reference} is not a project path field"
    files = load_project_config_checked(local_path)
    if files.invalid:
        return {}, f".project/ is invalid: {'; '.join(files.errors)}"
    section, field = reference.split(".", 1)
    current = files.config.get_path(section, field) if files.config is not None else None
    if current == created_file_path:
        return {}, None
    if current:
        return {}, f"{reference} already names {current}"
    try:
        rendered = render_project_config_update(
            local_path, [key], lambda config: _set_reference(config, key, created_file_path)
        )
    except ProjectFilesInvalid as e:
        return {}, f".project/ is invalid: {e}"
    return rendered, None


def update_config_after_file_create(
    local_path: str,
    control_id: str,
    created_file_path: str,
    control_reference_mapping: dict[str, str],
) -> bool:
    """Record a created file's reference in ``.project/``, only into an empty field.

    A field that already names a different file is left unchanged (feature
    043, FR-015). Remediation records references through the executor from
    ``project_reference`` (framework-design 4.3); this function serves other
    callers that pass their own mapping.

    Args:
        local_path: Repository path
        control_id: Control ID whose reference to record
        created_file_path: Path to the created file (relative to repo)
        control_reference_mapping: Mapping of control_id -> ``<section>.<field>``

    Returns:
        True if config was updated, False otherwise (no mapping, already set,
        a different reference kept, or ``.project/`` invalid)
    """
    reference = control_reference_mapping.get(control_id)
    if not reference:
        logger.debug(f"Control {control_id}: no reference mapping, cannot update .project/")
        return False

    rendered, kept = render_reference_update(local_path, reference, created_file_path)
    if kept:
        logger.info(f"Not updating .project/ for {control_id}: {kept}")
    if not rendered:
        return False
    for path, text in rendered.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    logger.info(f"Updated .project/ with {reference} = {created_file_path}")
    return True


def sync_discovered_file_to_config(
    local_path: str,
    control_id: str,
    discovered_path: str,
    control_reference_mapping: dict[str, str],
) -> bool:
    """Sync a discovered file to .project/ config.

    When a file is found via discovery (not via config reference),
    this function can be called to add it to the config for future lookups.

    Args:
        local_path: Repository path
        control_id: OSPS control ID
        discovered_path: Path to the discovered file (relative to repo)
        control_reference_mapping: Mapping of control_id -> ref_path

    Returns:
        True if config was updated, False otherwise
    """
    return update_config_after_file_create(
        local_path=local_path,
        control_id=control_id,
        created_file_path=discovered_path,
        control_reference_mapping=control_reference_mapping,
    )


__all__ = [
    "reference_key",
    "render_reference_update",
    "resolve_file_for_control",
    "update_config_after_file_create",
    "sync_discovered_file_to_config",
]
