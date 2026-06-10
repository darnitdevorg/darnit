# Implementation Plan: Threat-Model Coverage for Cobra-Based Go CLIs

**Branch**: `014-cobra-threat-model` | **Date**: 2026-05-18 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/014-cobra-threat-model/spec.md`

## Summary

Extend `darnit-baseline`'s tree-sitter discovery to recognise cobra-based Go CLI commands as entry points, group them into command families by filesystem layout, assign STRIDE categories via a small import-based heuristic, and render them as a top-level "CLI Entry Points" section of the threat-model document. Output is positioned as a reviewer-refinable draft, with `gittuf/gittuf` as the canonical reference target. Existing HTTP / Python / MCP discovery is unaffected.

The technical approach is a tightly-scoped extension to the existing `packages/darnit-baseline/src/darnit_baseline/threat_model/` module — new tree-sitter query patterns, a new entry-point extractor, a new family-grouping pass, a STRIDE-heuristic step, and a new rendering section. `EntryPointKind.CLI_COMMAND` already exists in `discovery_models.py`; no model surgery required.

## Technical Context

**Language/Version**: Python 3.11 / 3.12 (workspace targets).

**Primary Dependencies**: `tree-sitter`, `tree-sitter-language-pack` (Go grammar already loaded for existing HTTP discovery). No new runtime dependencies.

**Storage**: N/A — read-only static analysis writing Markdown / JSON / SARIF output files alongside existing threat-model output.

**Testing**: `pytest` with fixture-based discovery tests (mirrors existing `fixtures/go_http_handler` pattern). Unit tests for the new queries, the family-grouping pass, the STRIDE-heuristic mapping, the rendering helpers. Integration test against a synthetic multi-command cobra program. Optional manual end-to-end check against `gittuf/gittuf` (not in CI; documented in `quickstart.md`).

**Target Platform**: Same as darnit-baseline — cross-platform Python on Linux / macOS / Windows where the existing tree-sitter pipeline runs.

**Project Type**: Library extension. Internal-to-`darnit-baseline`; no new package, no new public API.

**Performance Goals**: SC-007 — under 60 seconds for repositories of up to ~500 Go source files on a modern laptop. The existing pipeline already finishes gittuf in <5s; cobra discovery adds one additional query pass plus per-finding heuristic evaluation, both linear in file count.

**Constraints**:
- No new runtime dependencies (FR-009 / Assumptions).
- No Go tooling invocation at audit time — no `go build`, `go vet`, `go list` (FR-010). Pure tree-sitter against source.
- Output is a draft (FR-006); findings must be marked as needing reviewer attention.
- Must not regress existing HTTP / Python / MCP discovery (FR-008).

**Scale/Scope**: Reference target is `gittuf/gittuf` — 267 `.go` files, 42 cobra command constructors, 0 HTTP routes. Spec's SC-002 sets a 5–15 distinct-family target. Phase 2 (urfave/cli, kingpin, gRPC, message handlers) is explicitly out of scope here.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| **I. Plugin Separation** | ✅ | Work is internal to `darnit-baseline`. No new core-framework imports of implementation packages; the existing `ComplianceImplementation` protocol surface is unchanged. |
| **II. Conservative-by-Default** | ✅ | The heuristic STRIDE category for opaque commands is rendered with an explicit "needs reviewer attention" marker (FR-005 + Q2 clarification). The system surfaces uncertainty rather than asserting categorical correctness — same posture as WARN > FAIL in compliance calculations. |
| **III. TOML-First Architecture** | ✅ | OSPS-SA-03.02 control metadata is already in `openssf-baseline.toml`. This feature changes the handler implementation only; no control schema changes. |
| **IV. Never Guess User Values** | ✅ | The output is positioned as a draft requiring human refinement. The heuristic categories are visible, marked, and recategorisable — not silently applied. Verification-prompt block (FR-006) tells the next reviewer exactly what to verify. No values are written to user-owned files like `.project/project.yaml` without confirmation. |
| **V. Sieve Pipeline Integrity** | ✅ | This is a remediation handler, not a sieve pass. The 4-phase sieve semantics are unaffected. |

**Result**: No gate violations. Proceeding to Phase 0.

## Project Structure

### Documentation (this feature)

```text
specs/014-cobra-threat-model/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan)
├── data-model.md        # Phase 1 output (/speckit-plan)
├── quickstart.md        # Phase 1 output (/speckit-plan)
├── contracts/           # Phase 1 output (/speckit-plan)
│   └── output-document-contract.md   # Schema of the rendered THREAT_MODEL.md
├── spec.md              # The feature specification
├── checklists/
│   └── requirements.md  # Spec-quality checklist
└── tasks.md             # Phase 2 output (/speckit-tasks — not produced here)
```

### Source Code (repository root)

```text
packages/darnit-baseline/src/darnit_baseline/threat_model/
├── queries/
│   └── go.py                    # Extend: new cobra command queries (composite literal + func New)
├── discovery_models.py          # No change — EntryPointKind.CLI_COMMAND already exists
├── ts_discovery.py              # Extend: new _extract_go_cli_commands + integration into Go pipeline
├── grouping.py                  # Extend: new group_by_cli_family for filesystem-layout coalescing
├── ranking.py                   # Extend: STRIDE-heuristic for CLI_COMMAND entry points
├── ts_generators.py             # Extend: new _render_cli_entry_points section + integration into Markdown / SARIF output
└── (other files unchanged)

