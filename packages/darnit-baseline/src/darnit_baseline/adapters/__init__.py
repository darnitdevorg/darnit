"""Adapters for OpenSSF Baseline check and remediation execution.

This module provides adapter implementations that bridge the declarative
framework configuration with the existing Python check implementations.

Adapters:
    - BuiltinCheckAdapter: Wraps existing Python check functions
    - BuiltinRemediationAdapter: Wraps existing remediation actions
"""

from .builtin import (
    BuiltinCheckAdapter,
    BuiltinRemediationAdapter,
    get_builtin_check_adapter,
    get_builtin_remediation_adapter,
)

__all__ = [
    "BuiltinCheckAdapter",
    "BuiltinRemediationAdapter",
    "get_builtin_check_adapter",
    "get_builtin_remediation_adapter",
]
