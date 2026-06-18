---

description: "Task list for authoring the darnit Technical Steering Committee charter and roster."
---

# Tasks: Technical Steering Committee Charter

**Input**: Design documents from `/specs/015-tsc-charter/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md (all present)

**Tests**: Not requested. This feature ships Markdown only -- validation is done by running the data-model.md validation rules and the spec checklist against the authored files (bundled into Phase 6: Polish), not by a unit-test framework.

**Organization**: Tasks are grouped by user story so each story (US1, US2, US3) can be authored and validated independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks).
- **[Story]**: Maps the task to a user story from `spec.md`. Setup/Foundational/Polish phases carry no story label.
- All file paths are repository-root relative.

## Path Conventions

This feature is a documentation deliverable, not code. There is no `src/` or `tests/` tree. Files live at the **repository root** (`/Users/mlieberman/Projects/darnit/`): `CHARTER.md`, `TECHNICAL-STEERING-COMMITTEE.md`, `GOVERNANCE.md`, and a one-line edit to the existing `README.md`. The plan in `specs/015-tsc-charter/plan.md` documents this structure decision.

---

## Phase 1: Setup

**Purpose**: Confirm the branch is in the right state to author the three top-level governance files.

- [X] T001 Verify the current branch is `015-tsc-charter` and the working tree is clean (`git status` shows only the spec files already committed for this feature)
- [X] T002 Confirm no `CHARTER.md`, `TECHNICAL-STEERING-COMMITTEE.md`, or `GOVERNANCE.md` already exist at the repository root (`ls -la CHARTER.md TECHNICAL-STEERING-COMMITTEE.md GOVERNANCE.md`); if any exist, stop and reconcile rather than clobber
- [X] T003 [P] Open `https://github.com/gittuf/community/blob/main/CHARTER.md` (or equivalent local copy) to source the LF Projects Technical Charter section structure and language for adaptation in Phase 3

---

## Phase 2: Foundational

**Purpose**: One blocking decision the rest of the charter and roster reference.

**CRITICAL**: No user story work begins until this is done.

- [X] T004 Record the canonical adopted date as `2026-06-17` (ISO-8601), to be used consistently in `CHARTER.md` document metadata and the `TECHNICAL-STEERING-COMMITTEE.md` header comment

**Checkpoint**: Adopted date fixed; US1, US2, and US3 can now proceed (US1 and US2 in parallel; US3 follows US1).

---

## Phase 3: User Story 1 -- Published charter establishes governance authority (Priority: P1) [MVP]

**Goal**: Produce `CHARTER.md` at the repository root with the full LF Projects Technical Charter section structure (Sections 1-8) used by GUAC and gittuf, with all required content per FR-001, FR-003, FR-004, FR-007, FR-008, FR-009, FR-010, FR-013.

**Independent Test**: A reader unfamiliar with the project opens `CHARTER.md` and can answer, from that file alone: What is the TSC's scope? How are decisions made? How are votes recorded? Under what license is the document released? They do not need to consult external documents to find these answers (SC-001, SC-002).

### Implementation for User Story 1

