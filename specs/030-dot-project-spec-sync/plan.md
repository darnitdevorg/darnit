# Implementation Plan: Sync `.project/` reader with current CNCF spec

**Branch**: `030-dot-project-spec-sync` | **Date**: 2026-08-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/030-dot-project-spec-sync/spec.md` (with 3 clarifications recorded 2026-08-14: parse-only scope for new fields; one-release grace window for renamed fields with deprecation warning; version identifier bumps 1:1 with tracked-hash file).

## Summary

The upstream CNCF `.project/` specification (`utilities/dot-project/types.go`) has drifted since darnit last reconciled. The tracked hash in `.github/dot-project-spec-hash.txt` (`d8ca8361...`) no longer matches the current upstream (`860df23e...`), so `tests/darnit/context/test_dot_project_upstream.py::TestUpstreamSpecSync::test_upstream_spec_unchanged` fails on every PR. This feature reconciles `packages/darnit/src/darnit/context/dot_project.py` with the current upstream state, updates `DOT_PROJECT_SPEC_VERSION`, refreshes the tracked-hash file, and covers the reconciled surface with a fixture-driven test that exercises every field darnit reads today. Scope is strictly parse-only (per Q1 clarification): the reader accepts every field the current upstream declares, but exposes only the fields darnit already consumed pre-reconciliation. Any newly renamed field carries a one-release deprecation alias (per Q2). The version identifier bumps 1:1 with the tracked-hash file (per Q3).

## Technical Context

**Language/Version**: Python 3.11/3.12 (workspace targets — same as the rest of darnit)

**Primary Dependencies**: PyYAML (already used by `dot_project.py`) for parsing; standard library `hashlib`/`urllib.request` for the upstream-sync test (already imported by `test_dot_project_upstream.py`). No new runtime dependencies.

**Storage**: Filesystem only. Reads `.project/project.yaml` from the target repository; writes nothing new. `.github/dot-project-spec-hash.txt` is a tracked one-line file that the test compares against.

**Testing**: pytest, extending existing `tests/darnit/context/test_dot_project*.py` files. New fixture at `tests/darnit/context/fixtures/dot_project_full_field_coverage.yaml` (or similar) that exercises every field darnit reads today so SC-002 (behavior parity pre/post reconciliation) is mechanically verifiable.

**Target Platform**: Same as darnit workspace: any platform Python 3.11+ runs on. No platform-specific behavior introduced.

**Project Type**: Library/framework maintenance change; scoped to `packages/darnit/` core. No new packages, no new plugins.

**Performance Goals**: N/A. The reader parses a single small YAML file per audit; the change does not alter parsing complexity.

**Constraints**:
- Zero product-source additions in `packages/darnit-baseline/` or other implementation packages (the reader is core-only).
- Reader public field names darnit already exposes MUST remain unchanged (spec FR-003).
- Deprecation warnings for renamed upstream fields MUST emit through Python's `warnings.warn(..., DeprecationWarning)` so downstream callers can filter or escalate them uniformly (resolves the outstanding "delivery mechanism" question from the clarify phase).

**Scale/Scope**: One reader file (~885 lines), one tracked-hash file, one upstream-sync test, plus one new fixture and its consumer test. Estimated diff: <400 lines of production code, <200 lines of test code.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The darnit constitution (5 core principles, plus architecture constraints and workflow rules) evaluated against this feature:

| Principle | Applies | Assessment |
|-----------|---------|------------|
| I. Plugin Separation | Yes | PASS. The reader lives in `packages/darnit/src/darnit/context/dot_project.py` (core framework). This feature does not import any implementation package. Deprecation-warning additions do not cross the framework/implementation boundary. |
| II. Conservative-by-Default | Yes | PASS. The reader has no compliance-status side effects; it produces typed values that downstream controls consume. Parse-only scope (Q1 clarification) means no new value can silently become a control's conclusion. If a renamed field is not aliased, a control that used to consume it would now see a missing value and its own conservative-by-default logic kicks in as it would for any other missing project context. |
| III. TOML-First Architecture | Yes | PASS (N/A in substance). This feature touches no control TOML. `dot_project.py` is the *reader* for a YAML file whose schema is owned upstream, not a control definition. |
| IV. Never Guess User Values | Yes | PASS. The reader does not conclude user-judgment values. Reconciling with the current upstream cannot change the auto_detect / allow_sieve_hints axes (they live in framework TOML, not in `.project/project.yaml`). Renamed-field aliases warn but do not guess. |
| V. Sieve Pipeline Integrity | Yes | PASS (N/A in substance). The reader is called from the sieve orchestrator's context-injection step, not from within a pass. Its output shape is unchanged for every field darnit already reads (spec FR-003), so no pass semantics shift. |

Architecture constraints (three-layer architecture, package structure): PASS. The change is confined to `packages/darnit/` core. No new layers or packages.

Development workflow (lint, tests, spec sync, no-emoji rules): PASS. Standard workflow; no new gates required.

**Gate result: PASS. Proceed to Phase 0.**

## Project Structure

### Documentation (this feature)

```text
specs/030-dot-project-spec-sync/
├── plan.md              # This file
├── research.md          # Phase 0 output — upstream diff analysis + decisions
├── data-model.md        # Phase 1 output — reconciled reader dataclass surface
├── quickstart.md        # Phase 1 output — maintainer runbook
├── contracts/
│   └── reader-contract.md   # Phase 1 output — public reader API contract
├── checklists/
│   └── requirements.md  # From /speckit-specify
└── tasks.md             # /speckit-tasks output (not created here)
```

### Source Code (repository root)

```text
packages/darnit/src/darnit/context/
├── dot_project.py            # THE reconciliation surface. Dataclass updates, alias handling, DOT_PROJECT_SPEC_VERSION bump.
└── (no new modules)

