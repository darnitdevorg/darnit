# Implementation Plan: Pinned-Requirements Detection

**Branch**: `037-pinned-requirements-detection` | **Date**: 2026-09-17 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/037-pinned-requirements-detection/spec.md`

## Summary

`repro_deps_pinned` judges dependency pinning by filename alone -- it never opens the files it judges, so a `pip-compile --generate-hashes` output receives the same hard FAIL as a bare `numpy` (issue #429). The fix reads the file and classifies it into hash-pinned (PASS), version-pinned (WARN), unpinned (FAIL), or not-inspectable (FAIL).

The WARN tier is what makes this more than a plugin change. A handler's verdict vocabulary is PASS / FAIL / INCONCLUSIVE / ERROR; there is no WARN. The only existing route to a WARN status is the all-inconclusive fallthrough in the orchestrator, which replaces the handler's message with a fixed "manual verification required" string. FR-005 and FR-013 require a WARN that says why, so the framework gains a conclusive WARN outcome (FR-016) and the plugin gains a parser.

Two packages change: `packages/darnit/` (verdict vocabulary) and `packages/darnit-reproducibility/` (classification). The framework change is additive and gated so that no existing handler's verdict moves (FR-017, SC-008).

## Technical Context

**Language/Version**: Python 3.11/3.12 (workspace targets)

**Primary Dependencies**: no new runtime dependency is added. Requirement parsing uses `packaging` (PEP 440 `Requirement` / `SpecifierSet`), which `darnit` core already imports at runtime in `core/composition.py:363` and `config/framework_schema.py:1445`. See research.md R4 -- `packaging` is imported but undeclared today, and this plan declares it rather than adding it.

**Storage**: filesystem only. One file read per audit, no caching (spec Assumptions).

**Testing**: pytest. New unit tests under `tests/darnit_reproducibility/` for classification and `tests/darnit/sieve/` for the WARN outcome. Fixture repos under `tests/darnit_reproducibility/fixtures/`.

**Target Platform**: same as the rest of darnit -- local filesystem audit of a checked-out repository.

**Project Type**: Python monorepo, framework plus plugins.

**Performance Goals**: none beyond "does not regress audit wall time." A `requirements.txt` is a small text file read once.

**Constraints**:
- FR-014 / FR-017 / SC-004 / SC-005 / SC-008: this feature must be a no-op for every repository it does not explicitly claim. That is the dominant design constraint and it shapes the test strategy more than the parser does.
- FR-015: no new runtime dependency outside the existing darnit dependency set.
- FR-019: file discovery is unchanged -- root `requirements.txt` only.

**Scale/Scope**: one handler, one new framework enum member, one new orchestrator disposition. Roughly 5 source files and 4 test files.

## Constitution Check

*GATE: evaluated before Phase 0 and re-evaluated after Phase 1.*

### I. Plugin Separation -- PASS

`darnit` core gains a vocabulary item; it does not learn anything about requirements files or about `darnit-reproducibility`. The classification logic lives entirely in the plugin. No new core-to-implementation import. The new outcome is available to every handler, not privileged to this one.

The `hasattr()` back-compat rule does not apply -- no protocol method is added. The equivalent obligation for an enum is that no consumer may assume exhaustiveness; research.md R2 records where that is checked.

### II. Conservative-by-Default -- PASS, and the principle is the reason for the design

- The bug is a false negative, which Principle II calls the preferable direction. The fix must not overcorrect. The single place it could is FR-004's PASS, which is bounded by FR-010: a VCS reference caps the file at WARN precisely so the PASS never rests on evidence weaker than the lock files this control already passes.
- FR-005's WARN is the principle applied directly: direct pins with floating transitive dependencies is a known-incomplete state, and WARN counts as FAIL for compliance. A `==`-pinning project does not reach compliance on this control.
- No user-judgment value is concluded anywhere; Principle IV is not engaged.

### III. TOML-First Architecture -- PASS

No control metadata moves into Python. `RE-01.01` keeps its TOML definition and its existing two passes (`repro_deps_pinned`, then `manual`). No new control, no new TOML key, no `rules/catalog.py` entry.

### V. Sieve Pipeline Integrity -- PASS, with the reasoning recorded because this is the gate most at risk

Principle V states that the orchestrator stops at the first conclusive result, that each pass type has well-defined PASS / FAIL / INCONCLUSIVE semantics, and that "a handler returning INCONCLUSIVE MUST cause the pipeline to continue to the next phase, never short-circuit to PASS."

A conclusive WARN is compatible with all three:

1. It does not change INCONCLUSIVE behavior. INCONCLUSIVE still continues. WARN is a distinct outcome, chosen by a handler that determined something, not by one that could not determine anything.
2. It never short-circuits to PASS. It short-circuits in the direction Principle II treats as equivalent to FAIL, which is the safe direction the principle exists to protect.
3. It is gated by the feature 025 authority rule exactly as PASS and FAIL are: only `dispositive` or `asserted` authority concludes. A suggestive step -- an LLM -- cannot manufacture a WARN that stops the chain any more than it can manufacture a PASS. See contracts/handler-warn-outcome.md.

The semantics are stated normatively in the contract and, per Development Workflow item 3, in `docs/architecture/framework-design.md` before the code lands.

### Development Workflow -- one obligation carried into tasks

Workflow item 3 requires that spec changes update `docs/architecture/framework-design.md` first, then validate sync. Adding a handler outcome is a framework-behavior change, so `framework-design.md` must document the WARN outcome and the updated disposition table, and `scripts/validate_sync.py` must pass afterwards. This is a task, not an afterthought.

### Gate result

No violations. Complexity Tracking below records the one judgment call that a reviewer is most likely to challenge.

## Project Structure

### Documentation (this feature)

```text
specs/037-pinned-requirements-detection/
|-- plan.md                              # This file
|-- spec.md
|-- research.md                          # Phase 0
|-- data-model.md                        # Phase 1
|-- quickstart.md                        # Phase 1
|-- contracts/
|   |-- handler-warn-outcome.md          # Framework contract
|   `-- requirements-classification.md   # Plugin contract
|-- checklists/requirements.md
`-- tasks.md                             # /speckit-tasks output, not created here
```

### Source Code (repository root)

```text
packages/darnit/src/darnit/sieve/
|-- handler_registry.py      # HandlerResultStatus gains WARN
|-- orchestrator.py          # StepDisposition.CONCLUDE_WARN; resolve_step_result;
|                            #   _dispatch_handler_invocations branch;
|                            #   _handler_status_to_outcome; _apply_cel_expr guard
`-- models.py                # PassOutcome gains WARN (see research.md R2)

packages/darnit-reproducibility/src/darnit_reproducibility/
|-- requirements_pins.py     # NEW -- line parsing and classification, no I/O decisions
|-- handlers.py              # repro_deps_pinned_handler consumes the classifier
`-- (pyproject.toml)         # declares `packaging` (research.md R4)

