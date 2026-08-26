"""Filesystem-backed ``ReportStore`` default.

Feature 033 T016. Writes each format to
``<root>/<report_id>.{md,json,sarif}``.
"""

from __future__ import annotations

from pathlib import Path

from darnit.stores.defaults.attestation import _sanitize_filename
from darnit.stores.errors import StoreOperationError


class FilesystemReportStore:
    """Write audit reports (Markdown/JSON/SARIF) under ``<root>``."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def _write(self, report_id: str, ext: str, content: str) -> None:
        safe_id = _sanitize_filename(report_id)
        target = self._root / f"{safe_id}{ext}"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as err:
            raise StoreOperationError(
                f"failed to write report to {target}: {err}"
            ) from err

    def write_markdown(self, report_id: str, content: str) -> None:
        self._write(report_id, ".md", content)

    def write_json(self, report_id: str, content: str) -> None:
        self._write(report_id, ".json", content)

    def write_sarif(self, report_id: str, content: str) -> None:
        self._write(report_id, ".sarif", content)

    def close(self) -> None:
        return None


__all__ = ["FilesystemReportStore"]
