# Quickstart: Verifying Cobra Threat-Model Coverage End-to-End

**Feature**: 014-cobra-threat-model

This is the runbook for a maintainer to confirm the cobra threat-model coverage is doing what the spec says. Run this once after implementation lands; run again whenever the heuristic table or grouping algorithm changes.

## Prerequisites

- Local clone of `kusari-oss/darnit` on the `014-cobra-threat-model` branch.
- `uv sync --all-extras` complete.
- A scratch directory where you can clone reference targets.

## Step 1 — Run against the synthetic minimal fixture

```bash
cd /Users/mlieberman/Projects/darnit
uv run pytest tests/darnit_baseline/threat_model/test_ts_discovery.py -k cobra -v
```

Expected:
- Tests under `test_*_cobra_*` pass.
- The `cobra_minimal` fixture yields exactly 1 family, with Tampering as the fallback category.
- The `cobra_subcommand` fixture yields 1 family with multiple `members`.
- The `cobra_mixed_http` fixture yields one CLI family AND at least one HTTP route.
- The `go_no_cobra` fixture yields zero CLI findings (FR-009 regression test).

## Step 2 — Run against gittuf (the real-world reference)

```bash
cd /tmp
[ -d gittuf ] || git clone --depth=1 https://github.com/gittuf/gittuf.git
cd /Users/mlieberman/Projects/darnit
uv run python -c "
from darnit.sieve.handler_registry import HandlerContext
from darnit_baseline.threat_model.remediation import generate_threat_model_handler
ctx = HandlerContext(local_path='/tmp/gittuf', owner='gittuf', repo='gittuf')
result = generate_threat_model_handler(
    {'path': 'docs/threatmodel/SUMMARY.md', 'overwrite': True},
    ctx,
)
print('STATUS:', result.status)
print('MSG:', result.message)
"
```

Expected:
- Status: `PASS`.
- Message includes a non-zero `group_count`.
- `/tmp/gittuf/docs/threatmodel/SUMMARY.md` exists, is non-empty, and contains a `### CLI Entry Points` subsection.

## Step 3 — Eyeball the output

Open `/tmp/gittuf/docs/threatmodel/SUMMARY.md`.

Checks:

1. **Section ordering** — `## Entry Points` appears between `## Unmitigated Findings` and `## Companion Artefacts` (per the output contract).
2. **CLI subsection present, HTTP subsection absent** — gittuf has no HTTP routes, so only `### CLI Entry Points` should render. There should be no empty placeholder.
3. **Family count** — between 5 and 15 family headings under CLI Entry Points (SC-002). For gittuf at current `main`, expect roughly the count of top-level directories under `internal/cmd/`.
4. **Family names match gittuf's CLI vocabulary** — open a terminal and run `cd /tmp/gittuf && go run main.go --help` (or read `internal/cmd/root/root.go`); the family display names in the document should match the top-level commands listed there (e.g., `cache`, `attest`, `rsl`, `verify`).
5. **Per-family fields populated** — each family has Source root, Subcommands count + list, STRIDE categories, Confidence line ("heuristic — needs reviewer attention"), and a subcommand table.
6. **STRIDE plausibility (SC-006)** — pick three families and ask: does the assigned category match what that command actually does? Tampering for `cache populate` is fine. Repudiation for `attest *` is fine. Spoofing+Information Disclosure for an HTTP-touching command would be fine but gittuf has none. Note any miscategorisations and decide whether the heuristic table needs adjustment.
7. **Limitations section** — should mention how many of the 267 Go files imported cobra and whether any cobra-importing files matched no query. Honest count.
8. **Verification-prompt block** — present, including the CLI-specific paragraph.

## Step 4 — Confirm no regression on the existing path

```bash
cd /Users/mlieberman/Projects/darnit
uv run pytest tests/darnit_baseline/threat_model/ -q
```

Expected: all pre-existing tests pass. Zero regressions on HTTP / Python / MCP discovery (SC-004).

## Step 5 — Snapshot regeneration (only if heuristics changed)

If you intentionally adjusted the STRIDE heuristic table or the grouping algorithm, snapshot tests for the synthetic fixtures may fail. Regenerate:

```bash
uv run pytest tests/darnit_baseline/threat_model/test_ts_generators.py -k cobra --snapshot-update
git diff tests/darnit_baseline/threat_model/__snapshots__/  # review carefully
```

Commit the snapshot delta in the same PR as the heuristic change, with a commit message that explains *why* the snapshot moved. Do not bulk-regenerate snapshots without reviewing — a snapshot drift you didn't expect is a regression signal.

## Step 6 — Optional: Demo dry-run

For the conference demo, time the end-to-end flow:

```bash
time (cd /tmp/gittuf && rm -rf docs/threatmodel)
time uv run python -c "..."  # the same call from Step 2
```

Expected: total wall-clock under 60s on a modern laptop (SC-007). The actual threat-model generation typically completes in 3–8s; the remaining budget is for the audience to read the output on stage.

If timing exceeds 60s, the most likely culprit is opengrep running large semgrep rulesets. Disable opengrep for the demo by running without it on `PATH`; the structural-only output is still presentation-quality.

## Troubleshooting

- **CLI Entry Points section is empty** — likely the cobra-detection trigger didn't fire. Verify the file actually imports `github.com/spf13/cobra` and that the import is collected by `_collect_go_imports`. If the import is there but the section is still empty, suspect the query patterns — re-check `queries/go.py`.
- **Family names look wrong** (e.g., "init" appearing as a top-level family instead of nested under "cache") — common-prefix inference may be miscomputing the command root. Print the inferred root from a debug invocation and compare to the project's actual layout.
- **All families default to Tampering** — the heuristic table didn't match any of their imports. Either the table needs another rule for that project's idioms, or the file genuinely doesn't import anything category-relevant and Tampering is the correct fallback.
- **SC-002 family count outside 5–15 for gittuf** — fewer than 5: command-root inference probably went too deep. More than 15: too shallow, treating every leaf directory as its own family.
