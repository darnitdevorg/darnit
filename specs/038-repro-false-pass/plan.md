# Implementation Plan: Honest Verdicts for Reproducibility Controls

**Branch**: `038-repro-false-pass` | **Date**: 2026-09-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/038-repro-false-pass/spec.md`

## Summary

Four issues (#445, #431, #430, #432) where reproducibility controls report a repository as better than the evidence supports. Two are verdict-strength corrections and two are detection-coverage additions.

- **#445** `repro_bit_for_bit` PASSes because `SOURCE_DATE_EPOCH` appears in a workflow. It becomes a conclusive WARN naming the signal and what stayed unverified.
- **#431** `repro_build_env_declared` PASSes on any `Dockerfile`, including `FROM alpine:latest`. It reads the file and requires digest pinning.
- **#430** `_SUSPICIOUS_PATTERNS` misses `go install`, `go get`, `cargo install`, `gem install`.
- **#432** nothing detects non-deterministic compiler flags.

One package changes: `packages/darnit-reproducibility/`. No framework change -- feature 037 already added the conclusive WARN these verdicts need, which is why this branch stacks on #443.

The load-bearing consequence is FR-010: `_detect_strong_hermeticity_signal` gates its Nix path on `dependency_results.get("RE-01.02") == "PASS"`, so tightening #431 withdraws a hermeticity signal from repositories that did not change. That is accepted and must be visible in the result.

## Technical Context

**Language/Version**: Python 3.11/3.12 (workspace targets)

**Primary Dependencies**: none added. All four changes are pure-stdlib string and path work inside one module.

**Storage**: filesystem only; files are read during the audit as they are today.

**Testing**: pytest. New unit tests in `tests/darnit_reproducibility/`; fixtures as tmp_path-constructed repos, matching the convention already used by `TestRepoDepsPin`.

**Target Platform**: local filesystem audit of a checked-out repository.

**Project Type**: Python monorepo, framework plus plugins.

**Performance Goals**: none new. `_FILE_SCAN_LIMIT = 30` already bounds scan cost and is not changed.

**Constraints**:
- FR-013 / SC-006 / SC-007: no control outside the three named may move, and inherently-pinned declarations must produce byte-identical output.
- FR-014: no new runtime dependency.
- FR-015: a pattern in a comment is not an occurrence. `_scan_line` already strips comments; the new detectors must go through it rather than around it.

**Scale/Scope**: three handlers plus the shared scan helpers in one file; roughly 2 source files and 3 test files.

## Constitution Check

*GATE: evaluated before Phase 0 and re-evaluated after Phase 1.*

### I. Plugin Separation -- PASS

Entirely within `packages/darnit-reproducibility/`. No core change, no new protocol method, no framework import of an implementation. The conclusive WARN this feature depends on is already in core from feature 037.

### II. Conservative-by-Default -- PASS; this feature exists to enforce it

Every change moves a verdict in the direction the constitution requires. #445 and #431 replace PASSes that were never earned; #430 and #432 surface violations that were being missed. Nothing moves toward PASS.

The one place this could overcorrect is FR-005's rule that only digest pinning counts, which will fail `FROM python:3.12-slim-bookworm`. That is the intended reading: a tag is mutable, and `3.12-slim-bookworm` resolves to different bytes month to month. Recorded in Complexity Tracking because it will generate pushback.

FR-010's propagation is the same principle applied transitively: the Nix signal was always conditional on the environment being confirmed, and it stops being confirmed.

### III. TOML-First Architecture -- PASS

No control metadata moves into Python. No new control, no new TOML key. `reproducibility.toml` is untouched.

### V. Sieve Pipeline Integrity -- PASS

The WARN in FR-001 is the conclusive outcome added by feature 037, gated by the same authority rule as PASS and FAIL. INCONCLUSIVE behavior is unchanged. `repro_bit_for_bit` and `repro_build_env_declared` are registered `default_authority="dispositive"`, so their WARN concludes.

One dependency-ordering note: FR-010 relies on `dependency_results["RE-01.02"]`, which requires RE-01.02 to be verified before RE-02.01. The orchestrator's `verify_batch` already topologically sorts on `depends_on`/`inferred_from`, and the gate exists and works today, so this is a property to preserve rather than build.

### Development Workflow

No framework behavior changes, so `docs/architecture/framework-design.md` needs no update. `validate_sync.py` must still pass.

### Gate result

No violations. Two judgment calls recorded below.

## Project Structure

### Documentation (this feature)

```text
specs/038-repro-false-pass/
|-- plan.md                        # This file
|-- spec.md
|-- research.md                    # Phase 0
|-- data-model.md                  # Phase 1
|-- quickstart.md                  # Phase 1
|-- contracts/
|   |-- build-env-pinning.md       # RE-01.02 contract
|   `-- hermeticity-scan.md        # RE-02.01 scan contract
|-- checklists/requirements.md
`-- tasks.md                       # /speckit-tasks output, not created here
```

### Source Code (repository root)

```text
packages/darnit-reproducibility/src/darnit_reproducibility/
|-- container_pinning.py     # NEW -- FROM-line parsing and pin classification
`-- handlers.py              # three handlers + the shared scan tables

tests/darnit_reproducibility/
|-- test_container_pinning.py   # NEW -- FROM-line table, pure function
|-- test_handlers.py            # extend TestBuildEnvDeclared / TestHermeticBuild / TestBitForBit
`-- test_repro_corpus.py        # NEW -- SC-007 corpus expectation
```

**Structure Decision**: `FROM`-line parsing goes in a new `container_pinning.py` for the same reason feature 037 put requirement parsing in `requirements_pins.py`: it is a pure text-to-classification function with a table of edge cases, and `handlers.py` is already a flat 900-line module. The new module does no file discovery and constructs no `HandlerResult`.

The compiler-flag and installer detection stays in `handlers.py`, because both are additions to the existing `_SUSPICIOUS_PATTERNS` / `_scan_line` machinery rather than new logic.

## Complexity Tracking

| Decision | Why | Alternative rejected because |
|---|---|---|
| Only digest pinning counts; `FROM python:3.12-slim-bookworm` fails | A tag is mutable. `3.12-slim-bookworm` is rebuilt regularly and resolves to different bytes over time, which is precisely the property RE-01.02 claims to establish. | Accepting a "specific-looking" tag would mean picking an arbitrary line between `latest` and `3.12.1-slim-bookworm-20260101`, neither of which is actually immutable. This repository's own `packaging/container/Dockerfile` uses `FROM python:3.12-slim-bookworm` and will be flagged -- see quickstart.md, which treats that as a feature rather than an embarrassment. |
| FR-010 propagation: repos lose an RE-02.01 PASS without changing | The Nix gate's premise is that RE-01.02 confirmed the declared environment. Once it stops confirming, keeping the PASS keeps a verdict whose justification is gone. | Judging the flake independently (spec Q1 option B) preserves a PASS built on the evidence this feature is removing. Resolved as option A during `/speckit-specify`. |
