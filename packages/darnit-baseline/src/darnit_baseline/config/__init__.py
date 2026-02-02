"""OSPS-specific configuration mappings."""

from .mappings import (
    CONTROL_REFERENCE_MAPPING,
    DEFAULT_FILE_LOCATIONS,
    PROJECT_TYPE_EXCLUSIONS,
    ProjectType,
)

__all__ = [
    "ProjectType",
    "PROJECT_TYPE_EXCLUSIONS",
    "CONTROL_REFERENCE_MAPPING",
    "DEFAULT_FILE_LOCATIONS",
]
