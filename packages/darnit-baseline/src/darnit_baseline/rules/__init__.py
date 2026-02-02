"""OSPS rules catalog for SARIF generation."""

from .catalog import DOMAIN_INFO, OSPS_RULES, get_rule

__all__ = [
    "OSPS_RULES",
    "DOMAIN_INFO",
    "get_rule",
]
