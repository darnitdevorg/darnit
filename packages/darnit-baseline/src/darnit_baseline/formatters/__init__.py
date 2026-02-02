"""OSPS-specific output formatters."""

from .sarif import (
    build_sarif_rules,
    generate_sarif_audit,
    get_location_for_control,
    result_to_sarif_result,
)

__all__ = [
    "generate_sarif_audit",
    "build_sarif_rules",
    "result_to_sarif_result",
    "get_location_for_control",
]
