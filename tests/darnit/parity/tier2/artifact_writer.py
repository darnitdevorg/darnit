"""Artifact bundle writer for Tier 2 (feature 028 T019).

Writes per-fixture artifacts under parity-artifacts/<fixture_name>/ for
inspection after a workflow run. Even on GREEN runs the bundle is written
so a maintainer can verify what the test saw. See data-model.md section 7.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


def write_fixture_artifacts(
    artifact_root: Path,
    fixture_name: str,
    mcp_json: str,
    skill_markdown: str,
    diff_md: str,
    metadata: dict[str, object] | None = None,
) -> Path:
    """Write the four per-fixture artifact files. Returns the fixture's
    artifact directory.
    """
    fixture_dir = artifact_root / fixture_name
    fixture_dir.mkdir(parents=True, exist_ok=True)

    (fixture_dir / "mcp_tool_result.json").write_text(mcp_json)
    (fixture_dir / "skill_final_message.md").write_text(skill_markdown)
    (fixture_dir / "diff_report.md").write_text(diff_md)

    meta_out: dict[str, object] = {
        "fixture_name": fixture_name,
        "timestamp_utc": datetime.now(UTC).isoformat(),
    }
    if metadata:
        meta_out.update(metadata)
    (fixture_dir / "metadata.json").write_text(
        json.dumps(meta_out, indent=2, default=str),
    )

    return fixture_dir


__all__ = ("write_fixture_artifacts",)
