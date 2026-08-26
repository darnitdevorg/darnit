"""In-memory ReportStore reference backend (feature 033 T020)."""

from __future__ import annotations


class InMemoryReportStore:
    """Dict-backed ReportStore for tests.

    ``self._state`` is a dict keyed by ``(report_id, format)`` where
    format is ``"md"``, ``"json"``, or ``"sarif"``.
    """

    def __init__(self, **kwargs) -> None:
        self._state: dict[tuple[str, str], str] = {}

    def write_markdown(self, report_id: str, contents: str) -> None:
        self._state[(report_id, "md")] = contents

    def write_json(self, report_id: str, contents: str) -> None:
        self._state[(report_id, "json")] = contents

    def write_sarif(self, report_id: str, contents: str) -> None:
        self._state[(report_id, "sarif")] = contents

    def close(self) -> None:
        return None


__all__ = ["InMemoryReportStore"]
