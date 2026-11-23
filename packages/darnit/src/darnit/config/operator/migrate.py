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

from pydantic import ValidationError

from darnit.config.loader import load_project_config_checked, update_extension_file
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
        if key == "plugins" and isinstance(value, dict):
            # Only plugins.allowed exists in operator configuration; darnit
            # does not verify plugin signatures (framework-design 6.6).
            if "allowed" in value:
                operator[key] = {"allowed": value["allowed"]}
            rest = {k: v for k, v in value.items() if k != "allowed"}
            if rest:
                unsupported[key] = rest
        elif key in _OPERATOR_TABLES:
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
        if "plugins" in unsupported:
            lines.append("# darnit does not verify plugin signatures; restrict plugins with [plugins] allowed.")
        lines.extend(f"# {line}" if line else "#" for line in _toml(unsupported))
    while lines[-1] in ("", "#"):
        lines.pop()
    return "\n".join(lines) + "\n"


def _unsupported_names(unsupported: dict[str, Any]) -> list[str]:
    names = [k for k in unsupported if k not in ("controls", "plugins")]
    names.extend(f"plugins.{k}" for k in unsupported.get("plugins") or {})
    for control_id, entry in (unsupported.get("controls") or {}).items():
        if isinstance(entry, dict):
            names.extend(f"controls.{control_id}.{k}" for k in entry)
        else:
            names.append(f"controls.{control_id}")
    return names


def _read_project_file(repo: Path) -> dict[str, Any]:
    """The current ``.project/darnit.yaml`` content, refusing when a ``.project/`` file is invalid.

    Like every other ``.project/`` writer, migration does not write over a
    present but unreadable or invalid ``.project/project.yaml`` or
    ``.project/darnit.yaml``; it reports the validation errors instead
    (framework-design.md 7.9, FR-019/FR-020).
    """
    files = load_project_config_checked(str(repo))
    if files.invalid:
        raise MigrationError(
            "a .project/ file is present but invalid; fix it and re-run. Nothing was written: "
            + "; ".join(files.errors)
        )
    return dict(files.extension.data or {})


def _set_claims(claims: dict[str, dict[str, Any]]):
    """Round-trip mutation that sets only the migrated claims under ``controls:``."""

    def mutate(data: Any) -> None:
        controls = data.get("controls")
        if not isinstance(controls, dict):
            controls = data["controls"] = {}
        for control_id, claim in claims.items():
            controls[control_id] = claim

    return mutate


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

    existing = _read_project_file(repo)
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
        # Round-trip write: comments, key order, and formatting already in
        # .project/darnit.yaml are kept; only the migrated claims change (#524).
        update_extension_file(str(repo), _set_claims({cid: controls[cid] for cid in result.written}))
    return result
