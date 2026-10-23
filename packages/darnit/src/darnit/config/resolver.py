"""Recording a created file's path in ``.project/`` (feature 043, framework-design 4.3)."""

import types
from typing import Any

from pydantic import BaseModel

from darnit.config.loader import (
    ProjectFilesInvalid,
    get_default_extension,
    load_project_config_checked,
    render_project_config_update,
)
from darnit.config.schema import BaselineExtension, PathRef, ProjectConfig


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


__all__ = [
    "reference_key",
    "render_reference_update",
]
