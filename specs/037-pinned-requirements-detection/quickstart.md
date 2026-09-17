# Quickstart: Verifying Pinned-Requirements Detection

**Feature**: 037 | **Date**: 2026-09-17

## What changed, in one paragraph

`repro_deps_pinned` used to decide whether your dependencies were pinned by looking at filenames. Now, when there is no lock file, it opens your `requirements.txt` and reads it. A file pinned with hashes passes. A file pinned with `==` but no hashes warns, because your transitive dependencies still float. A file with open ranges fails and tells you which requirement is the problem.

## Before and after

Given a repo whose only dependency file is:

```text
numpy==1.26.4 --hash=sha256:2a02aba9ed12e4ac4eb3ea9421c420301a0c6460d9830d74a9df87efa4912010
click==8.1.7 --hash=sha256:ae74fb96c20a0277a1d615f1e4d73c8414f5a98db8b799a7931d1582f3390c28
```

| | Status | Message |
|---|---|---|
| Before | FAIL | Dependency manifests found but no lock files: requirements.txt (pip requirements) |
| After | PASS | every requirement is pinned with a hash |

## Running it

```bash
# Unit level -- classification and handler verdicts
uv run pytest tests/darnit_reproducibility/ -v

# Framework level -- the WARN outcome
uv run pytest tests/darnit/sieve/test_handler_warn_outcome.py -v

# Full gate, per constitution Development Workflow
uv run ruff check .
uv run pytest tests/ --ignore=tests/integration/ --ignore=tests/darnit/parity/tier2 -q
uv run python scripts/validate_sync.py --verbose
```

Note the test-ignore spelling: `--ignore=tests/darnit/parity/tier2`, not `--ignore=tests/darnit/parity`. The broader form skips parity tier 1, which CI runs, and hides failures until CI finds them.

## End-to-end against a real repo

```bash
uv run darnit audit --framework reproducibility /path/to/repo
```

This requires PR #439 (issues #427, #428). Without it, plugin sieve handlers are never registered outside the MCP server path, `repro_deps_pinned` does not execute at all, and `RE-01.01` falls through to `manual` and reports WARN regardless of what this feature does. A WARN observed before #439 merges says nothing about this feature.

## The three verdicts, by hand

```bash
cd "$(mktemp -d)" && git init -q .

printf 'numpy==1.26.4 --hash=sha256:%064d\n' 1 > requirements.txt   # PASS
printf 'numpy==1.26.4\n'                                            > requirements.txt   # WARN
printf 'numpy>=1.26\n'                                              > requirements.txt   # FAIL
```

Run the audit after each write. The WARN case is the one worth reading closely: it is not a failure of the tool to determine something. It is the tool determining that pinning direct dependencies does not make a build reproducible.

## What did not change

- A repo with a lock file: identical status, message, and confidence (SC-004).
- A repo with no dependency files: identical INCONCLUSIVE (SC-005).
- `setup.py`, `package.json`, `Cargo.toml`, `go.mod`: still judged by presence alone.
- `requirements-dev.txt`, `requirements/base.txt`: still not discovered (FR-019).
- Every other control, in every framework: unchanged (SC-008).

## Reviewing a verdict without re-running

The result evidence records the file inspected, the classification, and the requirements that drove it. For a FAIL, the offending lines are named; for a WARN, the lines lacking hashes. The enumerated examples are capped, with a total count alongside, so a repo with hundreds of unpinned requirements does not produce a result larger than the file it describes.
