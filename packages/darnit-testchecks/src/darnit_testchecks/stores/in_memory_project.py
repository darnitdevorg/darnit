"""In-memory ProjectStateStore reference backend (feature 033 T020)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from darnit.context.dot_project import ProjectConfig


class InMemoryProjectStateStore:
    """Dict-backed ProjectStateStore for tests.

    Seed via constructor ``InMemoryProjectStateStore(project=config)``
    before running the audit.
    Tests can inspect ``store.project`` after the audit for assertions.
    """

    def __init__(
        self,
        project: ProjectConfig | None = None,
        **kwargs: Any,
    ) -> None:
        self.project: ProjectConfig | None = project
        self.read_count = 0

    def read_project(self) -> ProjectConfig | None:
        self.read_count += 1
        return self.project

    def close(self) -> None:
        return None


__all__ = ["InMemoryProjectStateStore"]