- [X] T005 [US1] Create `/Users/mlieberman/Projects/darnit/CHARTER.md` with Section 1 (Mission and Scope of the Project): one paragraph naming darnit's mission (AI-assisted compliance auditing with a plugin architecture) and the TSC's scope of authority per FR-003 (technical direction, releases, security policy, sub-projects/working groups, foundation representation, charter amendments)
- [X] T006 [US1] Add Sections 2 (Technical Steering Committee) and 3 (TSC Voting) to `CHARTER.md`. Section 2: single-tier composition (per D1), pointer to `TECHNICAL-STEERING-COMMITTEE.md` for the live roster, chair clause (optional per D8); leave the *membership change* and *removal-for-cause* narrative as an explicit `<!-- US3: membership process -->` placeholder for tasks T010-T012. Section 3: full FR-004 voting thresholds (consensus-first; one vote per member; 50% quorum; simple majority of attendees with quorum for ordinary decisions; 2/3 of entire TSC for charter amendments and license exceptions) AND the FR-013 vote recording mechanism (GitHub PR approvals on the affected file are the canonical record; non-file decisions use a GitHub Issue/Discussion with explicit `+1`/`-1`/`+0` comments from TSC members)
- [X] T007 [US1] Add Sections 4 (Compliance with Policies), 5 (Community Assets), 6 (General Rules and Operations), 7 (Intellectual Property Policy), and 8 (Amendments) to `CHARTER.md`, adapting language verbatim from the LF Projects Technical Charter where possible. Section 4: name the project Code of Conduct, fall back to the LF Projects CoC if none exists yet (per D10 / FR-007), require DCO sign-off (per FR-008). Section 7: state the license stack -- code Apache-2.0, docs CC-BY-4.0, data CDLA-Permissive-2.0 (per FR-008). Section 8: amendment process with 2/3-of-entire-TSC threshold (per FR-010, referencing the threshold defined in Section 3)
- [X] T008 [US1] Add document metadata to `CHARTER.md`: an "Adopted: 2026-06-17" line, a provenance line ("Adapted from the LF Projects Technical Charter, also used by GUAC and gittuf"), and an explicit "This document is licensed under CC-BY-4.0." notice (per FR-009)

**Checkpoint**: `CHARTER.md` contains all 8 LF sections in order, with the membership process deliberately stubbed out for US3. Validation rule "all eight sections present in order" from `data-model.md` should already pass.

---

## Phase 4: User Story 2 -- Initial roster reflects industry + academia balance (Priority: P1)

**Goal**: Produce `TECHNICAL-STEERING-COMMITTEE.md` at the repository root with the row-per-member Markdown table format mirroring gittuf, populated with the two founding members.

**Independent Test**: A human or trivial script can parse the file's table and extract `(name, affiliation, category, github_handle)` for both members. The roster row for Michael Lieberman shows Kusari / industry / @mlieberman85; the row for Justin Cappos shows New York University / academia / @JustinCappos (SC-003).

### Implementation for User Story 2

- [X] T009 [P] [US2] Create `/Users/mlieberman/Projects/darnit/TECHNICAL-STEERING-COMMITTEE.md` exactly per the "Required document structure" block in `specs/015-tsc-charter/data-model.md`: H1 ("# Technical Steering Committee"), an HTML comment with `Adopted: 2026-06-17. License: CC-BY-4.0.`, an introductory sentence, the Markdown table with all five columns (`Name`, `Affiliation`, `Category`, `GitHub`, `Role`), the two founding-member rows (Michael Lieberman | Kusari | industry | @mlieberman85 | member; Justin Cappos | New York University | academia | @JustinCappos | member), and a closing sentence linking to `./CHARTER.md`

**Checkpoint**: Roster file is independently parseable; all four required columns populated for every row (data-model.md validation rule); SC-003 satisfied.

**Note**: T009 is parallelizable with all of Phase 3 -- it touches a different file from `CHARTER.md`.

---

## Phase 5: User Story 3 -- Membership changes have a documented, auditable process (Priority: P2)

**Goal**: Replace the `<!-- US3: membership process -->` placeholder in `CHARTER.md` Section 2 with the full membership-change and removal-for-cause narrative, satisfying FR-005, FR-006, FR-011.

**Independent Test**: A maintainer reading `CHARTER.md` Section 2 alone can write a PR that adds or removes a TSC member and point to the exact section text that authorizes the change and defines the approval threshold.

### Implementation for User Story 3

