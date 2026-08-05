# Implementation Plan: E2E Regression Baseline for `darnit run` (cmd_run)

**Branch**: `024-cmd-run-e2e-tests` | **Date**: 2026-08-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/024-cmd-run-e2e-tests/spec.md`

## Summary

Pin the observable behavior of `darnit run` (cmd_run at `packages/darnit/src/darnit/cli.py:631-728`) with an end-to-end test suite before RFC-0001 Stage 1 replaces the codepath with a Harness-driven implementation. Test-only feature per issue #359: add `tests/darnit/cli/test_cmd_run_e2e.py` covering the golden path, the deterministic-only guarantee (no LLM, no MCP, no network egress escaping stubs), and failure-path exit contracts. Fixtures live under `tests/darnit/cli/fixtures/`. No production code changes; no new runtime dependencies.

## Technical Context

**Language/Version**: Python 3.11 / 3.12 (workspace targets, unchanged)

**Primary Dependencies**: pytest (already declared), `unittest.mock` stdlib (already used across the suite). No new runtime dependencies; no new dev dependencies.

**Storage**: Filesystem only. Test fixtures are trees created under `tmp_path` or shipped as static files under `tests/darnit/cli/fixtures/`.

**Testing**: pytest, invoked via `uv run pytest tests/darnit/cli/test_cmd_run_e2e.py -v`. Discovered automatically by the existing `pyproject.toml` pytest config; no CI workflow changes.

**Target Platform**: Any host that runs the darnit dev workspace (Linux, macOS). Windows is not a workspace target. CI runs on GitHub-hosted Linux runners.

**Project Type**: Test package inside the darnit CLI's test tree. Adds a new package directory `tests/darnit/cli/` alongside the existing `tests/darnit/config/`, `tests/darnit/sieve/`, `tests/darnit/tools/`.

**Performance Goals**: New file adds <=30 s to the developer-laptop wall-clock time of `pytest tests/darnit/` (SC-005). No performance goals for the CLI itself; this is test coverage of existing behavior.

**Constraints**: No network access during test execution, no real LLM API key, no reliance on any external binary beyond what the fixture minimally requires. Deterministic under repeated runs; no flakes tolerated.

**Scale/Scope**: <=800 lines total (tests + fixtures) per SC-006. One new test file, one fixture tree, one conftest hook if needed. Approximately 8-12 test cases across the three user stories.

## Constitution Check

Constitution version: 1.3.0. Five Core Principles evaluated as gates.

| Principle | Applicable? | Verdict | Rationale |
|-----------|-------------|---------|-----------|
| I. Plugin Separation (framework MUST NOT import implementations) | Yes | PASS | The tests exercise the framework CLI through its public surface (`argparse` -> `cmd_run`), which itself already goes through the plugin-discovery contract. Test files live under `tests/darnit/cli/` (framework tree) and may import from `darnit_baseline` only for fixture-setup convenience if a real installed plugin is required for the golden path -- if so, the import goes in test code (which is not framework production code) and is called out explicitly in the test docstring. Preferred alternative: use `darnit-testchecks` (the test-only implementation package that already exists specifically for this) to avoid a dependency on `darnit-baseline` from framework tests. Decision pushed to Phase 0 research. |
| II. Conservative-by-Default | Yes | PASS | The tests pin conservative behavior: exit-code contract, no silent PASS. Any harness-driver change that loosens verdicts fails the pinning tests. This feature strengthens the principle by locking down current conservative outputs. |
| III. TOML-First Architecture | Yes | PASS (N/A in substance) | No control definitions change. If a fixture ships a minimal TOML for a made-up framework, that TOML lives under `tests/darnit/cli/fixtures/`, is not shipped to users, and does not affect the schema. |
| IV. Never Guess User Values | Yes | PASS | Tests do not fill in user-judgment values. The `noninteractive` feedback handler returns `None` for every prompt, per the current contract; the test suite pins this behavior. If the harness driver introduces automatic answering under noninteractive mode, that is a violation of principle IV and the test suite will fail (correctly). |
| V. Sieve Pipeline Integrity | Yes | PASS | Tests exercise the pipeline end-to-end without stubbing sieve internals. Only external subprocess calls (`gh`, `git` beyond fixture setup) and LLM/MCP entry points are stubbed; the sieve orchestrator, handler registry, and pass mechanics run unpatched. |

No violations. No entries required in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/024-cmd-run-e2e-tests/
├── spec.md                            # /speckit-specify output
├── plan.md                            # this file (/speckit-plan output)
├── research.md                        # Phase 0: fixture strategy + stubbing points
├── data-model.md                      # Phase 1: minimal -- describes fixture entities
├── quickstart.md                      # Phase 1: how a maintainer runs / extends these tests
├── contracts/
│   └── cmd_run-output.md              # observable output contract pinned by the tests
├── checklists/
│   └── requirements.md                # spec-quality checklist (already exists)
└── tasks.md                           # /speckit-tasks output (NOT created here)
```

### Source Code (repository root)

Test-only addition. Only paths under `tests/darnit/cli/` are created. No production source changes.

```text
tests/darnit/
├── agent/                             # existing
├── cli/                               # NEW package directory
│   ├── __init__.py                    # NEW (empty, makes cli/ a package)
│   ├── conftest.py                    # NEW (fixtures, monkeypatch helpers)
│   ├── test_cmd_run_e2e.py            # NEW (the E2E tests)
│   └── fixtures/                      # NEW
│       └── minimal_repo/              # NEW (single-check-satisfies fixture tree)
│           ├── .baseline.toml         # picks a framework (probably darnit-testchecks)
│           ├── .project/
│           │   └── project.yaml
│           ├── README.md
│           └── (any files needed to make one check PASS)
├── config/                            # existing
├── context/                           # existing
├── core/                              # existing
├── sieve/                             # existing
├── tools/                             # existing
└── test_cli.py                        # existing -- unit-level, argparse wiring only
```

**Structure Decision**: New sibling package `tests/darnit/cli/` because:
- Existing `tests/darnit/test_cli.py` is unit-scoped (argparse parsing, formatter helpers). Mixing E2E command tests into it would blur intent and inflate its runtime; the sibling package keeps E2E in a dedicated tree that can be run in isolation (`pytest tests/darnit/cli/`).
- The sibling-package convention already exists in this repo (`tests/darnit/config/`, `tests/darnit/sieve/`, etc.), so no new pattern is introduced.
- Fixtures under `tests/darnit/cli/fixtures/` scope naming and cleanup to this feature; nothing pollutes other test trees.

## Complexity Tracking

Not applicable. Constitution Check passed with no violations.
