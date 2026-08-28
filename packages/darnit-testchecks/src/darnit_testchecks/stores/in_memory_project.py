"""In-memory ProjectStateStore reference backend (feature 033 T020)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from darnit.context.dot_project import MaintainerEntry, ProjectConfig


class InMemoryProjectStateStore:
    """Dict-backed ProjectStateStore for tests.

    Seed via ``store.write_project(config)`` before running the audit.
    Tests can inspect ``store._state`` after the audit for assertions.
    """

    def __init__(self, **kwargs) -> None:
        self._state: dict[str, object] = {
            "project": None,
            "maintainers": [],
        }
        self.read_count = 0
        self.write_count = 0

    def read_project(self) -> "ProjectConfig | None":
        self.read_count += 1
        return self._state["project"]  # type: ignore[return-value]

    def write_project(self, config: "ProjectConfig") -> None:
        self.write_count += 1
        self._state["project"] = config

    def read_maintainers(self) -> "list[MaintainerEntry]":
        return list(self._state["maintainers"])  # type: ignore[arg-type]

    def write_maintainers(self, entries: "list[MaintainerEntry]") -> None:
        self._state["maintainers"] = list(entries)

    def close(self) -> None:
        return None


__all__ = ["InMemoryProjectStateStore"]