- [X] T010 [US3] In `/Users/mlieberman/Projects/darnit/CHARTER.md` Section 2, replace the `<!-- US3: membership process -->` placeholder with the membership-addition process: a candidate is nominated by an existing TSC member via a PR that adds a row to `TECHNICAL-STEERING-COMMITTEE.md`; existing TSC members vote by approving (or declining) the PR; approval requires a majority of existing TSC members; the merge commit is the canonical record per FR-013
- [X] T011 [US3] In the same Section 2, add the removal process: voluntary resignation is a PR removing the member's row (no vote required, acknowledgment by another TSC member suffices). Removal-for-cause requires a majority of the *other* current TSC members -- the member under review does not vote on their own removal (per FR-006). Explicitly state that "inactivity" is NOT defined by a fixed numeric threshold; it is a discretionary judgment by the remaining TSC members, initiated via a public issue or PR and resolved by the removal-for-cause threshold above
- [X] T012 [US3] In the same Section 2, add a brief acknowledgement of the two-member-TSC concentration risk: while the TSC has only two voting members, "majority of the other members" arithmetically means a majority of one, so a remaining member alone can effect a removal. This is a known transitional posture and the project intends to recruit a third member promptly. Reference the corresponding edge case in `specs/015-tsc-charter/spec.md` is NOT required (the charter must stand on its own), but the *substance* of the edge case MUST appear in the charter text

**Checkpoint**: `CHARTER.md` is now content-complete. The spec checklist item "All functional requirements have clear acceptance criteria" should be re-verifiable end-to-end.

---

## Phase 6: Polish & Cross-Cutting

**Purpose**: Add the discoverability layer (GOVERNANCE.md, README link), then validate the deliverable against the spec checklist, the data-model validation rules, and the constitution's Development Workflow gates.

- [X] T013 [P] Merge with pre-existing `/Users/mlieberman/Projects/darnit/GOVERNANCE.md` (committed 2026-01-15 in commit `64dd2f2`) rather than create a new file. **Reconciliation chosen interactively during implementation**: the existing maintainer-only decision-making model was reframed as the operational layer *below* the TSC charter -- top of document points to `CHARTER.md` and `TECHNICAL-STEERING-COMMITTEE.md` for binding governance rules; existing Project Structure, Roles and Responsibilities, Day-to-Day PR Process, Release Process, Code of Conduct, and Contact sections preserved with light edits noting that TSC authority sits above maintainer authority. Note: the data-model.md "<=30 lines" target was deliberately exceeded -- the merged document is ~70 lines because it had to retain pre-existing content; this is a deliberate deviation from the plan, not a defect.
- [X] T014 [P] Edit `/Users/mlieberman/Projects/darnit/README.md` to add a one-line "Governance" link pointing to `./GOVERNANCE.md`, placed near the top or in an existing "Project Info" / "Community" section (whichever exists); this satisfies the "linked from the README" alternative in FR-012
- [X] T015 Run the data-model.md validation rules against the three new files: (a) `CHARTER.md` contains all 8 LF sections in order (`grep -nE "^## " CHARTER.md`); (b) `grep -n "NEEDS CLARIFICATION" CHARTER.md TECHNICAL-STEERING-COMMITTEE.md GOVERNANCE.md` returns nothing; (c) every roster row has all four required columns populated; (d) every `GitHub` cell matches `@[A-Za-z0-9-]+`; (e) at most one row carries `Role = chair`; (f) `CHARTER.md` contains the string `CC-BY-4.0`; (g) cross-document invariant -- neither founding member's GitHub handle appears in `CHARTER.md` (only in the roster), so a future roster change requires editing one file
- [X] T016 Re-run the spec quality checklist at `specs/015-tsc-charter/checklists/requirements.md` against the authored files; confirm every item still passes (especially "Requirements are testable and unambiguous", "Success criteria are measurable", "No implementation details leak into specification")
- [X] T017 Walk through `specs/015-tsc-charter/quickstart.md` "Sanity check before submitting any governance PR" against the PR diff, before opening the PR
- [X] T018 Run the constitution's Development Workflow gates: `uv run ruff check .` (no-op on Markdown but must still pass), `uv run pytest tests/ --ignore=tests/integration/ -q` (unchanged behavior; must pass), `uv run python scripts/validate_sync.py --verbose` (this feature does not touch the framework-design spec, so sync should remain valid)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies; start immediately.
- **Foundational (Phase 2)**: Depends on Setup. Blocks all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational. Authors `CHARTER.md` skeleton + Sections 3-8.
- **User Story 2 (Phase 4)**: Depends on Foundational. Authors `TECHNICAL-STEERING-COMMITTEE.md`. **Independent of US1** (different file).
- **User Story 3 (Phase 5)**: Depends on US1 (T006 creates the placeholder T010-T012 replace).
- **Polish (Phase 6)**: T013 and T014 can start anytime after Foundational (T013 doesn't depend on any other file's contents; T014 is a separate file). T015-T018 (validation) depend on all of US1, US2, US3 being complete.

