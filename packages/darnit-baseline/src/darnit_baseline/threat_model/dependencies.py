"""Dependency manifest parsing for threat model confidence scoring.

Parses pyproject.toml, package.json, requirements.txt, and go.mod to
determine what the project actually depends on.  This provides a
high-confidence signal that a technology is genuinely *used* (vs merely
referenced in a regex or comment).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from darnit.core.logging import get_logger
from darnit.core.repo_files import open_in_repository

logger = get_logger("threat_model.dependencies")

# Maps dependency names (lowercase) to the datastore / framework / auth
# identifiers used elsewhere in the threat-model patterns module.
# A single dependency may map to multiple identifiers (e.g. "prisma" relates
# to both the prisma ORM and whatever DB it targets).
_DEPENDENCY_MAP: dict[str, list[str]] = {
    # --- Databases / datastores ---
    "psycopg": ["postgresql"],
    "psycopg2": ["postgresql"],
    "psycopg2-binary": ["postgresql"],
    "asyncpg": ["postgresql"],
    "pg": ["postgresql"],
    "postgres": ["postgresql"],
    "pg-promise": ["postgresql"],
    "pymysql": ["mysql"],
    "mysqlclient": ["mysql"],
    "mysql2": ["mysql"],
    "mysql": ["mysql"],
    "pymongo": ["mongodb"],
    "mongoose": ["mongodb"],
    "mongodb": ["mongodb"],
    "redis": ["redis"],
    "ioredis": ["redis"],
    "aioredis": ["redis"],
    "sqlite3": ["sqlite"],
    "better-sqlite3": ["sqlite"],
    "aiosqlite": ["sqlite"],
    "boto3": ["s3"],
    "@aws-sdk/client-s3": ["s3"],
    "@prisma/client": ["prisma"],
    "prisma": ["prisma"],
    "drizzle-orm": ["drizzle"],
    "@supabase/supabase-js": ["supabase"],
    "supabase": ["supabase"],
    # --- Frameworks ---
    "next": ["nextjs"],
    "express": ["express"],
    "fastapi": ["fastapi"],
    "django": ["django"],
    "flask": ["flask"],
    "react": ["react"],
    "vue": ["vue"],
    "nuxt": ["vue"],
    # --- Auth ---
    "next-auth": ["nextauth"],
    "@clerk/nextjs": ["clerk"],
    "passport": ["passport"],
    "jsonwebtoken": ["jwt"],
    "jose": ["jwt"],
    "@auth/core": ["jwt"],
    "firebase": ["firebase_auth"],
    "@auth0/nextjs-auth0": ["auth0"],
    "auth0": ["auth0"],
}


def parse_dependency_manifests(repo_path: str) -> set[str]:
    """Return the set of technology identifiers declared in dependency manifests.

    Scans pyproject.toml, setup.cfg, requirements*.txt, package.json, and
    go.mod.  Returns identifiers like ``"postgresql"``, ``"fastapi"`` etc. that
    can be compared against pattern-based detection results to assign confidence.
    """
    declared: set[str] = set()

    _parse_pyproject_toml(repo_path, declared)
    _parse_requirements_txt(repo_path, declared)
    _parse_package_json(repo_path, declared)
    _parse_go_mod(repo_path, declared)

    if declared:
        logger.debug("Dependencies from manifests: %s", sorted(declared))
    return declared


# ---------------------------------------------------------------------------
# Individual parsers
# ---------------------------------------------------------------------------

def _normalise_dep_name(raw: str) -> str:
    """Normalise a dependency name for lookup (lowercase, strip extras/version)."""
    name = raw.strip()
    # Preserve scoped npm packages like @prisma/client
    if name.startswith("@"):
        # Strip version specifier after the package name
        name = re.split(r"[\[>=<~!;\s]", name)[0]
        return name.lower()
    # Strip extras like psycopg2[binary] or version specifiers
    name = re.split(r"[\[>=<~!;@\s]", name)[0]
    return name.lower().replace("_", "-")


def _add_matches(dep_name: str, declared: set[str]) -> None:
    norm = _normalise_dep_name(dep_name)
    if norm in _DEPENDENCY_MAP:
        declared.update(_DEPENDENCY_MAP[norm])


def _parse_pyproject_toml(repo_path: str, declared: set[str]) -> None:
    """Parse pyproject.toml for dependencies."""
    # Walk to find pyproject.toml files (monorepos may have several)
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {
            "node_modules", ".git", "venv", ".venv", "__pycache__",
            "dist", "build", "env",
        }]
        if "pyproject.toml" not in files:
            continue
        path = os.path.join(root, "pyproject.toml")
        try:
            content = _read_file(repo_path, path)
        except OSError:
            continue

        # Lightweight TOML parsing — grab dependency names from quoted
        # strings.  We match all quoted strings that look like Python
        # package specifiers (contain letters, may have version specs).
        # This catches both multi-line arrays and inline arrays.
        for match in re.finditer(r'"([a-zA-Z@][^"]*)"', content):
            _add_matches(match.group(1), declared)
        for match in re.finditer(r"'([a-zA-Z@][^']*)'", content):
            _add_matches(match.group(1), declared)


def _parse_requirements_txt(repo_path: str, declared: set[str]) -> None:
    """Parse requirements*.txt files."""
    for name in os.listdir(repo_path):
        if name.startswith("requirements") and name.endswith(".txt"):
            path = os.path.join(repo_path, name)
            try:
                content = _read_file(repo_path, path)
            except OSError:
                continue
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                _add_matches(line, declared)


def _parse_package_json(repo_path: str, declared: set[str]) -> None:
    """Parse package.json for dependencies and devDependencies."""
    path = os.path.join(repo_path, "package.json")
    if not os.path.isfile(path):
        return
    try:
        content = _read_file(repo_path, path)
        data: dict[str, Any] = json.loads(content)
    except (OSError, json.JSONDecodeError):
        return

    for section in ("dependencies", "devDependencies", "peerDependencies"):
        deps = data.get(section, {})
        if isinstance(deps, dict):
            for dep_name in deps:
                _add_matches(dep_name, declared)


def _parse_go_mod(repo_path: str, declared: set[str]) -> None:
    """Parse go.mod for require directives."""
    path = os.path.join(repo_path, "go.mod")
    if not os.path.isfile(path):
        return
    try:
        content = _read_file(repo_path, path)
    except OSError:
        return
    for match in re.finditer(r"^\s*(\S+)\s+v", content, re.MULTILINE):
        module = match.group(1).split("/")[-1]
        _add_matches(module, declared)


def _read_file(repo_path: str, path: str) -> str:
    with open_in_repository(repo_path, path, errors="ignore", encoding="utf-8") as f:
        return f.read()


__all__ = ["parse_dependency_manifests"]
