"""Filesystem-backed ``ProjectStateStore`` default.

Feature 033 T016. Reads ``.project/project.yaml`` and
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
    from darnit.context.dot_project import ProjectConfig


class FilesystemProjectStateStore:
    """Read ``.project/`` YAML files on the local filesystem.

    Args:
        repo_path: Root of the repository whose ``.project/`` this store
            reads.
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

    def close(self) -> None:
        return None


__all__ = ["FilesystemProjectStateStore"]
