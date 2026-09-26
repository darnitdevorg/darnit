"""Locate, validate, and trust-check operator configuration (feature 040).

Resolution order (every driver): an explicit path given at launch, else the
per-user default location, else built-in defaults. The file is refused when it
resolves to a path inside the audited repository, and its permissions are
checked the way OpenSSH's ``StrictModes`` does. Strict mode is switched on by
the caller (a launch option), by recognized CI, or by the file itself; the
file can never switch it off. See contracts/operator-config.md.
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from darnit.config.operator.schema import OperatorConfig
from darnit.core.logging import get_logger
from darnit.stores.defaults.platform_paths import user_config_dir
from darnit.trust.ci import is_recognized_ci

logger = get_logger("config.operator.loader")

BUILTIN_DEFAULTS = "builtin-defaults"
CONFIG_FILENAME = "config.toml"


class OperatorConfigError(Exception):
    """Operator configuration could not be loaded safely."""


@dataclass(frozen=True)
class LoadedOperatorConfig:
    config: OperatorConfig
    source: str
    digest: str | None
    permission_check: str
    strict: bool
    searched: list[str] = field(default_factory=list)

    def report(self) -> dict[str, str | None]:
        """The ``operator_config`` block every audit report carries (FR-009)."""
        return {"source": self.source, "digest": self.digest, "permission_check": self.permission_check}


@dataclass(frozen=True)
class LaunchOptions:
    """Operator configuration options given when a driver process was launched."""

    path: str | None = None
    strict: bool = False


_launch_options = LaunchOptions()


def set_launch_options(path: str | Path | None, *, strict: bool = False) -> None:
    """Record the launch-time ``--operator-config`` and ``--strict-operator-config`` values."""
    global _launch_options
    _launch_options = LaunchOptions(path=None if path is None else str(path), strict=strict)


def get_launch_options() -> LaunchOptions:
    return _launch_options


def _permissions_checkable() -> bool:
    return sys.platform != "win32" and hasattr(os, "getuid")


def _permission_problem(path: Path) -> str | None:
    """Return a description of the first unsafe ownership or mode, if any.

    The file and each parent directory up to the user's home (or the
    filesystem root) must be owned by the current user or root and must not be
    group- or world-writable. Sticky world-writable directories such as /tmp
    are skipped, since others cannot replace entries in them.
    """
    uid = os.getuid()
    home = Path.home().resolve()
    current = path
    while True:
        st = current.stat()
        is_dir = current != path
        sticky = bool(st.st_mode & stat.S_ISVTX)
        if st.st_uid not in (uid, 0):
            return f"{current} is owned by uid {st.st_uid}"
        if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH) and not (is_dir and sticky):
            return f"{current} is group- or world-writable"
        if current == home or current.parent == current:
            return None
        current = current.parent


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _format_validation_error(path: Path, error: ValidationError) -> str:
    problems = "; ".join(
        f"{'.'.join(str(part) for part in e['loc']) or '<root>'}: {e['msg']}" for e in error.errors()
    )
    return f"Invalid operator configuration {path}: {problems}"


def load_operator_config(
    explicit_path: str | Path | None = None,
    *,
    audit_target: str | Path | None = None,
    strict: bool = False,
) -> LoadedOperatorConfig:
    """Load operator configuration for an audit of ``audit_target``."""
    default_path = user_config_dir() / CONFIG_FILENAME
    searched = [str(default_path)]
    strict = strict or is_recognized_ci()

    if explicit_path is not None:
        path = Path(explicit_path).expanduser()
        if not path.is_file():
            raise OperatorConfigError(f"Operator configuration not found: {path}")
    elif default_path.is_file():
        path = default_path
    else:
        return LoadedOperatorConfig(
            config=OperatorConfig(schema_version=1),
            source=BUILTIN_DEFAULTS,
            digest=None,
            permission_check="not_applicable",
            strict=strict,
            searched=searched,
        )

    resolved = path.resolve()
    if audit_target is not None and _inside(resolved, Path(audit_target).resolve()):
        raise OperatorConfigError(
            f"Refusing operator configuration {resolved}: it is inside the audited repository "
            f"{Path(audit_target).resolve()}. Operator configuration must live outside any "
            "repository being audited."
        )

    raw = resolved.read_bytes()
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise OperatorConfigError(f"Invalid operator configuration {path}: {exc}") from exc
    try:
        config = OperatorConfig.model_validate(data)
    except ValidationError as exc:
        raise OperatorConfigError(_format_validation_error(path, exc)) from exc

    strict = strict or config.policy.strict_permissions
    if _permissions_checkable():
        problem = _permission_problem(resolved)
        permission_check = "passed" if problem is None else f"failed: {problem}"
    else:
        problem = "permissions cannot be checked on this platform"
        permission_check = "not_checkable"

    if problem is not None:
        if strict:
            raise OperatorConfigError(
                f"Refusing operator configuration {resolved}: permission check failed ({problem})."
            )
        logger.warning(
            "Operator configuration %s may be writable by others (%s); it will be used. "
            "Run with --strict-operator-config to refuse it.",
            resolved,
            problem,
        )

    return LoadedOperatorConfig(
        config=config,
        source=str(resolved),
        digest=hashlib.sha256(raw).hexdigest(),
        permission_check=permission_check,
        strict=strict,
        searched=searched,
    )


def resolve_operator_config(audit_target: str | Path) -> LoadedOperatorConfig:
    """Load operator configuration for one audit using the launch options.

    Every driver resolves through here, so the CLI, the MCP server, and the
    harness find the same file and apply the containment check against the
    repository each audit targets.
    """
    options = get_launch_options()
    return load_operator_config(options.path, audit_target=audit_target, strict=options.strict)
