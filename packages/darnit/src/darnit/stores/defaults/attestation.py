"""Filesystem-backed ``AttestationStore`` default.

Feature 033 T016. Writes each attestation bundle to
``<root>/<bundle_id>.<ext>`` where ``<ext>`` derives from the
content_type argument. Reproduces the pre-feature on-disk layout
(``.darnit/attestations/`` under a repo root).
"""

from __future__ import annotations

import re
from pathlib import Path

from darnit.stores.errors import StoreOperationError

# Content-type -> filesystem extension. Keeps darnit's on-disk
# convention explicit and stable for downstream tooling (Sigstore
# verifiers, in-toto readers) that grep for these suffixes.
_CONTENT_TYPE_EXT: dict[str, str] = {
    "application/vnd.in-toto+json": ".intoto.json",
    "application/vnd.dev.sigstore.bundle+json": ".sigstore.json",
    "application/json": ".json",
}


class FilesystemAttestationStore:
    """Write attestation bundles under ``<root>/<bundle_id>.<ext>``."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def write(self, bundle_id: str, bundle_bytes: bytes, content_type: str) -> None:
        ext = _CONTENT_TYPE_EXT.get(content_type, ".bin")
        safe_id = _sanitize_filename(bundle_id)
        target = self._root / f"{safe_id}{ext}"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle_bytes)
        except OSError as err:
            raise StoreOperationError(
                f"failed to write attestation bundle to {target}: {err}"
            ) from err

    def close(self) -> None:
        return None


_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9._+@-]")


def _sanitize_filename(name: str) -> str:
    """Replace filesystem-unsafe characters with `_` for cross-platform safety."""
    return _FILENAME_UNSAFE.sub("_", name) or "unnamed"


__all__ = ["FilesystemAttestationStore"]
