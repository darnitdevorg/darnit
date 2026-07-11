"""OSPS-specific output formatters."""

from .badge import (
    BADGE_BASE_URL,
    control_id_to_key,
    generate_badge_url,
    status_to_badge_status,
)
from .sarif import (
    build_sarif_rules,
    generate_sarif_audit,
    get_location_for_control,
    result_to_sarif_result,
)

__all__ = [
    # Badge formatter
    "generate_badge_url",
    "control_id_to_key",
    "status_to_badge_status",
    "BADGE_BASE_URL",
    # SARIF formatter
    "generate_sarif_audit",
    "build_sarif_rules",
    "result_to_sarif_result",
    "get_location_for_control",
]
