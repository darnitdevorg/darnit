#!/usr/bin/env python3
"""Adversarial corpus report (feature 041, framework-design.md section 5.5).

Runs a framework's controls against the fixture corpus in
tests/darnit_baseline/corpus/ (offline, deterministic) and reports, per step
and outcome, the correct and incorrect conclusions against the labels, the
false PASS results, and which steps are eligible for a PASS promotion.

Exit Codes:
    0 = No false PASS beyond the known list, and no stale known entries
    1 = A step allowed to conclude PASS produced an unlisted false PASS, or
        a known entry no longer occurs

Usage:
    uv run python scripts/corpus_report.py [--format markdown|json] [--output PATH]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.darnit_baseline.corpus.runner import (  # noqa: E402
    CorpusReport,
    KnownFalsePass,
    Violation,
    gate,
    load_framework,
    load_known_false_pass,
    run_corpus,
)


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|")


def _table(headers: list[str], rows: list[list[object]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines.extend("| " + " | ".join(_cell(v) for v in row) + " |" for row in rows)
    return lines


def _step(step_index: int | None, handler: str) -> str:
    return "inferred_from" if step_index is None else f"pass[{step_index}] {handler}"


def render_markdown(report: CorpusReport, unexpected: list[Violation], stale: list[KnownFalsePass]) -> str:
    labels: dict[str, int] = {}
    for meta in report.fixtures.values():
        for expected, count in meta["labels"].items():
            labels[expected] = labels.get(expected, 0) + count
    verdicts: dict[str, int] = {}
    for control in report.controls:
        verdicts[control.verdict] = verdicts.get(control.verdict, 0) + 1
    known = [v for v in report.violations if v not in unexpected]

    out = [
        "# Adversarial corpus report",
        "",
        f"- Corpus version: `{report.corpus_version}`",
        f"- Frameworks: {', '.join(report.frameworks)}",
        f"- Fixtures: {len(report.fixtures)}; labels: {sum(labels.values())} ("
        + ", ".join(f"{k} {v}" for k, v in sorted(labels.items()))
        + ")",
        f"- Steps measured: {sum(s.measured for s in report.steps)} of {len(report.steps)} declared",
        "",
        "## Gate",
        "",
        f"- False PASS by a step allowed to conclude PASS: {len(report.violations)} "
        f"({len(known)} known, {len(unexpected)} unexpected)",
        f"- Stale known entries: {len(stale)}",
        f"- Result: {'FAIL' if unexpected or stale else 'PASS'}",
        "",
    ]
    if report.violations:
        out += _table(
            ["Fixture", "Control", "Step", "Expected", "Known"],
            [
                [
                    v.fixture,
                    v.control_id,
                    _step(v.step_index, v.handler),
                    v.expected,
                    "no" if v in unexpected else "yes",
                ]
                for v in report.violations
            ],
        )
        out.append("")
    if stale:
        out += _table(
            ["Fixture", "Control", "Step", "Task"],
            [[k.fixture, k.control_id, _step(k.step_index, k.handler), k.task] for k in stale],
        )
        out.append("")

    out += [
        "## Control results against labels",
        "",
        "`undetermined` means no step concluded (WARN with nothing concluded, PENDING, or ERROR).",
        "",
    ]
    out += _table(["Verdict", "Controls"], [[k, v] for k, v in sorted(verdicts.items())])
    out += ["", "## Steps by outcome", ""]
    out += _table(
        [
            "Control",
            "Step",
            "May conclude PASS",
            "Outcome",
            "Observed",
            "Concluded",
            "Correct",
            "Incorrect",
            "False PASS",
        ],
        [
            [
                r.control_id,
                _step(r.step_index, r.handler),
                "yes" if r.may_conclude_pass else "no",
                r.outcome,
                r.observed,
                r.concluded,
                r.correct,
                r.incorrect,
                r.false_pass,
            ]
            for r in report.rows
        ],
    )
    eligible = [s for s in report.steps if s.eligible_for_promotion]
    out += [
        "",
        "## Eligible for a PASS promotion",
        "",
        "Steps that may not yet conclude PASS, produced at least one correct PASS, and no false PASS.",
        "Eligibility is necessary, not sufficient: it is only as strong as the fixtures that exercise the step.",
        "",
    ]
    out += _table(
        ["Control", "Step", "Correct PASS"],
        [[s.control_id, _step(s.step_index, s.handler), s.true_pass] for s in eligible],
    )
    out += ["", "## Per-fixture results", ""]
    out += _table(
        ["Fixture", "Control", "Expected", "Result", "Concluded by", "Verdict"],
        [
            [
                c.fixture,
                c.control_id,
                c.expected,
                c.status,
                "none" if c.concluded_by in (None, "none") else _step(c.step_index, c.concluded_by),
                c.verdict,
            ]
            for c in report.controls
        ],
    )
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path, help="write the report here instead of stdout")
    parser.add_argument("--framework", default="openssf-baseline")
    args = parser.parse_args()

    logging.basicConfig(level=logging.ERROR)
    report = run_corpus(load_framework(args.framework))
    unexpected, stale = gate(report, load_known_false_pass())

    if args.format == "json":
        data = report.to_dict()
        data["gate"] = {
            "unexpected": [v.describe() for v in unexpected],
            "stale": [f"{k.framework} {k.control_id} {_step(k.step_index, k.handler)} on '{k.fixture}'" for k in stale],
            "passed": not unexpected and not stale,
        }
        text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    else:
        text = render_markdown(report, unexpected, stale)

    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)

    for violation in unexpected:
        print(f"false PASS: {violation.describe()}", file=sys.stderr)
    for entry in stale:
        print(
            f"stale known entry: {entry.control_id} {_step(entry.step_index, entry.handler)} on '{entry.fixture}'",
            file=sys.stderr,
        )
    return 1 if unexpected or stale else 0


if __name__ == "__main__":
    sys.exit(main())
