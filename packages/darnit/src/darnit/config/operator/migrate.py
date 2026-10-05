"""Move a repository's .baseline.toml to its new homes (feature 040, US5, FR-022).

Per-control ``status``/``reason`` become claims in ``.project/darnit.yaml``.
Tool settings are returned as a proposed operator configuration fragment for
the operator to review; this module never writes operator configuration.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from darnit.config.loader import _write_yaml_file, get_default_extension
from darnit.config.merger import BASELINE_TOML
from darnit.config.schema import BaselineExtension, ControlOverride

PROJECT_FILE = Path(".project") / "darnit.yaml"
_CLAIM_FIELDS = ("status", "reason")
_CUSTOM_CONTROL_FIELDS = ("name", "level", "domain")
_OPERATOR_TABLES = ("plugins", "mcp_servers", "stores")
_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


class MigrationError(Exception):
    """The migration could not run without risking the repository's files."""


@dataclass
class MigrationResult:
    project_file: Path
    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    operator_fragment: str = ""
    not_migrated: list[str] = field(default_factory=list)


def _key(key: str) -> str:
    return key if _BARE_KEY.match(key) else json.dumps(key)


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_value(v)}" for k, v in value.items()) + " }"
    raise MigrationError(f"cannot express {value!r} in TOML")


def _tables(path: list[str], table: dict[str, Any]) -> list[str]:
    scalars = {k: v for k, v in table.items() if not isinstance(v, dict) or not v}
    nested = {k: v for k, v in table.items() if isinstance(v, dict) and v}
    lines: list[str] = []
    if scalars or not nested:
        lines.append("[" + ".".join(_key(p) for p in path) + "]")
        lines.extend(f"{_key(k)} = {_value(v)}" for k, v in scalars.items())
        lines.append("")
    for k, v in nested.items():
        lines.extend(_tables([*path, k], v))
    return lines


def _toml(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, dict):
            lines.extend(_tables([key], value))
        else:
            lines.extend([f"{_key(key)} = {_value(value)}", ""])
    return lines


def _split(data: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any], list[str]]:
    """Claims, operator settings, settings operator configuration cannot express, and invalid claims."""
    claims: dict[str, dict[str, Any]] = {}
    operator: dict[str, Any] = {}
    unsupported: dict[str, Any] = {}
    invalid: list[str] = []

    for key, value in data.items():
        if key == "version":
            continue
        if key in _OPERATOR_TABLES:
            operator[key] = value
        elif key != "controls" or not isinstance(value, dict):
            unsupported[key] = value

    for control_id, entry in (data.get("controls") or {}).items():
        if not isinstance(entry, dict):
            unsupported.setdefault("controls", {})[control_id] = entry
            continue
        claim = {k: entry[k] for k in _CLAIM_FIELDS if k in entry}
        rest = {k: v for k, v in entry.items() if k not in _CLAIM_FIELDS}
        if claim:
            try:
                ControlOverride.model_validate(claim)
                claims[control_id] = claim
            except ValidationError:
                invalid.append(f"controls.{control_id}")
        if all(k in rest for k in _CUSTOM_CONTROL_FIELDS):
            operator.setdefault("custom_controls", {})[control_id] = {k: v for k, v in rest.items() if k != "custom"}
            continue
        if "passes" in rest:
            operator.setdefault("controls", {})[control_id] = {"passes": rest.pop("passes")}
        if rest:
            unsupported.setdefault("controls", {})[control_id] = rest
    return claims, operator, unsupported, invalid


def _fragment(operator: dict[str, Any], unsupported: dict[str, Any]) -> str:
    if not operator and not unsupported:
        return ""
    lines = [
        "# Proposed operator configuration from .baseline.toml. Review it, then add it to",
        "# your operator configuration file; darnit does not write it.",
        "",
        *_toml(operator),
    ]
    if unsupported:
        lines.append("# Operator configuration has no equivalent for these settings; they are not migrated.")
        if "extends" in unsupported:
            lines.append("# Select the framework with the --framework option instead of extends.")
        lines.extend(f"# {line}" if line else "#" for line in _toml(unsupported))
    while lines[-1] in ("", "#"):
        lines.pop()
    return "\n".join(lines) + "\n"


def _unsupported_names(unsupported: dict[str, Any]) -> list[str]:
    names = [k for k in unsupported if k != "controls"]
    for control_id, entry in (unsupported.get("controls") or {}).items():
        if isinstance(entry, dict):
            names.extend(f"controls.{control_id}.{k}" for k in entry)
        else:
            names.append(f"controls.{control_id}")
    return names


def _read_project_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise MigrationError(f"cannot read {PROJECT_FILE}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("controls", {}), dict):
        raise MigrationError(f"{PROJECT_FILE} does not have the expected shape; fix it and re-run")
    return data


def migrate_baseline_toml(repo: Path, *, force: bool = False) -> MigrationResult:
    """Write ``repo``'s .baseline.toml claims to .project/darnit.yaml and propose an operator fragment.

    Args:
        repo: Repository root holding ``.baseline.toml``.
        force: Replace a claim ``.project/darnit.yaml`` already makes for the
            same control; otherwise it is kept and reported as skipped.

    Raises:
        MigrationError: ``.baseline.toml`` is missing or unreadable, or
            ``.project/darnit.yaml`` cannot be read or would not conform to
            its schema. Nothing is written in that case.
    """
    repo = Path(repo)
    source = repo / BASELINE_TOML
    try:
        data = tomllib.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MigrationError(f"no {BASELINE_TOML} in {repo}") from exc
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise MigrationError(f"cannot read {source}: {exc}") from exc

    claims, operator, unsupported, invalid = _split(data)
    result = MigrationResult(
        project_file=repo / PROJECT_FILE,
        operator_fragment=_fragment(operator, unsupported),
        not_migrated=[*_unsupported_names(unsupported), *invalid],
    )

    existing = _read_project_file(result.project_file)
    controls = dict(existing.get("controls") or {})
    for control_id, claim in claims.items():
        current = controls.get(control_id)
        if current == claim:
            result.unchanged.append(control_id)
        elif current is not None and not force:
            result.skipped.append(control_id)
        else:
            controls[control_id] = claim
            result.written.append(control_id)

    if result.written:
        updated = {**existing, "controls": controls}
        try:
            BaselineExtension.model_validate(updated)
        except ValidationError as exc:
            raise MigrationError(f"{PROJECT_FILE} would not conform to its schema: {exc}") from exc
        result.project_file.parent.mkdir(exist_ok=True)
        extension = get_default_extension()
        _write_yaml_file(str(result.project_file), updated, extension.header if extension else [])
    return result
