#!/usr/bin/env python3
"""Record the corpus's tool calls from the real tools (framework-design.md section 5.5).

A fixture whose labels declare ``[fixture.tools.<tool>] recorded = true``
replays ``<fixture>/recorded/<tool>.json`` in every corpus run, so the run
needs no installed tool and is deterministic. This script writes those
files: it runs the openssf-baseline corpus with the real tool, once with the
shipped framework and once per superseded command in
``tests/darnit_baseline/corpus/runner.py`` (``SUPERSEDED_COMMANDS``), and
records every call the steps made. The audited copy's path is written as
``$REPO_PATH``.

Re-record after changing a recorded tool's command in the framework TOML,
after changing a fixture that declares a recorded tool, or when moving to a
new tool version; then run the corpus tests and review the diff.

Usage:
    uv run python scripts/record_corpus_tools.py --tool zizmor=$(command -v zizmor) [--fixture NAME ...]
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.darnit_baseline.corpus.runner import (  # noqa: E402
    SUPERSEDED_COMMANDS,
    load_fixtures,
    load_framework,
    run_fixture,
    with_tool_command,
)

FRAMEWORK = "openssf-baseline"


def _version(executable: str) -> str:
    run = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=30, check=True)
    return run.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tool", action="append", required=True, metavar="NAME=EXECUTABLE")
    parser.add_argument("--fixture", action="append", default=[], metavar="NAME", help="only these fixtures")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.ERROR)

    tools = dict(spec.split("=", 1) for spec in args.tool)
    for name, executable in tools.items():
        if not Path(executable).is_absolute() or not Path(executable).is_file():
            parser.error(f"--tool {name}: {executable!r} is not an absolute path to an executable")
    versions = {name: _version(executable) for name, executable in tools.items()}

    framework = load_framework(FRAMEWORK)
    written = 0
    for fixture in load_fixtures():
        if args.fixture and fixture.name not in args.fixture:
            continue
        for tool in fixture.recorded_tools():
            if tool not in tools:
                print(f"skip {fixture.name}: no --tool {tool}=...", file=sys.stderr)
                continue
            frameworks = [framework] + [
                with_tool_command(framework, tool, command) for command in SUPERSEDED_COMMANDS.get(tool, [])
            ]
            calls: list[dict[str, object]] = []
            for each in frameworks:
                run = run_fixture(fixture, each, record={tool: tools[tool]})
                for call in run.recorded_calls[tool]:
                    if all(call["args"] != seen["args"] for seen in calls):
                        calls.append(call)
            if not calls:
                print(f"warning: {fixture.name}: no step called {tool}", file=sys.stderr)
            recording = {
                "tool": tool,
                "version": versions[tool],
                "regenerate": f"uv run python scripts/record_corpus_tools.py --tool {tool}=PATH --fixture {fixture.name}",
                "calls": calls,
            }
            path = fixture.recording_path(tool)
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(recording, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
            print(f"wrote {path.relative_to(PROJECT_ROOT)} ({len(calls)} calls)")
            written += 1
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