tests/darnit_baseline/threat_model/
├── fixtures/
│   ├── cobra_minimal/           # NEW: smallest valid cobra program (1 command)
│   ├── cobra_subcommand/        # NEW: parent + 2-3 subcommands in nested directories
│   ├── cobra_mixed_http/        # NEW: cobra + net/http in same repo (FR-014)
│   └── go_no_cobra/             # NEW: Go project with no cobra (FR-009 false-positive test)
├── test_ts_discovery.py         # Extend: new test_*_cobra_* cases
├── test_grouping.py             # Extend: cli-family grouping tests
├── test_ranking.py              # Extend: STRIDE-heuristic mapping tests
└── test_ts_generators.py        # Extend: CLI section rendering tests
```

**Structure Decision**: Pure extension of an existing module. No new packages, no new top-level files, no public-API changes. Each touched file is a localised additive change; existing functions (HTTP extractor, Python extractors, etc.) are untouched. Test additions mirror the source additions one-for-one. Phase 2 (urfave/cli, kingpin) will follow the same pattern but with different query patterns — the family-grouping and rendering layers are designed to be framework-agnostic so they can be reused.

## Phase 0: Research

See [research.md](./research.md) for full detail. Summary of decisions:

| Decision | Outcome | Why |
|---|---|---|
| **Cobra AST patterns** | Two queries: (a) `composite_literal` with type `cobra.Command` containing `Use:` and `RunE:`/`Run:` fields; (b) `function_declaration` whose return type is `*cobra.Command`. Match either. | Covers gittuf's `func New() *cobra.Command` convention AND inline `&cobra.Command{...}` usage seen in cosign and slsa-verifier. Two queries is cheaper than one over-broad query with filtering. |
| **`command_root` inference** | The `command_root` is the deepest directory ancestor common to ≥2 discovered cobra files; default fallback to the project root if only one cobra file exists. `family_key` = first subdirectory beneath the `command_root`. Each family's `source_root` (the per-family path shown to reviewers) = `command_root + "/" + family_key`. | Implementation-cheap and matches gittuf's `internal/cmd/<family>/...` layout exactly. Cosign's `cmd/cosign/cli/<family>/...` also works. Robust to projects that put commands in `cmd/`, `internal/cmd/`, `pkg/cli/`, or anywhere else. |
| **STRIDE heuristic table** | Per-file import set drives the category: `os.Write*`/path-walking writers → Tampering; `crypto/*` and `sigstore/*` → Repudiation; `net/http` → Spoofing + Information Disclosure; `os/exec`/`syscall` → Elevation of Privilege; fall back to Tampering. Findings marked as needing reviewer attention. | Q2 clarification; the file is already parsed for cobra patterns, so reusing the existing `_collect_go_imports` helper makes import collection essentially free. |
| **Detection trigger** | Any source file importing `github.com/spf13/cobra` triggers the cobra extractor. Files not importing cobra are skipped (no false positives on look-alike struct literals). | Cheapest reliable trigger; FR-009 conformance. |
| **Output size enforcement** | Family-level grouping inherently caps finding count at the number of top-level command directories. For gittuf this is naturally ~10. No additional truncation in scope; if a project exceeds 15 families the document still renders all of them (better than truncating in a draft). | SC-002 was a target, not a hard cap; truncation would compromise the "humans refine" goal. |
| **SC-006 validation method** | PR-time human review against the gittuf reference output, plus snapshot tests on synthetic fixtures where exact category mappings are deterministic. No LLM-judge in CI (flaky). | Snapshot tests catch heuristic regressions on known cases; the wider "plausibility" judgment stays with the reviewer. |
| **Observability of skipped patterns** | Skipped patterns surface in the rendered document's existing Limitations section (FR-007). Optional `--debug` flag on the handler may emit structured log records for skipped patterns — deferred to a follow-up unless needed during implementation. | User-visible surface is already in scope; runtime logging is plumbing, not a behavior change. |

**Output**: research.md with all decisions and rationales.

## Phase 1: Design & Contracts

**Prerequisites**: `research.md` complete.

### 1. Data model — see [data-model.md](./data-model.md)

Extends the existing `DiscoveredEntryPoint` (no schema change; the `kind=EntryPointKind.CLI_COMMAND` value is used) and adds a new conceptual entity, `CommandFamily`, for grouping. The family is not persisted — it lives between the extraction and rendering stages, materialised by `group_by_cli_family()` from the flat list of `DiscoveredEntryPoint`s.

### 2. Contracts — see [contracts/output-document-contract.md](./contracts/output-document-contract.md)

The rendered Markdown document is the user-facing contract for this feature. The contract document spells out:

- The new top-level section order ("CLI Entry Points" before / after "HTTP Entry Points" per FR-014).
- The family-finding structure (one finding per family, with command locations listed inside).
- Required finding fields (family name, location, STRIDE category, brief description, "needs reviewer attention" marker).
- Verification-prompt-block contract (consistent with what the existing generator emits).
- Limitations-section contract (unrecognised patterns surface here).

### 3. Quickstart — see [quickstart.md](./quickstart.md)

A maintainer-facing runbook for verifying this feature end-to-end:
1. Clone gittuf into a scratch dir.
2. Run the threat-model generator against it.
3. Confirm the output has a "CLI Entry Points" section with 5–15 family findings.
4. Open one family's finding and trace its `location` pointer to the source.
5. Verify the document's "Limitations" section lists any skipped patterns honestly.

### 4. Agent context update

CLAUDE.md is updated to reference this plan inside its `<!-- SPECKIT START -->` / `<!-- SPECKIT END -->` markers. The previous reference (if any) is replaced.

## Re-evaluation of Constitution Check (post-design)

| Principle | Status after Phase 1 |
|---|---|
| **I. Plugin Separation** | ✅ No core ↔ implementation import boundary crossings introduced. |
| **II. Conservative-by-Default** | ✅ Heuristic categories are explicitly flagged as needing reviewer attention; the draft framing is preserved end-to-end. |
| **III. TOML-First Architecture** | ✅ Control metadata unchanged; implementation-only extension. |
| **IV. Never Guess User Values** | ✅ No user-owned values are written without confirmation. The output is the audit's own artifact, expressly drafted-not-asserted. |
| **V. Sieve Pipeline Integrity** | ✅ Sieve unchanged. |

**Result**: Gates remain green. Proceed to `/speckit-tasks`.

## Complexity Tracking

*No Constitution violations to justify.*
