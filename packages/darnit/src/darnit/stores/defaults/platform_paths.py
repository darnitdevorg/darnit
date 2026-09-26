"""Platform-conventional path resolution for the ``user-local`` backend.

Feature 034 T023. Concrete implementations of the four helpers whose
skeleton was scaffolded in T004.

Platform dispatch (research R-001):

* Linux (and unknown platforms): XDG Base Directory spec.
  Data:  ``${XDG_DATA_HOME:-$HOME/.local/share}/darnit``
  Cache: ``${XDG_CACHE_HOME:-$HOME/.cache}/darnit``
* macOS (``platform.system() == "Darwin"``):
  Data:  ``~/Library/Application Support/darnit``
  Cache: ``~/Library/Caches/darnit``
* Windows (``platform.system() == "Windows"``):
  Data:  ``%LOCALAPPDATA%\\darnit\\Data``
  Cache: ``%LOCALAPPDATA%\\darnit\\Cache``

User configuration (feature 040, research R1) is resolved separately by
``user_config_dir()``: ``~/.config/darnit`` on Linux and macOS (honoring an
absolute ``$XDG_CONFIG_HOME``), ``%APPDATA%\\darnit`` on Windows. Relative
``XDG_*`` values are ignored, as the XDG Base Directory spec requires.

Unknown platforms fall through to the XDG branch as the safest
heuristic. FR-014 forbids new runtime dependencies, so `platformdirs`
is deliberately not used.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

from darnit.core.logging import get_logger

logger = get_logger("stores.platform_paths")

__all__ = [
    "xdg_data_home",
    "xdg_cache_home",
    "xdg_config_home",
    "user_data_root",
    "user_cache_root",
    "user_config_dir",
]


def _xdg_dir(var: str, default: Path) -> Path:
    override = os.environ.get(var)
    if override:
        path = Path(override).expanduser()
        if path.is_absolute():
            return path
        logger.debug("Ignoring relative %s=%r", var, override)
    return default


def xdg_data_home() -> Path:
    """Return an absolute ``$XDG_DATA_HOME`` if set, else ``$HOME/.local/share``."""
    return _xdg_dir("XDG_DATA_HOME", Path.home() / ".local" / "share")


def xdg_cache_home() -> Path:
    """Return an absolute ``$XDG_CACHE_HOME`` if set, else ``$HOME/.cache``."""
    return _xdg_dir("XDG_CACHE_HOME", Path.home() / ".cache")


def xdg_config_home() -> Path:
    """Return an absolute ``$XDG_CONFIG_HOME`` if set, else ``$HOME/.config``."""
    return _xdg_dir("XDG_CONFIG_HOME", Path.home() / ".config")


def user_data_root() -> Path:
    """Return the platform-conventional data root for darnit.

    ``<data-root>/darnit`` per platform (attestations + reports subtree
    live under here as ``.../darnit/attestations/`` and ``.../darnit/reports/``).
    """
    system = platform.system()
    if system == "Darwin":
        root = Path.home() / "Library" / "Application Support" / "darnit"
    elif system == "Windows":
        base = os.environ.get(
            "LOCALAPPDATA",
            str(Path.home() / "AppData" / "Local"),
        )
        root = Path(base).expanduser() / "darnit" / "Data"
    else:
        # Linux and unknown platforms use XDG.
        root = xdg_data_home() / "darnit"
    logger.debug("user_data_root resolved (%s): %s", system, root)
    return root


def user_cache_root() -> Path:
    """Return the platform-conventional cache root for darnit."""
    system = platform.system()
    if system == "Darwin":
        root = Path.home() / "Library" / "Caches" / "darnit"
    elif system == "Windows":
        base = os.environ.get(
            "LOCALAPPDATA",
            str(Path.home() / "AppData" / "Local"),
        )
        root = Path(base).expanduser() / "darnit" / "Cache"
    else:
        root = xdg_cache_home() / "darnit"
    logger.debug("user_cache_root resolved (%s): %s", system, root)
    return root


def user_config_dir() -> Path:
    """Return the directory holding the operator configuration file.

    Linux, macOS, and unknown platforms use XDG (``~/.config/darnit``); macOS
    deliberately follows the CLI convention rather than
    ``~/Library/Application Support``. Windows uses ``%APPDATA%\\darnit``.
    """
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(base).expanduser() / "darnit"
    return xdg_config_home() / "darnit"
