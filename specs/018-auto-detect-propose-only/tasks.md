---

description: "Task list for feature 018: propose-only auto-detection for user-judgment keys"
---

# Tasks: Propose-Only Auto-Detection for User-Judgment Keys

**Input**: Design documents from `/specs/018-auto-detect-propose-only/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md

**Tests**: No test tasks. This feature changes prose only, so there is nothing
to test. The existing suites serve as regression evidence for FR-013 and appear
as verification tasks in Phase 6, not as new tests.

**Organization**: Grouped by user story. Because every story edits the same
small set of prose files, `[P]` appears far less often here than in a code
feature. Two tasks are parallel only when they touch different files.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

No source tree is involved. All paths are prose files at repository root or
under `docs/` and `.specify/`. See plan.md "Files changed" for the full set.

---

## Phase 1: Setup (Baseline Capture)

**Purpose**: Record the before-state that SC-004 compares against. This must
happen before any file is edited, or the comparison is worthless.

- [ ] T001 Run `uv run pytest tests/ --ignore=tests/integration/ -q` and record the pass count in a scratch note; this is the FR-013 baseline
- [ ] T002 [P] Run `uv run ruff check .` and confirm zero errors before any edit
- [ ] T003 [P] Run an audit against a fixed sample project that has `maintainers` unset and save the output to `/tmp/018-audit-before.txt` for the SC-004 comparison

**Checkpoint**: Before-state captured. Editing can begin.

---

## Phase 2: Foundational (Canonical Wording)

**Purpose**: Fix the vocabulary once, before three stories write into the same
paragraphs. Skipping this is how SC-001 fails: if one story writes "candidate"
and another writes "suggestion", the amended documents disagree with each other
even though every individual edit looks correct.

**CRITICAL**: No story work can begin until T004 is done.

- [ ] T004 Draft the replacement text for Principle IV as one coherent block in a scratch file, using only the six terms fixed in `specs/018-auto-detect-propose-only/data-model.md` ("user-judgment key", "candidate", "confirmation", "propose", "conclude", "origin"), covering every clause required by FR-001 through FR-007 and FR-015

**Checkpoint**: One agreed block of normative text exists. Stories now place it.

---

## Phase 3: User Story 1 - Maintainer amends the governance rule (Priority: P1) -- MVP

**Goal**: The permission flip itself. After this phase the project's governing
documents permit proposing a candidate for a user-judgment key and forbid using
it unconfirmed.

**Independent Test**: Read the amended constitution and CLAUDE.md in isolation
and confirm that offering a candidate is permitted while accepting one without
human confirmation is forbidden. No code needs to exist.

### Implementation for User Story 1

- [ ] T005 [US1] Replace the absolute prohibition at `.specify/memory/constitution.md:102-103` ("the sieve MUST NOT run for that key. No exceptions.") with the propose-only rule from T004, satisfying FR-001
- [ ] T006 [US1] Replace `.specify/memory/constitution.md:106-107` ("Sieve auto-detection is acceptable ONLY for keys where `auto_detect = true`"), which is the sentence that actually forbids proposing, per FR-001
- [ ] T007 [P] [US1] Rewrite `CLAUDE.md:170` and `CLAUDE.md:172` to match the amended constitution exactly in substance, per FR-008
- [ ] T008 [P] [US1] Rewrite the normative restatement at `ARCHITECTURE.md:29` ("the sieve must not run for that key"), found during Phase 0 research and absent from the original spec; see research.md Finding 3
- [ ] T009 [US1] Bump the constitution version from 1.2.0 to 1.3.0 at `.specify/memory/constitution.md:186` and add a new Sync Impact Report block at the top recording the change, per FR-009
- [ ] T010 [US1] In the Sync Impact Report, justify MINOR by citing the 1.0.0 -> 1.1.0 precedent where this same principle was widened while its core requirement stayed intact, per FR-009
- [ ] T011 [P] [US1] Mark the Stage 0 row at `docs/rfcs/0001-core-rearchitecture.md:247` as satisfied and reference this PR, per FR-012

**Checkpoint**: The rule has changed. A reader of the constitution alone now
gets the right answer to "may darnit show me a detected maintainer list?"

---

## Phase 4: User Story 2 - Contributor implements against an unambiguous rule (Priority: P2)

**Goal**: The precision. After this phase the amended rule answers boundary
questions without guesswork, so no implementation can read the loosened rule as
permission to consume a candidate.

**Independent Test**: Give the amended rule and the five consumption paths from
data-model.md to two readers and ask which may consume an unconfirmed
candidate. Both answer "none" without consulting code.

**Note**: These tasks edit the same Principle IV block as US1, so none of them
are parallel with each other. This is the cost of the two stories sharing a
paragraph, and it is why T004 exists.

### Implementation for User Story 2

- [ ] T012 [US2] Add the FR-002 clause to `.specify/memory/constitution.md` Principle IV naming all five consumption paths explicitly (verification result, compliance calculation, remediation input, generated attestation, persisted context), so SC-003 can cite a sentence per path
- [ ] T013 [US2] Scope the existing confidence-threshold provision at `.specify/memory/constitution.md:108-113` to keys that do NOT require human judgment, closing the hole where it currently reads as unscoped, per FR-004
- [ ] T014 [US2] Add the FR-005 clause stating that human confirmation is the only transition that makes a value usable, and that storing a candidate does not constitute confirming it
- [ ] T015 [US2] Add the FR-006 clause requiring a confirmation to record when it was made, by whom, and what it was based on, and permitting expiry after a configurable period without naming the period
- [ ] T016 [US2] Verify the existing prohibition on guessed values in executable snippets survives the rewrite at `.specify/memory/constitution.md:114-115`, per FR-007; this clause must not be lost while its neighbours change
- [ ] T017 [US2] Add the FR-015 clause explaining that `auto_detect` gates concluding and `allow_sieve_hints` gates proposing, and that the safety property is enforced by the pair rather than by a ban on detection
- [ ] T018 [US2] Mirror T012 through T017 into the Conservative-by-Default section of `CLAUDE.md` at the level of detail appropriate to runtime guidance, keeping substance identical per FR-008

**Checkpoint**: The rule is now precise enough to implement against. US1 plus
US2 together are the complete governance change.

---

## Phase 5: User Story 3 - Reviewer confirms nothing regressed (Priority: P3)

**Goal**: Evidence that loosening the written rule did not loosen behavior, and
that no document anywhere still states the old rule.

**Independent Test**: Audit results identical before and after; no prose file
contains a statement that detection must not run for user-judgment keys.

### Implementation for User Story 3

- [ ] T019 [P] [US3] Extend `ARCHITECTURE.md:441` ("Values with `auto_detect = false` require explicit user confirmation") to mention that a candidate may be proposed, per FR-011
- [ ] T020 [P] [US3] Clarify the schema table entry at `docs/design/CONTEXT_PROMPTS.md:201` from "Whether value can be auto-detected" to language distinguishing concluding from proposing, per FR-011
- [ ] T021 [P] [US3] Add a sentence near the `auto_detect = false` example at `docs/IMPLEMENTATION_GUIDE.md:707` explaining what the flag now means, per FR-011
- [ ] T022 [US3] Confirm every entry in the research.md inventory carries a disposition of updated, deferred, or unaffected, with none left undetermined, per FR-010 and SC-005
- [ ] T023 [US3] Verify no file under `packages/` was modified (`git diff --name-only | grep packages/` returns nothing), enforcing the FR-011 deferral and the FR-013 boundary

**Checkpoint**: Documentation tree is internally consistent. Nothing in
`packages/` moved.

---

## Phase 6: Polish & Verification

**Purpose**: Prove the success criteria and get the change in front of the TSC.

- [ ] T024 Re-run `uv run pytest tests/ --ignore=tests/integration/ -q` and confirm the pass count matches the T001 baseline exactly; any test needing modification disproves FR-013
- [ ] T025 [P] Re-run `uv run ruff check .` and `uv run python scripts/validate_sync.py --verbose`, both must pass
- [ ] T026 [P] Re-run the T003 audit, diff against `/tmp/018-audit-before.txt`, and confirm no substantive difference, satisfying SC-004
- [ ] T027 [P] Grep all prose for surviving statements of the old rule (`grep -rn "must not run" --include="*.md" .`) and confirm only historical spec records under `specs/001-*` and `specs/003-*` remain, satisfying SC-002
- [ ] T028 [P] Confirm every file touched is ASCII-only per the project writing rule
- [ ] T029 Read the amended Principle IV cold and confirm a sentence can be cited for each of the five consumption paths, satisfying SC-003
- [ ] T030 Open the PR against `darnitdevorg/darnit` from the fork, describing the change as reconciling the constitution with shipped behavior (research.md Finding 1) rather than as loosening a safety rule
- [ ] T031 Start the GOVERNANCE.md comment period and request TSC review; the amendment cannot merge on a single approval

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies. Must complete before any edit, or SC-004 has no baseline.
- **Foundational (Phase 2)**: Depends on Setup. BLOCKS all stories.
- **User Story 1 (Phase 3)**: Depends on T004. Delivers the permission flip.
- **User Story 2 (Phase 4)**: Depends on US1, because it adds clauses to the block US1 places. Not independent in the usual sense; see note below.
- **User Story 3 (Phase 5)**: Depends on US1 for the canonical wording it propagates. Independent of US2.
- **Polish (Phase 6)**: Depends on all stories.

### A note on story independence

The template assumes stories are independently deliverable. Here US1 is, and
US2 is not: US2 writes clauses into the paragraph US1 replaces. Shipping US1
alone would be worse than shipping nothing, because it grants the permission
without the limits. Treat US1 + US2 as the atomic unit for merge; only US3 is
genuinely separable, and only in the sense that it could follow in a second PR.

### Parallel Opportunities

- T002 and T003 in Setup
- T007, T008, T011 in US1 (constitution, CLAUDE.md, ARCHITECTURE.md, RFC are four different files)
- T019, T020, T021 in US3 (three different files)
- T025, T026, T027, T028 in Polish
- Nothing in US2 is parallel; every task edits the same Principle IV block

---

## Parallel Example: User Story 1

```bash
# After T005 and T006 land the constitution text, these three are independent:
Task: "Rewrite CLAUDE.md:170,172 to match the amended constitution"
Task: "Rewrite the normative restatement at ARCHITECTURE.md:29"
Task: "Mark the Stage 0 row satisfied at docs/rfcs/0001-core-rearchitecture.md:247"
```

---

## Implementation Strategy

### Recommended: US1 + US2 as one PR

1. Phase 1 Setup, Phase 2 Foundational
2. Phase 3 (US1) and Phase 4 (US2) together
3. Phase 5 (US3) in the same PR if the diff stays readable
4. Phase 6 verification, then open the PR and start the comment period

RFC-0001 Stage 0 requires this land as its own PR, so the temptation to bundle
it with Stage 1 groundwork should be resisted (FR-012, SC-006).

### If the diff gets large

Split US3 into a follow-up PR. It touches only non-normative prose, so the
governing documents stay consistent either way. Do not split US1 from US2.

---

## Notes

- `packages/darnit/src/darnit/context/auto_detect.py` is a module about context
  detection generally, NOT the TOML flag. Several inventory hits are that
  module and must not be touched. This is the single most likely mistake.
- Historical spec records under `specs/001-tiered-control-automation/` and
  `specs/003-auto-context-inference/` state the old rule and are deliberately
  left alone. Rewriting them would misrepresent what was decided then.
- `docs/architecture/framework-design.md:838` already shows `auto_detect = false`
  alongside `allow_sieve_hints = true` and needs no change; it is the evidence
  that the design already went this way.
