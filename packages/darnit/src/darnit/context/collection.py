"""Context collection with resolution priority and file parsing.

This module implements the context resolution priority:
1. .project/project.yaml - Primary source of truth
2. File sources (MAINTAINERS.md, etc.) - Parse from existing files
3. User prompt - Fall back to asking the user

It also implements file parsers for extracting values from various formats:
- markdown_list: Extract lists from markdown files
- yaml_path: Extract values from YAML files using dot-notation paths
- json_path: Extract values from JSON files using JSONPath expressions
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from darnit.core.logging import get_logger

logger = get_logger("context.collection")


# =============================================================================
# File Parsers
# =============================================================================


def parse_markdown_list(file_path: Path, pattern: str | None = None) -> list[str]:
    """Parse a list from a markdown file.

    Extracts items from:
    - Bullet lists (- item, * item)
    - Numbered lists (1. item)
    - @mentions anywhere in the file
    - Code blocks (for CODEOWNERS format)

    Args:
        file_path: Path to the markdown file
        pattern: Optional regex pattern to filter/extract items

    Returns:
        List of extracted values
    """
    if not file_path.exists():
        return []

    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.debug(f"Could not read {file_path}: {e}")
        return []

    items: list[str] = []

    # Extract @mentions (GitHub usernames)
    mentions = re.findall(r"@([\w-]+)", content)
    if mentions:
        items.extend([f"@{m}" for m in mentions])

    # Extract bullet list items
    bullet_items = re.findall(r"^[\s]*[-*]\s+(.+)$", content, re.MULTILINE)
    items.extend(bullet_items)

    # Extract numbered list items
    numbered_items = re.findall(r"^[\s]*\d+\.\s+(.+)$", content, re.MULTILINE)
    items.extend(numbered_items)

    # Apply pattern filter if provided
    if pattern:
        try:
            regex = re.compile(pattern)
            items = [item for item in items if regex.search(item)]
        except re.error:
            logger.warning(f"Invalid pattern: {pattern}")

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_items: list[str] = []
    for item in items:
        item = item.strip()
        if item and item not in seen:
            seen.add(item)
            unique_items.append(item)

    return unique_items


def parse_yaml_path(file_path: Path, path: str) -> Any:
    """Extract a value from a YAML file using dot-notation path.

    Args:
        file_path: Path to the YAML file
        path: Dot-notation path (e.g., "security.policy.path")

    Returns:
        The extracted value, or None if not found
    """
    if not file_path.exists():
        return None

    try:
        import yaml

        content = file_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)

        if not isinstance(data, dict):
            return None

        # Navigate the path
        current = data
        for key in path.split("."):
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None

        return current
    except Exception as e:
        logger.debug(f"Could not parse YAML {file_path}: {e}")
        return None


def parse_json_path(file_path: Path, path: str) -> Any:
    """Extract a value from a JSON file using JSONPath-like expression.

    Supports simple dot-notation paths and basic JSONPath:
    - "$.field.subfield" - JSONPath style
    - "field.subfield" - Simple dot notation

    Args:
        file_path: Path to the JSON file
        path: JSONPath expression or dot-notation path

    Returns:
        The extracted value, or None if not found
    """
    if not file_path.exists():
        return None

    try:
        content = file_path.read_text(encoding="utf-8")
        data = json.loads(content)

        # Normalize path (remove leading $.)
        if path.startswith("$."):
            path = path[2:]

        if not isinstance(data, dict):
            return None

        # Navigate the path
        current = data
        for key in path.split("."):
            # Handle array indexing [0]
            if "[" in key:
                base_key, idx_part = key.split("[", 1)
                idx = int(idx_part.rstrip("]"))
                if base_key:
                    current = current.get(base_key)
                if isinstance(current, list) and 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return None
            elif isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None

        return current
    except Exception as e:
        logger.debug(f"Could not parse JSON {file_path}: {e}")
        return None


def parse_codeowners(file_path: Path) -> list[str]:
    """Parse GitHub CODEOWNERS file to extract maintainers.

    Args:
        file_path: Path to CODEOWNERS file

    Returns:
        List of @mentions (users and teams)
    """
    if not file_path.exists():
        return []

    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.debug(f"Could not read {file_path}: {e}")
        return []

    maintainers: set[str] = set()

    for line in content.splitlines():
        # Skip comments and empty lines
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Extract @mentions from the line
        mentions = re.findall(r"@([\w/-]+)", line)
        for mention in mentions:
            # Handle org/team format
            if "/" in mention:
                maintainers.add(f"@{mention}")
            else:
                maintainers.add(f"@{mention}")

    return list(maintainers)


# =============================================================================
# Resolution Priority
# =============================================================================


def resolve_context_value(
    key: str,
    definition: dict[str, Any],
    repo_path: Path,
    project_context: dict[str, Any] | None = None,
) -> tuple[Any, str | None]:
    """Resolve a context value following the priority chain.

    Resolution priority:
    1. .project/project.yaml (via project_context param)
    2. File source (definition.source with definition.parser)
    3. Auto-detection (if definition.auto_detect is true)
    4. None (requires prompt)

    Args:
        key: The context key name
        definition: The context definition from TOML
        repo_path: Path to the repository
        project_context: Pre-loaded .project/ context (optional)

    Returns:
        Tuple of (value, resolution_method)
        - resolution_method is one of: "project", "file", "auto", None (needs prompt)
    """
    # 1. Check .project/project.yaml
    if project_context:
        store_path = definition.get("store_as")
        if store_path:
            value = _get_nested_value(project_context, store_path)
            if value is not None:
                return value, "project"

    # 2. Check file source
    source = definition.get("source")
    parser = definition.get("parser", "auto")
    if source:
        source_path = repo_path / source
        if source_path.exists():
            value = _parse_file_source(source_path, parser, definition)
            if value is not None:
                return value, "file"

    # 3. Check hint_sources (common file locations)
    hint_sources = definition.get("hint_sources", [])
    for hint_source in hint_sources:
        hint_path = repo_path / hint_source
        if hint_path.exists():
            # Infer parser from filename
            parser = _infer_parser(hint_path)
            value = _parse_file_source(hint_path, parser, definition)
            if value is not None:
                return value, f"file:{hint_source}"

    # 4. Auto-detection not yet implemented in this layer
    # (handled by context sieve via _try_sieve_detection)

    return None, None


def _get_nested_value(data: dict[str, Any], path: str) -> Any:
    """Get a nested value using dot notation."""
    current = data
    for key in path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


def _parse_file_source(
    file_path: Path,
    parser: str,
    definition: dict[str, Any],
) -> Any:
    """Parse a file source using the specified parser."""
    if parser == "markdown_list":
        pattern = definition.get("pattern")
        return parse_markdown_list(file_path, pattern) or None

    elif parser == "yaml_path":
        path = definition.get("extract_path", "")
        return parse_yaml_path(file_path, path)

    elif parser == "json_path":
        path = definition.get("extract_path", "")
        return parse_json_path(file_path, path)

    elif parser == "codeowners":
        return parse_codeowners(file_path) or None

    elif parser == "auto":
        return _auto_parse(file_path, definition)

    else:
        logger.warning(f"Unknown parser: {parser}")
        return None


def _auto_parse(file_path: Path, definition: dict[str, Any]) -> Any:
    """Auto-detect parser based on file extension and content."""
    suffix = file_path.suffix.lower()

    # JSON files
    if suffix == ".json":
        path = definition.get("extract_path", "")
        return parse_json_path(file_path, path)

    # YAML files
    if suffix in (".yaml", ".yml"):
        path = definition.get("extract_path", "")
        return parse_yaml_path(file_path, path)

    # CODEOWNERS file
    if file_path.name in ("CODEOWNERS", "MAINTAINERS"):
        return parse_codeowners(file_path)

    # Markdown files - extract lists
    if suffix == ".md":
        return parse_markdown_list(file_path, definition.get("pattern"))

    # Default: try markdown list parser
    return parse_markdown_list(file_path, definition.get("pattern"))


def _infer_parser(file_path: Path) -> str:
    """Infer the appropriate parser from the file path."""
    name = file_path.name.upper()
    suffix = file_path.suffix.lower()

    if name == "CODEOWNERS":
        return "codeowners"
    if suffix == ".json":
        return "json_path"
    if suffix in (".yaml", ".yml"):
        return "yaml_path"
    if suffix == ".md":
        return "markdown_list"

    return "auto"


# =============================================================================
# Validation
# =============================================================================


def validate_context_value(
    value: Any,
    definition: dict[str, Any],
) -> tuple[bool, str | None]:
    """Validate a context value against its definition.

    Args:
        value: The value to validate
        definition: The context definition from TOML

    Returns:
        Tuple of (is_valid, error_message)
    """
    ctx_type = definition.get("type", "string")
    pattern = definition.get("pattern")
    values = definition.get("values")  # For enum types

    # Type validation
    if ctx_type == "boolean":
        if isinstance(value, bool):
            return True, None
        if isinstance(value, str):
            if value.lower() in ("true", "yes", "1"):
                return True, None
            if value.lower() in ("false", "no", "0"):
                return True, None
        return False, "Expected a boolean value (true/false)"

    elif ctx_type in ("list", "list[string]", "list_or_path"):
        if isinstance(value, list):
            return True, None
        if isinstance(value, str):
            # Accept path to file or comma-separated values
            return True, None
        return False, "Expected a list or path"

    elif ctx_type == "email":
        if isinstance(value, str):
            if re.match(r"^[^@]+@[^@]+\.[^@]+$", value):
                return True, None
        return False, "Expected a valid email address"

    elif ctx_type == "enum":
        if values and value not in values:
            return False, f"Expected one of: {', '.join(values)}"
        return True, None

    elif ctx_type == "string":
        if not isinstance(value, str):
            return False, "Expected a string"
        # Pattern validation
        if pattern:
            try:
                if not re.match(pattern, value):
                    return False, f"Value must match pattern: {pattern}"
            except re.error:
                logger.warning(f"Invalid pattern in definition: {pattern}")
        return True, None

    return True, None


def coerce_context_value(
    value: Any,
    definition: dict[str, Any],
) -> Any:
    """Coerce a value to the expected type based on definition.

    Args:
        value: The raw value
        definition: The context definition

    Returns:
        The coerced value
    """
    ctx_type = definition.get("type", "string")

    if ctx_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "yes", "1")
        return bool(value)

    elif ctx_type in ("list", "list[string]"):
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            # Split comma-separated values
            return [v.strip() for v in value.split(",") if v.strip()]
        return [value]

    elif ctx_type == "list_or_path":
        # Keep as-is - could be a path or a list
        return value

    return value


__all__ = [
    # Parsers
    "parse_markdown_list",
    "parse_yaml_path",
    "parse_json_path",
    "parse_codeowners",
    # Resolution
    "resolve_context_value",
    # Validation
    "validate_context_value",
    "coerce_context_value",
]
