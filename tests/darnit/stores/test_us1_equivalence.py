"""US1 equivalence: in-memory project store yields identical mapper context.

Feature 033 T024 / SC-002 (MVP scope). The full audit-driver equivalence
test lives at the integration layer; this focuses on the seam that
matters: the ``DotProjectMapper`` reading via a pluggable
``ProjectStateStore``. Two mappers -- one wired to an
``InMemoryProjectStateStore`` seeded with a ``ProjectConfig``, one
wired to the filesystem default reading the equivalent YAML on disk --
must produce the same context dict. Also asserts the on-disk
``.project/`` is never opened when the in-memory backend is selected.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from darnit_testchecks.stores import InMemoryProjectStateStore

from darnit.config.framework_schema import StoreBlock, StoresConfig
from darnit.context.dot_project import ProjectConfig
from darnit.context.dot_project_mapper import DotProjectMapper
from darnit.stores.selection import resolve_stores

PROJECT_YAML = """
name: eq-fixture
description: Feature 033 US1 equivalence fixture
repositories:
  - https://github.com/example/eq-fixture
schema_version: "1.0.0"
"""


def _seed_on_disk(repo_root: Path) -> None:
    (repo_root / ".project").mkdir()
    (repo_root / ".project" / "project.yaml").write_text(PROJECT_YAML.strip() + "\n")


def _seed_in_memory() -> InMemoryProjectStateStore:
    store = InMemoryProjectStateStore()
    store.write_project(
        ProjectConfig(
            name="eq-fixture",
            description="Feature 033 US1 equivalence fixture",
            repositories=["https://github.com/example/eq-fixture"],
            schema_version="1.0.0",
        )
    )
    return store


class TestUS1MapperEquivalence:
    def test_same_context_from_both_backends(self, tmp_path: Path):
        # Filesystem run
        fs_root = tmp_path / "fs"
        fs_root.mkdir()
        _seed_on_disk(fs_root)
        fs_bundle = resolve_stores(None, repo_path=fs_root)
        fs_mapper = DotProjectMapper(fs_root, project_store=fs_bundle.project)
        fs_context = fs_mapper.get_context()

        # In-memory run
        mem_root = tmp_path / "mem"
        mem_root.mkdir()  # No .project/ on disk.
        mem_store = _seed_in_memory()
        mem_bundle = resolve_stores(
            StoresConfig(project=StoreBlock(backend="in-memory")),
            repo_path=mem_root,
        )
        # Swap in our pre-seeded instance so the mapper sees fixture data.
        # (Otherwise, the resolved plugin factory constructs a fresh empty one.)
        mem_bundle._factories["project"] = lambda: mem_store  # type: ignore[assignment]
        mem_mapper = DotProjectMapper(mem_root, project_store=mem_bundle.project)
        mem_context = mem_mapper.get_context()

        assert mem_context == fs_context, (
            "In-memory-backed mapper produced a different context than the "
            "filesystem-backed mapper for the same seeded ProjectConfig."
        )

    def test_on_disk_project_not_opened_when_in_memory_selected(self, tmp_path: Path):
        # Repo root has NO .project/ dir; the in-memory store carries the data.
        mem_store = _seed_in_memory()
        mem_bundle = resolve_stores(
            StoresConfig(project=StoreBlock(backend="in-memory")),
            repo_path=tmp_path,
        )
        mem_bundle._factories["project"] = lambda: mem_store  # type: ignore[assignment]

        mapper = DotProjectMapper(tmp_path, project_store=mem_bundle.project)
        # Spy on `open` in the reader module -- if the store path is
        # honored, the reader must never fall back to raw filesystem I/O.
        with patch("builtins.open") as mock_open:
            context = mapper.get_context()
            # Zero calls to `open` from the reader -- store answered.
            assert mock_open.call_count == 0
        assert context["project.name"] == "eq-fixture"
