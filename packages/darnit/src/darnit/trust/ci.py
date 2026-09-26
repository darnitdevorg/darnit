"""CI platform detection (feature 040, research R4)."""

from __future__ import annotations

import os


def is_recognized_ci() -> bool:
    """True when running under a CI platform darnit recognizes."""
    return os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("GITLAB_CI") == "true"