docs/architecture/framework-design.md    # Normative WARN outcome + disposition table

tests/darnit/sieve/
`-- test_handler_warn_outcome.py         # NEW -- framework-level WARN semantics

tests/darnit_reproducibility/
|-- test_requirements_pins.py            # NEW -- classification table, edge cases
|-- test_deps_pinned_handler.py          # NEW -- handler verdicts end to end
`-- fixtures/                            # NEW -- one repo dir per edge case
```

**Structure Decision**: the existing monorepo layout is used unchanged. The one structural choice is putting classification in a new `requirements_pins.py` rather than inside `handlers.py`: `handlers.py` is a flat file of five sieve handlers with no module-level structure, and a parser with a dozen edge cases would dominate it. The new module takes text and returns a classification -- it does no file discovery and constructs no `HandlerResult`, which keeps its tests free of sieve scaffolding.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| A plugin-motivated change to `darnit` core (new handler outcome) | FR-005 requires a WARN carrying the handler's own message. No handler can produce one; the only WARN route discards the message and is reached only by exhausting every pass. | Returning INCONCLUSIVE and relying on the fallthrough was evaluated and rejected during `/speckit-clarify` (Q1, option B): the operator would see "Could not automatically verify - manual verification required" for a file the tool successfully read and understood, which fails FR-005 and FR-013 and is the exact confusion #427 was about. Rewriting the fallthrough to carry the last handler message (option C) fails because `RE-01.01` ends with a `manual` pass that also returns INCONCLUSIVE, so the last message would be the manual placeholder's. |
| `PassOutcome` gains a member alongside `HandlerResultStatus` | `pass_history` records what each pass decided; mapping a WARN pass to INCONCLUSIVE would misreport a pass that concluded as one that did not. | Mapping WARN to INCONCLUSIVE in `_handler_status_to_outcome` is a one-line alternative, but `pass_history` is the audit trail a reviewer reads to check a verdict, and it would then contradict the control's status. Blast radius is small: `PassOutcome` has exactly two consumer files (`orchestrator.py`, `harness/driver.py`). See research.md R2. |
