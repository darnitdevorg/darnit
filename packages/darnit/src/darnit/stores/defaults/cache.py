"""Filesystem-backed ``AuditCacheStore`` default.

Feature 033 T016. Reads/writes cache envelopes under
``<root>/<sanitized_cache_key>.json`` with tempfile-then-rename atomic
semantics (matches the pre-feature behavior of
:mod:`darnit.core.audit_cache`).

MUST NOT raise on read or write per the AuditCacheStore Protocol's
best-effort contract; failures return None (read) or are logged and
swallowed (write).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from darnit.core.logging import get_logger
from darnit.stores.defaults.attestation import _sanitize_filename

logger = get_logger("stores.defaults.cache")


class FilesystemAuditCacheStore:
    """Read/write cache envelopes under ``<root>``."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def _path(self, cache_key: str) -> Path:
        return self._root / f"{_sanitize_filename(cache_key)}.json"

    def read(self, cache_key: str) -> dict[str, Any] | None:
        target = self._path(cache_key)
        if not target.exists():
            return None
        try:
            with open(target, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as err:
            logger.debug("audit cache read failed for %s: %s", target, err)
            return None

    def write(self, cache_key: str, envelope: dict[str, Any]) -> None:
        target = self._path(cache_key)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Atomic write: tempfile then rename (matches pre-feature
            # semantics from darnit.core.audit_cache).
            fd, tmp_path = tempfile.mkstemp(
                dir=str(target.parent),
                suffix=".tmp",
                prefix="audit-cache-",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(envelope, f, indent=2)
                os.replace(tmp_path, str(target))
            except Exception:
                # Best-effort cleanup on rename failure.
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as err:
            logger.warning("audit cache write failed for %s: %s", target, err)

    def close(self) -> None:
        return None


__all__ = ["FilesystemAuditCacheStore"]
