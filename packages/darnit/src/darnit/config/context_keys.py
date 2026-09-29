"""Canonical context key names, vocabularies, and value digests (feature 042, FR-018, research R9).

Every context key has one name and one vocabulary, taken from the framework
TOML definition. Legacy names and spellings found in stored data are read as
the canonical form; darnit writes only the canonical form.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from darnit.config.context_schema import ContextDefinition

LEGACY_KEY_NAMES: dict[str, str] = {
    "ci.provider": "ci_provider",
    "provider": "ci_provider",
}

_NO_VALUE = object()

LEGACY_VALUES: dict[str, dict[str, Any]] = {
    "ci_provider": {
        "github_actions": "github",
        "gitlab_ci": "gitlab",
        "azure_pipelines": "azure",
        "bitbucket_pipelines": "other",
        "unknown": _NO_VALUE,
    },
}

ORDER_INSENSITIVE_KEYS = frozenset({"maintainers"})

_TRUE_ANSWERS = frozenset({"true", "yes", "y"})
_FALSE_ANSWERS = frozenset({"false", "no", "n"})


def canonical_key(name: str) -> str:
    """The canonical name for a stored or supplied context key name."""
    return LEGACY_KEY_NAMES.get(name, name)


def legacy_names(key: str) -> list[str]:
    """Legacy names that read as ``key``."""
    return [legacy for legacy, canonical in LEGACY_KEY_NAMES.items() if canonical == key]


def normalize_value(key: str, value: Any) -> Any:
    """``value`` in the key's canonical vocabulary; None when it means no value."""
    if isinstance(value, str):
        value = value.strip()
        mapped = LEGACY_VALUES.get(key, {}).get(value, value)
        if mapped is _NO_VALUE:
            return None
        return mapped or None
    if isinstance(value, list):
        return [item.strip() if isinstance(item, str) else item for item in value]
    return value


def vocabulary(definition: ContextDefinition | None) -> list[str] | None:
    """The allowed values of an enum key, or None when the key has no fixed vocabulary."""
    if definition is None or definition.type != "enum":
        return None
    return list(definition.values or [])


def in_vocabulary(value: Any, definition: ContextDefinition | None) -> bool:
    allowed = vocabulary(definition)
    return allowed is None or value in allowed


def coerce_value(definition: ContextDefinition, value: Any) -> Any:
    """A person's answer as a value of the key's type.

    Raises:
        ValueError: the answer is not a value of that type.
    """
    kind = definition.type
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE_ANSWERS:
            return True
        if text in _FALSE_ANSWERS:
            return False
        raise ValueError(f"expected yes or no, got {value!r}")
    if kind == "enum" and isinstance(value, str):
        return value.strip().lower()
    if kind == "list" and isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _canonical_json(key: str, value: Any) -> str:
    normalized = normalize_value(key, value)
    if key in ORDER_INSENSITIVE_KEYS and isinstance(normalized, list):
        normalized = sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str)


def value_digest(key: str, value: Any) -> str:
    """``sha256:`` digest of the normalized value; a confirmation applies only while it matches."""
    return "sha256:" + hashlib.sha256(_canonical_json(key, value).encode("utf-8")).hexdigest()
