"""Filesystem-backed ``ProjectStateStore`` default.

Feature 033 T016. Reads/writes ``.project/project.yaml`` and
``.project/maintainers.yaml`` on the local filesystem. The reader
delegates to the existing :class:`darnit.context.dot_project.DotProjectReader`
via a construction shape that avoids the store-routing path (so the
default backend does not recurse through itself).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from darnit.stores.errors import StoreOperationError

if TYPE_CHECKING:
    from darnit.context.dot_project import MaintainerEntry, ProjectConfig


class FilesystemProjectStateStore:
    """Read/write ``.project/`` YAML files on the local filesystem.

    Args:
        repo_path: Root of the repository whose ``.project/`` this store
            reads and writes.
    """

    def __init__(self, repo_path: Path) -> None:
        self._repo_path = Path(repo_path)

    @property
    def project_yaml(self) -> Path:
        return self._repo_path / ".project" / "project.yaml"

    @property
    def maintainers_yaml(self) -> Path:
        return self._repo_path / ".project" / "maintainers.yaml"

    def read_project(self) -> ProjectConfig | None:
        # Lazy import to avoid circulars during darnit.stores package load.
        from darnit.context.dot_project import DotProjectReader

        if not self.project_yaml.exists():
            return None
        try:
            # DotProjectReader's default path does raw filesystem I/O; the
            # store-aware constructor kwarg lands in T021 and the reader
            # will route BACK through the store's raw-I/O path, which is
            # this function's callers. To break the cycle, this default
            # backend reads YAML directly rather than routing through the
            # reader's store hook. The reader's YAML parsing is exposed
            # via its `_parse_yaml_files` internal path.
            reader = DotProjectReader(self._repo_path)
            return reader.read()
        except Exception as err:  # noqa: BLE001
            raise StoreOperationError(
                f"failed to read {self.project_yaml}: {err}"
            ) from err

    def write_project(self, config: ProjectConfig) -> None:
        # v0 write path piggybacks on the existing DotProjectWriter (which
        # serializes ProjectConfig -> project.yaml). Alternative backends
        # override this.
        from darnit.context.dot_project import DotProjectWriter

        try:
            writer = DotProjectWriter(self._repo_path)
            writer.write(config)
        except Exception as err:  # noqa: BLE001
            raise StoreOperationError(
                f"failed to write {self.project_yaml}: {err}"
            ) from err

    def read_maintainers(self) -> list[MaintainerEntry]:
        config = self.read_project()
        if config is None:
            return []
        return list(getattr(config, "maintainer_entries", []))

    def write_maintainers(self, entries: list[MaintainerEntry]) -> None:
        from darnit.context.dot_project import ProjectConfig

        existing = self.read_project() or ProjectConfig(name="")
        existing.maintainer_entries = list(entries)
        self.write_project(existing)

    def close(self) -> None:
        return None


__all__ = ["FilesystemProjectStateStore"]
