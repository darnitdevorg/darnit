"""The MCP tool surface an agent sees is recorded for each shipped framework.

Each framework's tools (name, description, input and output schema), as
``darnit serve --framework <name>`` lists them, are kept in
``tests/darnit/server/tool_surface/<framework>.json``. A change to any of them
fails this test until the file is updated, so what an agent will see differently
shows in the change's diff. To update the files after an intended change:

    DARNIT_UPDATE_TOOL_SURFACE=1 uv run pytest tests/darnit/server/test_tool_surface.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from darnit.config.merger import resolve_framework_path
from darnit.server.factory import create_server

SURFACE = Path(__file__).parent / "tool_surface"
FRAMEWORKS = ["openssf-baseline", "gittuf", "reproducibility"]


def _surface(framework: str) -> list[dict]:
    path = resolve_framework_path(framework)
    assert path is not None, f"framework {framework!r} is not registered"
    tools = asyncio.run(create_server(path).list_tools())
    return sorted((t.model_dump(mode="json", exclude_none=True) for t in tools), key=lambda t: t["name"])


def _changes(recorded: list[dict], measured: list[dict]) -> list[str]:
    rec = {t["name"]: t for t in recorded}
    now = {t["name"]: t for t in measured}
    out = [f"added: {n}" for n in sorted(set(now) - set(rec))]
    out += [f"removed: {n}" for n in sorted(set(rec) - set(now))]
    for name in sorted(set(rec) & set(now)):
        fields = sorted(k for k in set(rec[name]) | set(now[name]) if rec[name].get(k) != now[name].get(k))
        if fields:
            out.append(f"changed: {name} ({', '.join(fields)})")
    return out


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_tool_surface_matches_record(framework: str) -> None:
    measured = _surface(framework)
    text = json.dumps(measured, indent=2, sort_keys=True) + "\n"
    path = SURFACE / f"{framework}.json"
    if os.environ.get("DARNIT_UPDATE_TOOL_SURFACE") == "1":
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return
    assert path.is_file(), f"no recorded tool surface for {framework}; run with DARNIT_UPDATE_TOOL_SURFACE=1"
    recorded_text = path.read_text(encoding="utf-8")
    if recorded_text != text:
        changes = _changes(json.loads(recorded_text), measured) or ["formatting only"]
        pytest.fail(
            f"The MCP tool surface of {framework} differs from {path.name}:\n  "
            + "\n  ".join(changes)
            + "\nIf intended, run with DARNIT_UPDATE_TOOL_SURFACE=1 and commit the file with the change."
        )