.github/
└── dot-project-spec-hash.txt # Tracked-hash file. Rewritten to the current upstream SHA-256.

tests/darnit/context/
├── test_dot_project_upstream.py     # Existing sync test; no code changes needed if reconciliation is complete.
├── test_dot_project.py              # Existing reader tests; may gain a small addition for the alias-emits-warning case.
└── fixtures/
    └── full_field_coverage.yaml     # NEW fixture: every field darnit reads today, populated with representative values.
```

**Structure Decision**: Single-file reconciliation in the core framework. No new packages, no new modules. Testing extends existing `tests/darnit/context/` tests plus one new fixture. This layout matches the change's scope: reconciliation is a maintenance task on one reader, not a new subsystem.

## Complexity Tracking

No constitution violations to justify. The feature is a scoped reconciliation with zero new architecture.

## Phase 0: Research

Research questions surfaced by Technical Context and the spec's Assumptions/Edge Cases:

1. **What actually changed between the tracked-hash version (`d8ca8361...`) and the current upstream (`860df23e...`)?** — Fetch both blobs, produce a field-level diff, and classify each change as {added, renamed, removed, reshape}. This is the load-bearing input to every downstream decision.
2. **Which of darnit's current dataclass field names map to renamed upstream fields?** — Cross-walk `dot_project.py`'s public field surface against the upstream `Project` struct and its nested types. A rename that hits a field darnit consumes triggers FR-010's alias-with-warning path; a rename that hits a field darnit already ignores is a no-op.
3. **Does upstream now expose a `schema_version` (or equivalent) field on `Project`?** — The current `types.go` shows `SchemaVersion string \`json:"schema_version"\`` on Project. This is the CNCF-owned counterpart to darnit's `DOT_PROJECT_SPEC_VERSION`. Research decides whether darnit's version identifier should mirror the upstream schema_version string (when present) or remain independent per the Q3 clarification (bump on every drift regardless of upstream's own versioning).
4. **What is the right Python channel for the deprecation warning (FR-010)?** — Options: `warnings.warn(..., DeprecationWarning)`, `logger.warning(...)`, or a structured event. Constraint-level decision: `warnings.warn` is the Python-native mechanism for user-facing deprecations, honors filter configuration (`-W`), and matches how other Python libraries signal spec-migration guidance. `logger.warning` is available in the callers already and easier to route into darnit's INFO/WARN report streams, but does not gain a stable-across-versions guarantee. Research settles the choice with a rationale.
5. **How do we mechanically verify that no darnit control's behavior flips because of the reconciliation (SC-002)?** — Options: a golden-file test that snapshots the reader's output on the fixture and asserts equality; a semantic test that iterates every field darnit reads and asserts its post-reconciliation value equals a hand-authored expected value; or a control-invocation test that runs a representative subset of controls against the fixture pre- and post-. Research picks the smallest option that gives SC-002 real teeth.

**Output**: `research.md` documenting each decision with rationale and rejected alternatives.

## Phase 1: Design & Contracts

**Prerequisites**: `research.md` complete.

### Data Model (`data-model.md`)

The reconciled reader dataclass surface, expressed as:

- Every existing dataclass in `dot_project.py` with its field list.
- For each dataclass, per-field annotations: `KEPT` (unchanged), `KEPT-WITH-ALIAS` (new-name + old-name accepted, deprecation warning on old), `NEW-IGNORED` (upstream added a field; reader accepts but does not expose it via any dataclass attribute), `RESHAPED` (field shape changed upstream; reader handles both old and new shapes).
- The `DOT_PROJECT_SPEC_VERSION` bump target (concrete new value).
- The new `full_field_coverage.yaml` fixture's field census (one row per field darnit reads today, with the representative value used in the fixture).

The data-model document is a static reference for reviewers and future maintainers; it does not introduce new runtime types.

### Contracts (`contracts/reader-contract.md`)

The public reader API exposed to darnit callers. Darnit is a library and its "contract" is the shape of the module's public callable and dataclass surface. The reader contract enumerates:

- Public callables and their signatures (`DotProjectReader.load(...)`, `DotProjectReader.parse(...)`, etc.), with a note per callable stating whether the reconciliation changes the signature (must be "no" per FR-008).
- Public dataclass attributes and their types, with the same per-field annotation vocabulary as data-model.md.
- Constants exposed by the module (`DOT_PROJECT_SPEC_VERSION`, `DOT_PROJECT_SPEC_URL`), with the concrete post-reconciliation values.
- Warning behavior: which condition triggers `warnings.warn(..., DeprecationWarning)`, with the exact warning message text.

The contract file exists so that when the next reconciliation lands, the maintainer can diff the new contract against this one and see exactly what a downstream consumer might notice.

### Quickstart (`quickstart.md`)

Runbook for the maintainer running this reconciliation now, and for the maintainer running the next one. Contents:

1. Fetch upstream `types.go` at the current CNCF `main` tip.
2. Compare against the tracked-hash file's referent blob (retrieve from git history if needed).
3. Produce a per-field diff and classify each change.
4. Update `dot_project.py` per the classifications (dataclass edits, alias additions, deprecation warnings).
5. Bump `DOT_PROJECT_SPEC_VERSION` per the 1:1-with-tracked-hash rule (Q3).
6. Run `uv run pytest tests/darnit/context/test_dot_project_upstream.py -v --update-hash` to refresh the tracked-hash file.
7. Run `uv run pytest tests/darnit/context/ -v` and confirm the new fixture test passes.
8. Run the full workspace sweep as a smoke check.

This file also lives as the destination the failure message in `test_upstream_spec_unchanged` points at (matches spec SC-005).

### Agent Context Update

Update the reference between `<!-- SPECKIT START -->` and `<!-- SPECKIT END -->` markers in `CLAUDE.md` to point at `specs/030-dot-project-spec-sync/plan.md`.

## Post-Design Constitution Recheck

The design phase artifacts do not introduce any new principle-touching decisions:

- Plugin Separation: unchanged; all edits are within `packages/darnit/`.
- Conservative-by-Default: unchanged; reader emits typed values with the same semantics as before.
- TOML-First: unchanged; no controls touched.
- Never Guess User Values: reinforced by the deprecation-warning mechanism (renamed field is surfaced to the maintainer as a candidate migration action, never silently applied differently).
- Sieve Pipeline Integrity: unchanged; reader is upstream of the sieve.

**Post-design gate: PASS.**
