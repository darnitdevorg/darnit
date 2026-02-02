"""Check-specific helper utilities.

Re-exports common utilities from core.utils for convenience within the checks package.
"""

# Re-export from core utilities for convenience
from darnit.core.utils import (
    file_contains,
    file_exists,
    gh_api,
    gh_api_safe,
    make_result,
    read_file,
)

# Alias for backward compatibility with main.py naming
result = make_result

__all__ = [
    "gh_api",
    "gh_api_safe",
    "file_exists",
    "file_contains",
    "read_file",
    "make_result",
    "result",
]
