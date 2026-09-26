"""Edit ``[trust].repos`` in the operator configuration file (feature 040).

Only that one key is rewritten; every other line of the file, including
comments, is left as it was. The edited file is re-parsed and validated
before it replaces the original.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from darnit.config.operator.schema import OperatorConfig
from darnit.trust.identity import canonical_identity

_TRUST_HEADER = re.compile(r"^\s*\[\s*trust\s*\]\s*(#.*)?$")
_TABLE_HEADER = re.compile(r"^\s*\[")
_REPOS_KEY = re.compile(r"^\s*repos\s*=")


class TrustEditError(Exception):
    """The operator configuration could not be edited safely."""


def _load(path: Path) -> tuple[str, dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    try:
        data = tomllib.loads(text)
        OperatorConfig.model_validate(data)
    except (tomllib.TOMLDecodeError, ValidationError) as exc:
        raise TrustEditError(f"Invalid operator configuration {path}: {exc}") from exc
    return text, data


def _hosts(data: dict[str, Any]) -> list[str]:
    return list(data.get("trust", {}).get("case_insensitive_hosts", []))


def list_trusted_repos(path: Path) -> list[str]:
    """Entries of ``[trust].repos`` as written, or an empty list without a file."""
    if not path.is_file():
        return []
    _, data = _load(path)
    return list(data.get("trust", {}).get("repos", []))


def _render(repos: list[str]) -> str:
    return "repos = [" + ", ".join(json.dumps(r) for r in repos) + "]\n"


def _replace_repos(text: str, repos: list[str]) -> str:
    lines = text.splitlines(keepends=True)
    header = next((i for i, line in enumerate(lines) if _TRUST_HEADER.match(line)), None)
    if header is None:
        if "trust" in tomllib.loads(text):
            raise TrustEditError("[trust] is not written as a table; edit trust.repos by hand")
        separator = "" if not text or text.endswith("\n") else "\n"
        return f"{text}{separator}\n[trust]\n{_render(repos)}"

    end = next((i for i in range(header + 1, len(lines)) if _TABLE_HEADER.match(lines[i])), len(lines))
    start = next((i for i in range(header + 1, end) if _REPOS_KEY.match(lines[i])), None)
    if start is None:
        return "".join([*lines[: header + 1], _render(repos), *lines[header + 1 :]])

    for stop in range(start + 1, end + 1):
        try:
            tomllib.loads("".join(lines[start:stop]))
        except tomllib.TOMLDecodeError:
            continue
        return "".join([*lines[:start], _render(repos), *lines[stop:]])
    raise TrustEditError("could not locate the end of trust.repos; edit it by hand")


def _write(path: Path, text: str, mode: int) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".toml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _update(path: Path, repos: list[str], text: str, data: dict[str, Any]) -> None:
    new_text = _replace_repos(text, repos)
    new_data = tomllib.loads(new_text)
    expected = {**data, "trust": {**data.get("trust", {}), "repos": repos}}
    if new_data != expected:
        raise TrustEditError("editing trust.repos would change other settings; edit it by hand")
    OperatorConfig.model_validate(new_data)
    _write(path, new_text, path.stat().st_mode & 0o777)


def add_trusted_repo(path: Path, identity: str) -> bool:
    """Add ``identity`` (normalized) to ``[trust].repos``; False when already present."""
    if not path.exists():
        canonical = canonical_identity(identity)
        if canonical is None:
            raise TrustEditError(f"{identity!r} is not a repository identity; expected HOST/NAMESPACE/NAME")
        if not path.parent.exists():
            path.parent.mkdir(mode=0o700, parents=True)
            os.chmod(path.parent, 0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"schema_version = 1\n\n[trust]\n{_render([canonical])}")
        os.chmod(path, 0o600)
        return True

    text, data = _load(path)
    hosts = _hosts(data)
    canonical = canonical_identity(identity, hosts)
    if canonical is None:
        raise TrustEditError(f"{identity!r} is not a repository identity; expected HOST/NAMESPACE/NAME")
    repos = list(data.get("trust", {}).get("repos", []))
    if canonical in {canonical_identity(r, hosts) for r in repos}:
        return False
    _update(path, [*repos, canonical], text, data)
    return True


def remove_trusted_repo(path: Path, identity: str) -> None:
    """Remove every ``[trust].repos`` entry whose canonical form matches ``identity``."""
    if not path.is_file():
        raise TrustEditError(f"Operator configuration not found: {path}")
    text, data = _load(path)
    hosts = _hosts(data)
    canonical = canonical_identity(identity, hosts)
    if canonical is None:
        raise TrustEditError(f"{identity!r} is not a repository identity; expected HOST/NAMESPACE/NAME")
    repos = list(data.get("trust", {}).get("repos", []))
    kept = [r for r in repos if canonical_identity(r, hosts) != canonical]
    if len(kept) == len(repos):
        raise TrustEditError(f"{canonical} is not in trust.repos of {path}")
    _update(path, kept, text, data)
