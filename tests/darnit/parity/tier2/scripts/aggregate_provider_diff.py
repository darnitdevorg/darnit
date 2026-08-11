"""Aggregate cross-provider drift script (feature 029 T022, US3).

Reads Tier 2 artifact bundles for BOTH the Claude and OpenAI backends and
produces a Markdown table per fixture showing where the two providers'
final assistant messages agree or disagree on per-control status.

This is a LOCAL MAINTAINER script -- NOT invoked by any pytest module and
NOT run by CI. Its inputs are workflow-run artifact bundles downloaded via
`gh run download`. Example workflow:

    # 1. Dispatch Claude tier 2 workflow, download its artifacts:
    gh run download --repo darnitdevorg/darnit <claude-run-id>
    mv parity-artifacts parity-artifacts-claude

    # 2. Dispatch OpenAI tier 2 workflow, download its artifacts:
    gh run download --repo darnitdevorg/darnit <openai-run-id>
    mv parity-artifacts parity-artifacts-openai

    # 3. Diff the two bundles:
    uv run python -m tests.darnit.parity.tier2.scripts.aggregate_provider_diff \\
        --claude-artifacts parity-artifacts-claude \\
        --openai-artifacts parity-artifacts-openai

Alternate single-directory mode (if the two providers wrote to the same
fixture dir on separate dispatches, per feature 029's provider-filename
convention):

    uv run python -m tests.darnit.parity.tier2.scripts.aggregate_provider_diff \\
        --artifacts parity-artifacts

Output goes to stdout as one Markdown table per fixture.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tests.darnit.parity.tier2.skill_markdown_parser import SkillReport


def _read_message(path: Path) -> str | None:
    """Read a final-message file if it exists; return None otherwise."""
    if not path.exists() or not path.is_file():
        return None
    return path.read_text()


def _discover_fixtures(*roots: Path) -> list[str]:
    """Every subdirectory of any root that has at least one final-message
    file counts as a fixture."""
    names: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for child in root.iterdir():
            if not child.is_dir():
                continue
            for candidate in (
                "skill_final_message.md",
                "claude_final_message.md",
                "openai_final_message.md",
            ):
                if (child / candidate).exists():
                    names.add(child.name)
                    break
    return sorted(names)


def _find_message(
    fixture_name: str,
    provider: str,
    roots: list[Path],
) -> str | None:
    """Locate the final-message artifact for `provider` under any of the
    given artifact roots."""
    candidates: list[str] = []
    if provider == "claude":
        candidates = ["skill_final_message.md", "claude_final_message.md"]
    elif provider == "openai":
        candidates = ["openai_final_message.md"]
    else:
        candidates = [f"{provider}_final_message.md"]

    for root in roots:
        fixture_dir = root / fixture_name
        for candidate in candidates:
            content = _read_message(fixture_dir / candidate)
            if content is not None:
                return content
    return None


def _diff_one_fixture(
    fixture_name: str,
    claude_message: str | None,
    openai_message: str | None,
) -> str:
    """Produce a Markdown section (heading + table) for one fixture."""
    lines: list[str] = [f"## Fixture: {fixture_name}"]

    if claude_message is None and openai_message is None:
        lines.append("")
        lines.append("No final-message artifacts found for either provider.")
        lines.append("")
        return "\n".join(lines)

    if claude_message is None:
        lines.append("")
        lines.append("Claude final message NOT found; only OpenAI to report.")
    if openai_message is None:
        lines.append("")
        lines.append("OpenAI final message NOT found; only Claude to report.")

    claude_report = SkillReport.parse(claude_message) if claude_message else None
    openai_report = SkillReport.parse(openai_message) if openai_message else None

    claude_by_id: dict[str, str] = {}
    openai_by_id: dict[str, str] = {}
    if claude_report and claude_report.controls:
        claude_by_id = {c.id: c.status for c in claude_report.controls}
    if openai_report and openai_report.controls:
        openai_by_id = {c.id: c.status for c in openai_report.controls}

    control_ids = sorted(set(claude_by_id) | set(openai_by_id))
    if not control_ids:
        lines.append("")
        lines.append("Neither provider's message was parseable at the per-control level.")
        lines.append("")
        return "\n".join(lines)

    lines.append("")
    lines.append("| control_id | claude_status | openai_status | disagreement |")
    lines.append("| --- | --- | --- | --- |")

    disagreements = 0
    for cid in control_ids:
        claude_s = claude_by_id.get(cid, "-")
        openai_s = openai_by_id.get(cid, "-")
        disagrees = claude_s != openai_s and claude_s != "-" and openai_s != "-"
        marker = "YES" if disagrees else ""
        if disagrees:
            disagreements += 1
        lines.append(f"| {cid} | {claude_s} | {openai_s} | {marker} |")

    lines.append("")
    lines.append(
        f"Summary: {len(control_ids)} controls compared, {disagreements} disagreements.",
    )
    lines.append("")
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Cross-provider Tier 2 drift diff",
    )
    parser.add_argument(
        "--claude-artifacts",
        type=Path,
        help="Directory containing Claude Tier 2 artifact bundle (e.g. from `gh run download`)",
    )
    parser.add_argument(
        "--openai-artifacts",
        type=Path,
        help="Directory containing OpenAI Tier 2 artifact bundle",
    )
    parser.add_argument(
        "--artifacts",
        type=Path,
        help="Single artifact root containing both providers' messages "
        "(alternate mode; overrides --claude-artifacts and "
        "--openai-artifacts if both provided).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    roots: list[Path] = []
    if args.artifacts:
        roots.append(args.artifacts)
    if args.claude_artifacts:
        roots.append(args.claude_artifacts)
    if args.openai_artifacts:
        roots.append(args.openai_artifacts)

    if not roots:
        print(
            "Provide at least one of --artifacts, --claude-artifacts, --openai-artifacts",
            file=sys.stderr,
        )
        return 2

    fixture_names = _discover_fixtures(*roots)
    if not fixture_names:
        print("No fixtures with final-message artifacts found.", file=sys.stderr)
        return 1

    print("# Cross-provider Tier 2 drift diff")
    print()
    print(f"Fixtures analyzed: {len(fixture_names)}")
    print(f"Roots: {[str(r) for r in roots]}")
    print()

    total_disagreements = 0
    for name in fixture_names:
        claude_message = _find_message(name, "claude", roots)
        openai_message = _find_message(name, "openai", roots)
        section = _diff_one_fixture(name, claude_message, openai_message)
        print(section)
        if "disagreements" in section:
            # Grep the summary line for the count.
            for line in section.splitlines():
                if line.startswith("Summary:") and "disagreements." in line:
                    parts = line.split(",")
                    if len(parts) >= 2:
                        try:
                            total_disagreements += int(
                                parts[1].strip().split()[0],
                            )
                        except (IndexError, ValueError):
                            pass

    print("---")
    print(f"**Total disagreements across all fixtures: {total_disagreements}**")

    return 0


if __name__ == "__main__":
    sys.exit(main())
