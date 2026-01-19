"""Adapters for Test Checks Framework."""

from .builtin import (
    TrivialCheckAdapter,
    TrivialRemediationAdapter,
    get_test_check_adapter,
    get_test_remediation_adapter,
)

__all__ = [
    "TrivialCheckAdapter",
    "TrivialRemediationAdapter",
    "get_test_check_adapter",
    "get_test_remediation_adapter",
]