### User Story Dependencies

- **US1 (P1)**: Depends only on Foundational.
- **US2 (P1)**: Depends only on Foundational. Parallelizable with US1.
- **US3 (P2)**: Depends on US1 (specifically T006). Cannot start until T006 is done.

### Within Each User Story

- US1 is a sequential edit chain (all tasks touch the same file): T005 -> T006 -> T007 -> T008.
- US2 is a single task (T009).
- US3 is a sequential edit chain (all tasks touch the same file): T010 -> T011 -> T012.

### Parallel Opportunities

- **T003** (read reference template) [P] vs T001/T002 -- read-only, no file conflict.
- **T009** (US2, roster file) [P] vs all of US1 (T005-T008) -- different file.
- **T013** (GOVERNANCE.md) [P] vs T014 (README.md edit) -- different files; both can start once Foundational is done.
- US3 (T010-T012) cannot start in parallel with US1 because they edit the same file.

---

## Parallel Example: After Foundational Completes

```bash
# Start US1 (sequential, in one editor session):
T005 -> T006 -> T007 -> T008 -> CHARTER.md complete (with US3 placeholder)

# In parallel (different files), can start at the same time as US1:
T009  # author TECHNICAL-STEERING-COMMITTEE.md
T013  # author GOVERNANCE.md
T014  # edit README.md

# After US1 (T006 specifically) completes, start US3:
T010 -> T011 -> T012 -> CHARTER.md fully content-complete

# After everything above, run validation:
T015 -> T016 -> T017 -> T018
```

---

## Implementation Strategy

### MVP First (US1 + US2)

Both US1 and US2 are P1; the MVP is **both files** authored. Once T005-T009 are done, the project has a published charter and a published roster -- even without US3's membership-process narrative, the LF template plus a roster file is the minimum coherent governance artifact.

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (T004).
3. Complete Phase 3 (US1, T005-T008) and Phase 4 (US2, T009) -- parallelize if working with two people; otherwise interleave by file.
4. **STOP and VALIDATE**: the two files exist, are internally consistent, and meet SC-001 / SC-002 / SC-003. If urgent (e.g., a foundation review tomorrow), this is shippable as v1.0 with US3 content as a follow-on PR.

### Incremental Delivery

1. Setup + Foundational -> ready to author.
2. US1 + US2 -> MVP charter + roster ship.
3. US3 -> membership-process narrative ships, completing FR-005 / FR-006.
4. Polish -> GOVERNANCE.md, README link, and final validation ship.

### Single-Author Strategy (default for "real quick")

One person, one editor session, in order: T001-T018 sequentially. The full set takes one focused session.

---

## Notes

- All tasks edit files **at the repository root**, not under `specs/015-tsc-charter/`. Spec-directory files (spec.md, plan.md, research.md, data-model.md, quickstart.md, tasks.md, checklists/) are *inputs*, not outputs of this task list.
- The single-author strategy is the intended default (matches the user's original "real quick" framing).
- No new runtime code, no new tests, no new CI. The constitution's Development Workflow gates (T018) must still pass because they run on every PR.
- Commit cadence: one commit per phase is reasonable; alternatively one commit per task for finer audit trail. The PR opening this branch is the one that records the TSC's first PR-as-vote-record on its own charter (a quietly recursive moment).
