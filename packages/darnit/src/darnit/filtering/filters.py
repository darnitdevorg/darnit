"""Filter parsing and matching for CLI tag-based filtering.

Supports filtering controls by attributes like level, domain, tags, and severity.

Usage:
    # Parse filters from --tags arguments
    filters = parse_tags_arg(['level=1', 'domain=VM,security'])

    # Check if a control matches all filters
    if matches_filters(control, filters):
        ...

Grammar:
    filter := key_value | bare_tag
    key_value := key operator value
    key := "level" | "domain" | "severity" | "adapter" | <any_tag_key>
    operator := "=" | "<=" | ">=" | "<" | ">" | "!="
    bare_tag := string  # Matches against tags dict (key exists with truthy value)

Filter Logic:
    - Different fields: AND logic (level=1,domain=AC → level=1 AND domain=AC)
    - Same field repeated: OR logic (priority=low,priority=high → priority=low OR priority=high)
    - Missing tags: Control is EXCLUDED (not included)

Examples:
    level=1                      # level equals 1
    level<=2                     # level <= 2
    domain=VM                    # domain equals VM
    security                     # 'security' key exists in tags with truthy value
    severity>=7.0                # security_severity >= 7.0
    priority=low,priority=high   # priority is low OR high
    level=1,priority=high        # level=1 AND priority=high
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

# Operators in order of precedence (longer operators first to avoid partial matches)
OPERATORS = ["<=", ">=", "!=", "=", "<", ">"]


@dataclass
class ControlFilter:
    """A single filter condition."""

    field: str  # 'level', 'domain', 'tags', 'severity', 'adapter'
    operator: str  # '=', '<=', '>=', '<', '>', '!=', 'in'
    value: Any  # The value to compare


def parse_value(value_str: str) -> int | float | str:
    """Parse a filter value string into appropriate type.

    Args:
        value_str: The string value to parse

    Returns:
        Parsed value as int, float, or string
    """
    value_str = value_str.strip()

    # Try integer
    try:
        return int(value_str)
    except ValueError:
        pass

    # Try float
    try:
        return float(value_str)
    except ValueError:
        pass

    # Return as string
    return value_str


def parse_filter(filter_str: str) -> ControlFilter:
    """Parse a filter string like 'level=1' or 'security'.

    Args:
        filter_str: The filter string to parse

    Returns:
        A ControlFilter instance

    Examples:
        >>> parse_filter('level=1')
        ControlFilter(field='level', operator='=', value=1)

        >>> parse_filter('level<=2')
        ControlFilter(field='level', operator='<=', value=2)

        >>> parse_filter('security')
        ControlFilter(field='tags', operator='in', value='security')
    """
    filter_str = filter_str.strip()

    # Handle comparison operators (check longer operators first)
    for op in OPERATORS:
        if op in filter_str:
            parts = filter_str.split(op, 1)
            if len(parts) == 2:
                key = parts[0].strip()
                value = parse_value(parts[1])
                return ControlFilter(field=key, operator=op, value=value)

    # Bare value = tag filter (e.g., "security" matches controls with that tag)
    return ControlFilter(field="tags", operator="in", value=filter_str)


def parse_tags_arg(tags_args: list[str] | None) -> list[ControlFilter]:
    """Parse all --tags arguments into filters.

    Handles both multiple --tags args and comma-separated values within a single arg.

    Args:
        tags_args: List of --tags argument values

    Returns:
        List of ControlFilter instances

    Examples:
        >>> parse_tags_arg(['level=1', 'domain=VM'])
        [ControlFilter(...), ControlFilter(...)]

        >>> parse_tags_arg(['level=1,domain=VM,security'])
        [ControlFilter(...), ControlFilter(...), ControlFilter(...)]
    """
    if not tags_args:
        return []

    filters = []
    for arg in tags_args:
        # Handle comma-separated within single arg
        for part in arg.split(","):
            part = part.strip()
            if part:
                filters.append(parse_filter(part))

    return filters


def compare(actual: Any, operator: str, expected: Any) -> bool:
    """Compare two values using the specified operator.

    Args:
        actual: The actual value from the control
        operator: The comparison operator
        expected: The expected value from the filter

    Returns:
        True if the comparison succeeds
    """
    if actual is None:
        return False

    try:
        if operator == "=":
            return actual == expected
        elif operator == "!=":
            return actual != expected
        elif operator == "<=":
            return actual <= expected
        elif operator == ">=":
            return actual >= expected
        elif operator == "<":
            return actual < expected
        elif operator == ">":
            return actual > expected
    except TypeError:
        # Comparison failed (e.g., incompatible types)
        return False

    return False


def matches_filter(control: Any, f: ControlFilter) -> bool:
    """Check if a control matches a single filter.

    Args:
        control: A ControlSpec instance
        f: A ControlFilter to check against

    Returns:
        True if the control matches the filter
    """
    if f.field == "level":
        return compare(control.level, f.operator, int(f.value))

    elif f.field == "domain":
        # Domain is extracted from control_id (e.g., OSPS-AC-03.01 -> AC)
        domain = getattr(control, "domain", None)
        if domain is None and hasattr(control, "control_id"):
            # Extract domain from control_id pattern: OSPS-XX-NN.NN
            parts = control.control_id.split("-")
            if len(parts) >= 2:
                domain = parts[1]
        if f.operator == "=":
            return domain == f.value
        elif f.operator == "!=":
            return domain != f.value
        return False

    elif f.field == "tags":
        # Get tags from metadata
        tags = []
        if hasattr(control, "metadata") and isinstance(control.metadata, dict):
            tags = control.metadata.get("tags", [])
        elif hasattr(control, "tags"):
            tags = control.tags or []

        if f.operator == "in" or f.operator == "=":
            return f.value in tags
        elif f.operator == "!=":
            return f.value not in tags
        return f.value in tags

    elif f.field == "severity":
        # Get severity from metadata
        severity = 0.0
        if hasattr(control, "metadata") and isinstance(control.metadata, dict):
            severity = control.metadata.get("security_severity", 0.0)
        elif hasattr(control, "security_severity"):
            severity = control.security_severity or 0.0

        return compare(severity, f.operator, float(f.value))

    elif f.field == "adapter":
        # Match by check adapter name
        adapter = getattr(control, "check_adapter", None)
        if adapter is None and hasattr(control, "check"):
            adapter = getattr(control.check, "adapter", None)

        if f.operator == "=":
            return adapter == f.value
        elif f.operator == "!=":
            return adapter != f.value
        return False

    else:
        # Check if field exists in control's tags dict (for arbitrary tag filtering)
        tags = getattr(control, "tags", None) or {}
        if f.field in tags:
            return compare(tags[f.field], f.operator, f.value)

        # Also check metadata for backward compatibility
        metadata = getattr(control, "metadata", None) or {}
        if f.field in metadata:
            return compare(metadata[f.field], f.operator, f.value)

        # Field not found - exclude this control (user asked for a tag it doesn't have)
        return False


def group_filters_by_field(filters: list[ControlFilter]) -> dict[str, list[ControlFilter]]:
    """Group filters by field name.

    Args:
        filters: List of ControlFilter instances

    Returns:
        Dict mapping field names to lists of filters for that field
    """
    grouped: dict[str, list[ControlFilter]] = defaultdict(list)
    for f in filters:
        grouped[f.field].append(f)
    return dict(grouped)


def matches_filters(control: Any, filters: list[ControlFilter]) -> bool:
    """Check if a control matches filters using AND/OR logic.

    Logic:
        - Different fields: AND logic (all field groups must match)
        - Same field repeated: OR logic (at least one filter in group must match)

    Examples:
        level=1,domain=AC        → level=1 AND domain=AC
        priority=low,priority=high → priority=low OR priority=high
        level=1,priority=low,priority=high → level=1 AND (priority=low OR priority=high)

    Args:
        control: A ControlSpec instance
        filters: List of ControlFilter instances

    Returns:
        True if the control matches the filter logic
    """
    if not filters:
        return True

    # Group filters by field
    grouped = group_filters_by_field(filters)

    # Each field group must have at least one match (AND between groups, OR within group)
    for _field, field_filters in grouped.items():
        # OR logic within the group - at least one must match
        group_matched = False
        for f in field_filters:
            if matches_filter(control, f):
                group_matched = True
                break

        # AND logic between groups - if any group fails, control doesn't match
        if not group_matched:
            return False

    return True


def filter_controls(
    controls: list[Any],
    filters: list[ControlFilter] | None = None,
    include_ids: set | None = None,
    exclude_ids: set | None = None,
) -> list[Any]:
    """Filter controls by filters and include/exclude lists.

    Args:
        controls: List of ControlSpec instances
        filters: Optional list of ControlFilter instances
        include_ids: Optional set of control IDs to include (if set, only these are included)
        exclude_ids: Optional set of control IDs to exclude

    Returns:
        Filtered list of controls
    """
    if not controls:
        return []

    filters = filters or []
    exclude_ids = exclude_ids or set()

    filtered = []
    for control in controls:
        control_id = getattr(control, "control_id", None)

        # Check include list (if specified, only include these)
        if include_ids and control_id not in include_ids:
            continue

        # Check exclude list
        if control_id in exclude_ids:
            continue

        # Check tag filters
        if not matches_filters(control, filters):
            continue

        filtered.append(control)

    return filtered
