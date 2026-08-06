# Implementation Plan: `darnit-harness` -- End-to-End Audit Driver

**Branch**: `026-darnit-harness` | **Date**: 2026-08-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/026-darnit-harness/spec.md` (with 3 clarifications from `/speckit-clarify` on 2026-08-05: pluggable answer sources via Protocol with `.project/project.yaml` auto-discovery + `--answers` override; stdlib-logging-style progress lines to stderr with `[N/M]` counters; `darnit harness <path>` as a new subcommand of the existing `darnit` CLI, no separate binary/package).

## Summary

Adds `darnit harness <repo-path>` -- a new subcommand on the existing `darnit` CLI that runs a full audit end-to-end, dispatching LLM steps in-band using a user-supplied API key. Closes the loop feature 025 opened: same core code as MCP, but a non-interactive driver a fleet operator can invoke from CI.

Composes four existing primitives with two new pieces:
- **Uses:** `run_sieve_audit(stop_on_llm=True)` for the initial gather + `SieveOrchestrator.verify_with_llm_response` for each PENDING_LLM continuation (two-pass, per research.md R1), feature 025's `LLMStep` Protocol + `PydanticAILLMStep`, feature 018's `save_context_values` for confirmation persistence (wired but not called in MVP; see R4).
- **Adds:** an `AnswerSource` Protocol (pluggable; MVP file adapters only), a new `cmd_harness` entry point, and a small report generator.

Non-interactive by default; batch answers via `.project/project.yaml` auto-discovery + `--answers <path>` override. Reports to stdout in Markdown (default) or JSON; `--output <path>` writes to a file. Progress + summary to stderr; four-class exit-code contract per FR-008. Anthropic-only for MVP (matches feature 025's `PydanticAILLMStep` default); OpenAI etc. plug in via the same seam later.

## Technical Context

**Language/Version**: Python 3.11 / 3.12 (workspace targets, unchanged).

**Primary Dependencies (new)**: None. Feature 025 already added `pydantic-ai-slim[anthropic]` as a required runtime dep; this feature consumes it. No new packages.

**Primary Dependencies (in use)**: `pydantic-ai-slim[anthropic]` (from feature 025), `pydantic >= 2.0`, `pyyaml`, `mcp>=1.23,<2`, `cel-python`. Existing darnit-core internals: `SieveOrchestrator`, `run_sieve_audit`, `save_context_values`, `LLMStep`, `HarnessState`, `next_action`, `submit_result`.

**Storage**: Filesystem only (unchanged). Reads `.project/project.yaml` (feature 018 shape) and optional `--answers <path>` YAML/JSON at startup. Writes report to stdout or `--output <path>`. No new persistent state.

**Testing**: pytest; `MockLLMStep` (from feature 025) for LLM-dispatch tests so no live API calls are needed in CI.

**Target Platform**: Any host that runs darnit (Linux, macOS). Ships in `darnit-core`; no new platform requirements.

**Project Type**: Subcommand addition on the existing `darnit` CLI (Q3). Ships in `packages/darnit/src/darnit/`.

**Performance Goals**: SC-003 says <=30s on the deterministic-only feature-024 fixture; SC-004 same for an LLM-required fixture under `MockLLMStep`. Real-world audits with live LLM calls are bounded by FR-014's 15-minute total-run ceiling.

**Constraints**: No hangs (FR-014: per-LLM-call, per-subprocess, and total-run bounds). No interactive prompting in default mode (FR-006). No handlers with side effects during Check/Collect (FR-010; consistent with Constitution V + Stage 1). API key never written to disk or logged (research.md R7).

**Scale/Scope**: MVP is single-repo audit. Multi-repo iteration and org-level dedup queue are Stage 3 territory (out of scope). Expected slice size: ~500-800 lines net production + ~500 lines tests.

## Constitution Check

Constitution v1.3.0. Five Core Principles evaluated as gates.

| Principle | Applicable? | Verdict | Rationale |
|-----------|-------------|---------|-----------|
| I. Plugin Separation | Yes | PASS | Harness lives in `darnit-core` (`packages/darnit/src/darnit/`). Consumes framework configs and handlers through the existing plugin discovery path (`load_framework_by_name`); the harness does NOT import any implementation package. Reports use core-side formatters or a new harness-side formatter; `darnit-baseline` is not imported. |
| II. Conservative-by-Default | Yes | PASS + REINFORCED | The harness's LLM dispatch is subject to feature 025's authority rule -- suggestive LLM output attaches evidence but cannot conclude a control. SC-008 asserts this holds even under the new dispatch path. Missing credentials cause fail-fast (FR-002); the harness cannot silently degrade to a partial "deterministic-only" report labeled complete. |
| III. TOML-First Architecture | Yes | PASS (N/A in substance) | The harness reads controls from the same TOML the existing sieve reads. No new TOML schema fields. Answer-source files (both auto-discovered `.project/project.yaml` and `--answers` YAML) are user data, not control config. |
| IV. Never Guess User Values | Yes | PASS | Values from any `AnswerSource` adapter resolve as `asserted` authority (a human wrote them into the source the operator explicitly controls). No `AnswerSource` adapter proposes values from heuristics; that would need to be a `suggestive` step in a control, not an answer-source. Edge case in spec ("declared answer for an `auto_detect = false` key is accepted") is honest per Principle IV as amended in constitution 1.3.0 (the operator's config is an explicit human assertion). |
| V. Sieve Pipeline Integrity | Yes | PASS + EXTENDED | The harness invokes `run_sieve_audit(stop_on_llm=True)` -- the same semantics `darnit audit` and the MCP tools use -- and then dispatches each PENDING_LLM result through `LLMStep.evaluate()`, feeding the response back into `SieveOrchestrator.verify_with_llm_response` to obtain a final result. The sieve is not modified; the harness is a second consumer of the same seam MCP uses (per research.md R1). The authority-keyed rule from Stage 1 still enforces "LLM cannot conclude" regardless. |

**No violations.** No Complexity Tracking entries required.

Two positive observations:
- The pluggable `AnswerSource` Protocol (FR-005a) sets up the RFC's "Fleet mode and the manual queue" (Stage 3) work as an incremental addition rather than a rewrite. Adapters like `GitHubIssueAnswerSource` or `EmailAnswerSource` plug into the same seam without harness-core changes.
- Ship footprint is small (one new subcommand, one new Protocol, one report generator, tests). Stage-1's substrate did the heavy lifting; this feature is the wiring that makes it usable.

## Project Structure

### Documentation (this feature)

```text
specs/026-darnit-harness/
+-- spec.md                        # /speckit-specify + /speckit-clarify output
+-- plan.md                        # this file
+-- research.md                    # Phase 0: architectural decisions
+-- data-model.md                  # Phase 1: AnswerSource Protocol, HarnessRun, HarnessReport
+-- quickstart.md                  # Phase 1: how to run + verify locally
+-- contracts/
|   +-- cli.md                     # `darnit harness` argv + exit-code + stderr contract
|   +-- answer-source-protocol.md  # AnswerSource Protocol shape
|   +-- report-format.md           # Markdown + JSON report structures
+-- checklists/
|   +-- requirements.md            # spec-quality checklist (exists)
+-- tasks.md                       # /speckit-tasks output (later)
```

### Source Code (repository root)

Everything ships in `darnit-core`. No new package.

```text
packages/darnit/src/darnit/
+-- cli.py                                     # MODIFIED: add cmd_harness + subparser wiring
+-- harness/
|   +-- __init__.py                            # NEW
|   +-- driver.py                              # NEW: HarnessRun class + orchestration loop
|   +-- answer_sources.py                      # NEW: AnswerSource Protocol + ProjectYamlAnswerSource + FileAnswerSource
|   +-- report.py                              # NEW: MarkdownReporter, JsonReporter
|   +-- exit_codes.py                          # NEW: HarnessExitCode Literal + helpers
+-- sieve/
|   +-- orchestrator.py                        # (unchanged; harness invokes existing entry points)

