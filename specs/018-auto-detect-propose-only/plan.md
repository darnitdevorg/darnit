# Implementation Plan: Propose-Only Auto-Detection for User-Judgment Keys

**Branch**: `018-auto-detect-propose-only` | **Date**: 2026-07-28 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/018-auto-detect-propose-only/spec.md`

## Summary

Amend the project constitution and the prose documentation that restates it so
that a key requiring human judgment may have a candidate value proposed to a
person, while keeping the prohibition on that candidate being used unconfirmed.
RFC-0001 names this as the Stage 0 prerequisite for its Stage 1.

Phase 0 research changed the character of this work. The propose-only behavior
is not hypothetical and is not deferred to Stage 1: it already ships. The
framework reads `hint_sources` files to produce candidate values for keys
marked `auto_detect = false`, and a dedicated `allow_sieve_hints` flag exists,
is documented in the authoritative framework spec, and is enabled for
`maintainers` and `security_contact` in the OpenSSF Baseline configuration.
This amendment therefore reconciles the constitution with behavior the project
already has, rather than authorizing something new. See
[research.md](research.md) for the evidence.

That reframing makes the change lower-risk (no behavior moves) and more urgent
(the governing document currently misdescribes the system).

## Technical Context

**Language/Version**: N/A -- this feature changes prose documents only. No
source file is modified. Python 3.11/3.12 remains the workspace target.

**Primary Dependencies**: None added or changed.

**Storage**: N/A.

**Testing**: The existing suites (`ruff check`, `pytest tests/ --ignore=tests/integration/`,
`scripts/validate_sync.py`) serve as the regression evidence for FR-013. They
must pass unchanged, and no test may need modification -- a test requiring a
change would prove behavior moved.

**Target Platform**: N/A.

**Project Type**: Governance and documentation amendment within an existing
Python monorepo.

**Performance Goals**: N/A.

**Constraints**: ASCII-only content per project writing rules. No source,
configuration, or test file may be modified (FR-011, FR-013). The constitution
bump is fixed at one MINOR increment (FR-009, 1.2.0 -> 1.3.0).

**Scale/Scope**: Six prose files, one of which is the constitution. Nineteen
inventory entries: ten updated, five deferred, and four historical records left
alone.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Justification |
|---|---|---|
| I. Plugin Separation | N/A | No code changes; no imports added in either direction. |
| II. Conservative-by-Default | PASS | The amendment preserves every clause: unverified is not compliant, WARN counts as FAIL, false negatives are preferred. It narrows only the separate question of whether a candidate may be computed and shown. |
| III. TOML-First Architecture | N/A | No control metadata moves. Configuration files are explicitly out of scope (FR-011). |
| IV. Never Guess User Values | VIOLATED TODAY; this amendment is the remedy | The shipped system already breaches this principle as literally written: `collection.py:264-271` resolves `hint_sources` with no `auto_detect` gate, and `openssf-baseline.toml:287-289,300-301` enables it for `maintainers` and `security_contact` (research.md Finding 1). The breach is of the wording, not of the intent -- nothing concludes a user-judgment key. The core requirement -- the framework MUST NOT silently apply values requiring user judgment -- survives the amendment verbatim. FR-002 through FR-007 hold that line while the surrounding bullets change, and FR-004 closes a latent hole by scoping the confidence-threshold provision away from user-judgment keys, which today reads as unscoped. |
| V. Sieve Pipeline Integrity | PASS | Phase ordering, INCONCLUSIVE semantics, and the no-short-circuit-to-PASS rule are untouched. |
| Development Workflow | PASS | Lint, tests, and `validate_sync.py` all run and must pass. No spec-sync implication, since `docs/architecture/framework-design.md` already documents the propose mechanism (research.md, Finding 1) and needs no change. |

**Post-Phase-1 re-check**: PASS, unchanged. The design phase produced no new
artifacts that touch code, so no gate moved. The one substantive change Phase 0
forced was to FR-014's framing, recorded under Deviations below; it relaxes a
requirement rather than adding a violation.

### Deviations from clarified answers

**Q3 (flag naming) -- resolved 2026-07-28.** The original answer was to keep the
`auto_detect` name and record the mismatch between name and meaning as known
debt. Phase 0 found the mismatch does not exist: the project already has two
flags covering the two axes, where `auto_detect` gates whether a value may be
concluded automatically and `allow_sieve_hints` gates whether a detected value
may be shown as a suggestion. Under that reading `auto_detect = false` is an
accurate name for "may not conclude."

The user confirmed dropping the debt clause. FR-014 keeps the compatibility
requirement, and the new FR-015 requires the amendment to explain the flag pair
instead, since that relationship is the mechanism that makes propose-only safe
and is currently documented nowhere near the rule it implements.

## Project Structure

### Documentation (this feature)

```text
specs/018-auto-detect-propose-only/
  plan.md              # This file
  research.md          # Phase 0: the FR-010 inventory and three findings
  data-model.md        # Phase 1: canonical vocabulary and value lifecycle
  checklists/
    requirements.md    # Spec quality checklist
  tasks.md             # Phase 2 output (/speckit-tasks -- NOT created here)
```

No `contracts/` directory: the feature exposes no interface. The nearest thing
to a contract is the normative rule text itself, and drafting that in the plan
phase would leave tasks as mechanical transcription while moving the reviewable
substance out of the PR diff.

No `quickstart.md`: there is nothing for a user to run. The equivalent
verification is reading the amended rule, which the spec's Independent Tests
already specify.

### Files changed (repository root)

```text
.specify/memory/constitution.md    # Principle IV bullets; version 1.2.0 -> 1.3.0
                                   # plus a new Sync Impact Report block
CLAUDE.md                          # Conservative-by-Default section, lines 170-172
ARCHITECTURE.md                    # line 29 (normative restatement), line 441
docs/IMPLEMENTATION_GUIDE.md       # narrative around the auto_detect examples
docs/design/CONTEXT_PROMPTS.md     # schema table entry for auto_detect
docs/rfcs/0001-core-rearchitecture.md  # Stage 0 row: mark satisfied, link the PR
```

**Structure Decision**: No source tree is involved. The change set is six prose
files at repository root and under `docs/`, listed above and derived from the
inventory in research.md. Package directories under `packages/` are deliberately
untouched; the inventory records those locations as deferred.

## Complexity Tracking

No constitution violations. Table omitted.
