"""Audit profile resolution and control ID filtering.

Resolves profile names (short or qualified) to concrete AuditProfileConfig
instances, and filters control lists based on profile definitions.
"""

from typing import Any

from darnit.config.framework_schema import AuditProfileConfig
from darnit.core.logging import get_logger
from darnit.core.plugin import ControlSpec

logger = get_logger("config.profile_resolver")


class ProfileNotFoundError(Exception):
    """Raised when a profile name cannot be resolved."""

    def __init__(self, name: str, available: dict[str, list[str]]):
        self.name = name
        self.available = available
        profiles_list = "; ".join(
            f"{impl}: {', '.join(names)}" for impl, names in available.items()
        )
        super().__init__(
            f"Profile '{name}' not found. Available profiles: {profiles_list}"
        )


class ProfileAmbiguousError(Exception):
    """Raised when a short profile name matches multiple implementations."""

    def __init__(self, name: str, implementations: list[str]):
        self.name = name
        self.implementations = implementations
        super().__init__(
            f"Profile '{name}' is defined by multiple implementations: "
            f"{', '.join(implementations)}. "
            f"Use '<impl>:{name}' to disambiguate "
            f"(e.g., '{implementations[0]}:{name}')."
        )


def resolve_profile(
    name: str,
    implementations: dict[str, dict[str, AuditProfileConfig]],
) -> tuple[str, AuditProfileConfig]:
    """Resolve a profile name to an (implementation_name, AuditProfileConfig) pair.

    Args:
        name: Profile name. Either a short name ("onboard") or qualified
              ("gittuf:onboard").
        implementations: Mapping of implementation name → profile dict.
            Each profile dict maps profile name → AuditProfileConfig.

    Returns:
        Tuple of (implementation_name, AuditProfileConfig).

    Raises:
        ProfileNotFoundError: If no implementation defines this profile.
        ProfileAmbiguousError: If multiple implementations define it.
    """
    # Build available profiles for error messages
    available = {
        impl: list(profiles.keys())
        for impl, profiles in implementations.items()
        if profiles
    }

    # Qualified name: "impl:profile"
    if ":" in name:
        impl_name, profile_name = name.split(":", 1)
        profiles = implementations.get(impl_name, {})
        if profile_name in profiles:
            return (impl_name, profiles[profile_name])
        raise ProfileNotFoundError(name, available)

    # Short name: scan all implementations
    matches: list[tuple[str, AuditProfileConfig]] = []
    for impl_name, profiles in implementations.items():
        if name in profiles:
            matches.append((impl_name, profiles[name]))

    if len(matches) == 1:
        return matches[0]
    elif len(matches) == 0:
        raise ProfileNotFoundError(name, available)
    else:
        raise ProfileAmbiguousError(
            name, [impl_name for impl_name, _ in matches]
        )


def resolve_profile_control_ids(
    profile: AuditProfileConfig,
    all_controls: list[ControlSpec],
) -> list[str]:
    """Resolve a profile to a list of control IDs.

    When a profile specifies both `controls` (explicit IDs) and `tags`
    (filter), the result is their union.

    Args:
        profile: The audit profile configuration.
        all_controls: All controls from the implementation.

    Returns:
        Deduplicated list of control IDs matching the profile.
    """
    result_ids: set[str] = set()

    # Explicit control IDs
    if profile.controls:
        valid_ids = {c.control_id for c in all_controls}
        for control_id in profile.controls:
            if control_id in valid_ids:
                result_ids.add(control_id)
            else:
                logger.warning(
                    f"Profile references unknown control '{control_id}', skipping"
                )

    # Tag-based filtering
    if profile.tags:
        for control in all_controls:
            if _matches_tags(control, profile.tags):
                result_ids.add(control.control_id)

    return sorted(result_ids)


def _matches_tags(control: ControlSpec, tags: dict[str, Any]) -> bool:
    """Check if a control matches all tag filters.

    Supports exact match and comparison operators via key suffixes:
      - key: exact equality
      - key_gte: greater than or equal
      - key_lte: less than or equal
    """
    for key, expected in tags.items():
        # Handle comparison operators
        if key.endswith("_gte"):
            base_key = key[:-4]
            actual = control.tags.get(base_key)
            if actual is None:
                return False
            try:
                if float(actual) < float(expected):
                    return False
            except (TypeError, ValueError):
                return False
        elif key.endswith("_lte"):
            base_key = key[:-4]
            actual = control.tags.get(base_key)
            if actual is None:
                return False
            try:
                if float(actual) > float(expected):
                    return False
            except (TypeError, ValueError):
                return False
        else:
            # Exact match
            actual = control.tags.get(key)
            if actual != expected:
                return False
    return True