tests/darnit/harness/
+-- __init__.py                                # NEW
+-- conftest.py                                # NEW: fixtures for API-key stubbing, MockLLMStep injection, minimal_repo copies
+-- test_answer_sources.py                     # NEW: Protocol conformance + file adapters
+-- test_driver.py                             # NEW: end-to-end HarnessRun on fixture; LLM dispatch through MockLLMStep
+-- test_report.py                             # NEW: Markdown + JSON report shape
+-- test_cli.py                                # NEW: `darnit harness` CLI invocation, exit codes, stderr progress lines
+-- fixtures/                                  # NEW
    +-- minimal_llm_repo/                      # A fixture control set that requires an llm_extract step
    +-- answers.yaml                           # Example --answers file used by the tests
```

**Structure Decision:** New `darnit.harness` subpackage under `darnit-core`. Rationale:

- Q3 said "no new PyPI distribution" -- rules out `packages/darnit-harness/`.
- The harness is a discrete subsystem (driver + answer sources + reporter + exit codes) so it deserves its own subpackage rather than being pasted into `cli.py`. Compare to `darnit.server/` (MCP layer) and `darnit.agent/` (existing pipeline loop) -- same shape.
- Test tree mirrors the subpackage layout so `pytest tests/darnit/harness/` runs the whole slice in isolation.

## Complexity Tracking

Not applicable. Constitution Check passed with no violations.
