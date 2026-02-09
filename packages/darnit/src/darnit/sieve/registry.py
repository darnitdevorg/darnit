"""Control registry for sieve-based control definitions."""

from darnit.core.logging import get_logger

from .models import ControlSpec

logger = get_logger("sieve.registry")


class ControlRegistry:
    """Registry of controls with sieve verification definitions."""

    def __init__(self):
        self._specs: dict[str, ControlSpec] = {}

    def register(self, spec: ControlSpec, overwrite: bool = False) -> bool:
        """Register a control specification.

        Args:
            spec: The control specification to register
            overwrite: If False (default), skip if control already registered
                      If True, overwrite existing registration

        Returns:
            True if registered, False if skipped (already exists)
        """
        if not overwrite and spec.control_id in self._specs:
            logger.debug(f"Control {spec.control_id} already registered, skipping")
            return False
        self._specs[spec.control_id] = spec
        return True

    def get(self, control_id: str) -> ControlSpec | None:
        """Get control specification by ID."""
        return self._specs.get(control_id)

    def has(self, control_id: str) -> bool:
        """Check if control is registered."""
        return control_id in self._specs

    def list_controls(self) -> list[str]:
        """List all registered control IDs."""
        return list(self._specs.keys())

    def get_all_specs(self) -> list[ControlSpec]:
        """Get all registered control specifications."""
        return list(self._specs.values())

    def get_specs_by_level(self, level: int) -> list[ControlSpec]:
        """Get control specifications for a specific level."""
        return [s for s in self._specs.values() if s.level == level]

    def get_specs_by_domain(self, domain: str) -> list[ControlSpec]:
        """Get control specifications for a specific domain."""
        return [s for s in self._specs.values() if s.domain == domain]


# Global registry instance
_registry = ControlRegistry()


def get_control_registry() -> ControlRegistry:
    """Get the global control registry."""
    return _registry


def register_control(spec: ControlSpec, overwrite: bool = False) -> bool:
    """Register a control specification in the global registry.

    Args:
        spec: The control specification to register
        overwrite: If True, overwrite existing registration

    Returns:
        True if registered, False if skipped (already exists)
    """
    return _registry.register(spec, overwrite=overwrite)
