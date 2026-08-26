"""Backward-compat lock for pre-feature entry points.

Feature 033 T031. Guards the two seams most callers touch:

* ``DotProjectReader(repo_path)`` -- the pre-feature call shape without
  a ``store`` argument -- must continue to read on-disk YAML and
  produce the same ``ProjectConfig``.
* ``generate_attestation_from_results(..., output_path=...)`` -- the
  legacy filesystem write path -- must continue to work when no
  ``attestation_store`` is passed.

If either of these regresses, existing consumers break silently. This
test is the lock.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_YAML = """
name: bc-fixture
description: Feature 033 T031 backward-compat lock
repositories:
  - https://github.com/example/bc-fixture
"""


class TestDotProjectReaderBackwardCompat:
    def test_pre_feature_call_shape_still_works(self, tmp_path: Path):
        """`DotProjectReader(repo_path)` -- no store kwarg -- reads on-disk YAML."""
        from darnit.context.dot_project import DotProjectReader

        (tmp_path / ".project").mkdir()
        (tmp_path / ".project" / "project.yaml").write_text(
            PROJECT_YAML.strip() + "\n"
        )

        reader = DotProjectReader(tmp_path)  # NO store argument
        config = reader.read()
        assert config.name == "bc-fixture"
        assert config.repositories == ["https://github.com/example/bc-fixture"]

    def test_pre_feature_call_shape_returns_empty_when_missing(self, tmp_path: Path):
        from darnit.context.dot_project import DotProjectReader, ProjectConfig

        reader = DotProjectReader(tmp_path)  # NO .project/ directory
        config = reader.read()
        # Pre-feature behavior: empty ProjectConfig, not an exception.
        assert isinstance(config, ProjectConfig)
        assert config.name == ""


class TestAttestationGeneratorBackwardCompat:
    def test_no_store_kwarg_uses_filesystem_path(self, tmp_path: Path):
        """Legacy filesystem write path: `output_path=...`, no store."""
        from unittest.mock import MagicMock

        from darnit_baseline.attestation.generator import (
            generate_attestation_from_results,
        )

        # Build a minimal AuditResult double.
        audit_result = MagicMock()
        audit_result.commit = "abc123"
        audit_result.owner = "owner"
        audit_result.repo = "repo"
        audit_result.ref = "main"
        audit_result.level = 1
        audit_result.all_results = []
        audit_result.project_config = None
        audit_result.local_path = str(tmp_path)

        out = tmp_path / "att.intoto.json"
        result = generate_attestation_from_results(
            audit_result=audit_result,
            sign=False,
            output_path=str(out),
        )
        # Legacy behavior: file written on disk; result is the unsigned
        # statement JSON.
        assert out.exists()
        assert '"predicateType"' in result
