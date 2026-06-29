---

description: "Task list for the openspec removal / migration feature."
---

# Tasks: Remove openspec, Migrate Work to Speckit

**Input**: Design documents from `/specs/016-openspec-migration/`

**Prerequisites**: spec.md, plan.md, research.md, data-model.md, quickstart.md (all present)

**Tests**: No new test files. This feature is a tree refactor; verification happens via the constitution's existing Workflow gates (`ruff`, `pytest`, the trimmed `validate_sync.py`) plus the spec's success-criteria `find` / `grep` checks. Both are bundled into the Polish phase.

**Organization**: This feature's user stories are *testable end-state properties*, not vertical work slices. Phase order is therefore **topological** (driven by file-dependency, not by spec priority). Specifically: US4 (P2 -- rehome architectural specs) is executed in Phase 2 Foundational because US3 (P1 -- constitutional reference resolves) requires the new `docs/architecture/framework-design.md` path to exist before the constitution can reference it. The `[Story]` labels on tasks still reflect the user story each task primarily serves; the phase ordering is just sequenced for correctness.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks).
- **[Story]**: Maps the task to a user story from `spec.md`. Setup/Polish phases carry no story label.
- All file paths are repository-root relative.

## Path Conventions

This feature is an in-repository refactor. There is no new package or `src/`/`tests/` tree. All work happens against existing paths under the repository root (`/Users/mlieberman/Projects/darnit/`). Heavy use of `git mv` is intentional to preserve history -- see `research.md` D8.

---

## Phase 1: Setup

**Purpose**: Confirm the starting state is well-defined before mutating anything.

- [X] T001 Confirm the working tree is on branch `016-openspec-migration` and clean of unrelated changes: `git status --short` shows only files this feature is expected to touch
- [X] T002 Confirm pre-removal `validate_sync.py` passes: `uv run python scripts/validate_sync.py --verbose` exits 0. If it fails, fix the underlying issue first so later "did I break it?" diagnostics are clean
- [X] T003 Confirm pre-removal tests pass: `uv run pytest tests/ --ignore=tests/integration/ -q` exits 0
- [X] T004 Inspect `docs/generated/` if present: `ls docs/generated/` (per research D4 pre-check). If anything looks hand-written rather than `generate_docs.py` output, stop and surface in code review before proceeding

**Checkpoint**: Baseline established. Proceed to rehoming.

---

## Phase 2: Foundational -- Rehome Architectural Specs [US4]

**Purpose**: Move the 26 architectural specs to their new home. Required first because US3 (constitutional reference) and the trimmed `validate_sync.py` (Phase 4) both depend on `docs/architecture/framework-design.md` existing at its new path.

**Goal**: 26 rehomed files + 1 index live under `docs/architecture/`; the source openspec/specs subdirectories are emptied (the openspec top-level directory still exists at this checkpoint and gets deleted in Phase 4).

**Independent Test**: `ls docs/architecture/*.md | wc -l` returns 27 (26 specs + README.md); `git log --follow docs/architecture/framework-design.md` traces back through `openspec/specs/framework-design/spec.md`.

- [X] T005 [US4] Create `docs/architecture/` directory: `mkdir -p docs/architecture`
- [X] T006 [US4] Execute the 26 `git mv` operations per `data-model.md` Entity 1 table, mapping each `openspec/specs/<topic>/spec.md` to `docs/architecture/<topic>.md`. After each `git mv`, run `rmdir "openspec/specs/<topic>"` to clean the now-empty source directory. Topics: `framework-design`, `audit-pipeline`, `audit-context-collection`, `cel-expressions`, `ci-workflow-templates`, `conditional-controls`, `context-collection`, `context-documentation`, `control-dependencies`, `declarative-file-templates`, `dot-project-integration`, `example-plugin`, `external-templates`, `framework-agnostic-reporting`, `github-api-remediation`, `handler-pipeline`, `implementation-provided-tools`, `org-project-resolution`, `plugin-registry`, `policy-doc-templates`, `remediation-audit-filtering`, `remediation-manual-guidance`, `repo-identity-resolution`, `shared-handlers`, `sieve-handler-authoring`
- [X] T007 [US4] Rewrite internal Markdown links in the rehomed files: for each file in `docs/architecture/*.md`, change occurrences of `](../<topic>/spec.md)` to `](./<topic>.md)` and any prose mention of `openspec/specs/` to `docs/architecture/`. After this task, `grep -rln "openspec/" docs/architecture/` MUST return empty
- [X] T008 [US4] Write `docs/architecture/README.md` using the schema in `data-model.md` Entity 1 ("README.md schema"): H1 "Architecture Documentation", intro paragraph, and grouped bullet lists linking to all 26 rehomed files. Aim for ~one screen; this is an index, not a tutorial

**Checkpoint**: 27 files exist under `docs/architecture/`. US4 acceptance scenarios can be checked. `docs/architecture/framework-design.md` exists -- the path the constitution will reference in Phase 5.

---

## Phase 3: Migrate the Active Proposal [US2]

**Purpose**: Move the one in-flight openspec proposal to a normal speckit feature directory so the work isn't lost. Independent of Phase 2 -- different source files, different target files. Can be done in parallel with Phase 2 if working with multiple committers.

**Goal**: `specs/017-org-wide-audit-pipeline/` exists as a normal speckit feature with `spec.md`, `plan.md`, `tasks.md`.

**Independent Test**: `ls specs/017-org-wide-audit-pipeline/{spec,plan,tasks}.md` succeeds; the first 10 lines of `spec.md` show the speckit header injected by T010.

- [X] T009 [P] [US2] Create the target directory and perform the file renames preserving history. `mkdir -p specs/017-org-wide-audit-pipeline`; then `git mv openspec/changes/org-wide-audit-pipeline/proposal.md specs/017-org-wide-audit-pipeline/spec.md`; `git mv openspec/changes/org-wide-audit-pipeline/design.md specs/017-org-wide-audit-pipeline/plan.md`; `git mv openspec/changes/org-wide-audit-pipeline/tasks.md specs/017-org-wide-audit-pipeline/tasks.md`; `git rm openspec/changes/org-wide-audit-pipeline/.openspec.yaml`; `rmdir openspec/changes/org-wide-audit-pipeline`
- [X] T010 [US2] Edit `specs/017-org-wide-audit-pipeline/spec.md` to prepend the speckit spec header per `data-model.md` Entity 2 ("Header injection"). Preserve the original proposal body verbatim below the header; do not rewrite or restructure the proposal content in this PR. Also confirm the body's content count: `wc -l spec.md` should be >= the original `proposal.md` line count (header added, body preserved)

**Checkpoint**: US2 acceptance scenarios pass; `specs/017-org-wide-audit-pipeline/` is a normal speckit feature ready for future `/speckit-plan` / `/speckit-tasks` invocations.

---

## Phase 4: Removal + Reference Rewrites [US1]

**Purpose**: Delete the openspec directory and all artifacts it produced; rewrite every in-tree reference to point at the new locations; trim the validation script. This is the bulk of US1.

**Goal**: `openspec/` is gone; `generate_docs.py` is gone; `docs/generated/` is gone; every documentation, code, and config reference points at `docs/architecture/` or no longer mentions the removed scripts.

**Independent Test**: `find . -type d -name openspec -not -path "*/.git/*"` empty; `grep -rln openspec --exclude-dir=.git --exclude-dir=specs --exclude=CHANGELOG.md .` empty; `uv run python scripts/validate_sync.py --verbose` exits 0 with three checks reported.

### Deletions

- [X] T011 [US1] Delete the openspec directory: `git rm -r openspec/`. At this point T005-T010 are done so nothing of value lives there. After this, `find . -type d -name openspec -not -path "*/.git/*"` returns empty
- [X] T012 [US1] Delete the generate-docs script: `git rm scripts/generate_docs.py`
- [X] T013 [US1] Delete the generated docs directory if present: `git rm -r docs/generated/ 2>/dev/null || true` (T004 verified nothing hand-written is in there). If T004 surfaced a concern, that gets resolved before this task runs

### Script trim

- [X] T014 [US1] Trim `scripts/validate_sync.py` per `data-model.md` Entity 5: (a) change `SPEC_PATH` from `PROJECT_ROOT / "openspec" / "specs" / "framework-design" / "spec.md"` to `PROJECT_ROOT / "docs" / "architecture" / "framework-design.md"`; (b) delete the `validate_spec_exists()` function definition and any call sites that invoke it in the main entrypoint's validator list; (c) delete the `validate_docs_freshness()` function definition and its call sites; (d) update the module docstring to enumerate exactly three checks (TOML Schema valid, Pass Types Sync, SARIF Source); (e) if a `--changed-files` flag has docs-freshness branching, remove it. Verify: `uv run python scripts/validate_sync.py --verbose` exits 0 and output mentions only three check categories

### Config + template + code references

- [X] T015 [US1] Edit `.pre-commit-config.yaml`: change the validate_sync hook's `files:` regex from `^(packages/darnit/|openspec/specs/framework-design/)` to `^(packages/darnit/|docs/architecture/framework-design\.md)`
- [X] T016 [US1] Edit `.github/pull_request_template.md`: change the framework-spec checkbox row from `Updated framework spec (\`openspec/specs/framework-design/spec.md\`)` to `Updated framework spec (\`docs/architecture/framework-design.md\`)`
- [X] T017 [US1] Edit `packages/darnit-baseline/src/darnit_baseline/remediation/scanner.py`: remove the `"openspec"` string from the `_PRUNE_DIRS` set (line ~211). Leave the surrounding entries (`"specs"`, `".specify"`, `"node_modules"`, etc.) untouched

### Documentation references (parallelizable -- different files)

- [X] T018 [P] [US1] Edit `ARCHITECTURE.md`: drop the `openspec/` entry from the project-tree diagram (line ~132); update the "Authoritative framework specification" row (line ~535) to cite `docs/architecture/framework-design.md`
- [X] T019 [P] [US1] Edit `CLAUDE.md`: rewrite the 5 openspec references (lines ~186, ~225, ~229, ~241, ~244 in the pre-removal file). Where the line mentions `validate_sync.py`, keep the command but adjust narrative to reflect the narrower scope. Where the line mentions `generate_docs.py`, remove the command entirely (and any neighbouring `docs/generated/` instructions)
- [X] T020 [P] [US1] Edit `docs/IMPLEMENTATION_GUIDE.md`: rewrite both openspec references (lines ~817, ~1825) to `docs/architecture/framework-design.md`
- [X] T021 [P] [US1] Edit `docs/getting-started/troubleshooting.md`: rewrite both openspec references (lines ~53, ~60) to point at `docs/architecture/framework-design.md`. The troubleshooting context (validate_sync failures) is still valid; only the path changes
- [X] T022 [P] [US1] Edit `docs/getting-started/development-workflow.md`: rewrite the single openspec reference (line ~133) -- "Edit `openspec/specs/framework-design/spec.md`" becomes "Edit `docs/architecture/framework-design.md`"
- [X] T023 [P] [US1] Edit `docs/getting-started/framework-development.md`: rewrite both openspec references (lines ~168, ~216) to the new path
- [X] T024 [P] [US1] Edit `packaging/README.md`: drop the `uv run python scripts/generate_docs.py` line (line ~82); keep the `validate_sync.py` line (line ~81) since the script survives

**Checkpoint**: `grep -rln openspec --exclude-dir=.git --exclude-dir=specs --exclude=CHANGELOG.md .` returns empty. SC-002 satisfied. US1 acceptance scenarios pass.

---

## Phase 5: Amend the Constitution [US3]

**Purpose**: Update the constitution to (a) cite the new framework-design path, (b) reflect the new Development Workflow gate list, and (c) bump the version per the documented Governance procedure.

**Goal**: Constitution is internally consistent post-amendment; every path it cites resolves; every Workflow gate it lists exits zero on a clean checkout.

**Independent Test**: `grep -n openspec .specify/memory/constitution.md` empty; `grep "1.2.0" .specify/memory/constitution.md` returns a match; every command in the Validation Commands code block can be run.

- [X] T025 [US3] Amend `.specify/memory/constitution.md` per the edit table in `data-model.md` Entity 4. Edits in order: (1) version header `1.1.0 -> 1.2.0`; (2) last-amended date `2026-03-08 -> 2026-06-21`; (3) prepend a Sync Impact Report block describing the 1.1.0->1.2.0 bump (modeled on the existing block at top); (4) Spec-Implementation Synchronization section -- swap the `openspec/...` path for `docs/architecture/framework-design.md`; (5) Development Workflow item 3 -- rewrite to enumerate the 3 surviving checks; (6) Development Workflow item 4 (Generated docs) -- delete entirely; renumber subsequent items if any follow; (7) Sync Enforcement Rules item 2 -- swap the spec-path reference; (8) Sync Enforcement Rules item 3 (Generated Docs Must Stay Fresh) -- delete entirely; (9) CI Enforces Sync block -- delete the "Generated docs would change" bullet; (10) Validation Commands code block -- remove the `generate_docs.py` and `git diff docs/generated/` lines

**Checkpoint**: US3 acceptance scenarios pass. Reading the constitution top to bottom yields a coherent document with no dangling references.

---

## Phase 6: Polish & Verification

**Purpose**: Add the CHANGELOG entry, run every gate the post-amendment constitution lists, run the spec's success-criteria checks, and confirm the PR is ready.

- [X] T026 Create `CHANGELOG.md` at the repository root using the schema in `data-model.md` Entity 3. Include the `[Unreleased]` section with Removed / Added / Changed sub-sections enumerating this feature's changes, plus the downstream-integrator callout block
- [X] T027 Run the post-amendment Constitution Development Workflow gates and confirm zero exits: `uv run ruff check .`; `uv run pytest tests/ --ignore=tests/integration/ -q`; `uv run python scripts/validate_sync.py --verbose` (this is now the *trimmed* script -- output should mention exactly 3 checks). Capture each command's tail in the PR description for reviewer reference
- [X] T028 Run the spec success-criteria checks: `find . -type d -name openspec -not -path "*/.git/*"` (SC-001: empty); `grep -rln openspec --exclude-dir=.git --exclude-dir=specs --exclude=CHANGELOG.md .` (SC-002: empty); `ls docs/architecture/*.md | wc -l` (SC-005: 27); `ls specs/017-org-wide-audit-pipeline/{spec,plan,tasks}.md` (SC-004: 3 files); read CLAUDE.md + ARCHITECTURE.md + the constitution and confirm only speckit referenced (SC-006). Any failure means a step was missed -- do NOT proceed to PR
- [X] T029 Run pre-commit on the full tree: `pre-commit run --all-files`. The validate_sync hook should fire on `docs/architecture/framework-design.md` if it changed and on `packages/darnit/` changes. No hook failures
- [X] T030 Walk the quickstart's "Sanity check before opening PR" list. Confirm: single PR contains all of Phase 1-6; `git log --follow docs/architecture/framework-design.md` traces back into `openspec/specs/framework-design/spec.md`; PR description names the new framework-design path; PR description includes the downstream-integrator notice; pre-commit passes; SC-002 grep is clean

**Checkpoint**: Feature is complete. PR is ready to open.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)** -- no dependencies; start immediately.
- **Foundational (Phase 2) [US4]** -- depends on Setup. Blocks Phase 4 (validate_sync.py trim needs the new path) and Phase 5 (constitution references the new path).
- **Active Proposal (Phase 3) [US2]** -- depends on Setup. Independent of Phase 2; can be done in parallel.
- **Removal + References (Phase 4) [US1]** -- depends on Phase 2 (new path must exist for validate_sync.py to point at it) and Phase 3 (so the active proposal isn't lost when openspec/ is deleted).
- **Constitution (Phase 5) [US3]** -- depends on Phase 2 (path exists) and Phase 4 (script trim done, so the constitution's narrative about the script's scope matches reality).
- **Polish (Phase 6)** -- depends on all prior phases.

### User Story Dependencies

- **US4 (rehome)** -- executed first because US3 and parts of US1 (script trim) depend on the new path existing. P2 by spec, executed in Foundational position for correctness.
- **US2 (migrate active proposal)** -- independent of US4; runs parallel.
- **US1 (one spec system)** -- depends on US4 (so the references can be rewritten to point at the new home).
- **US3 (constitution reference resolves)** -- depends on US4 (new path) + US1 (sync pipeline trimmed before the constitution describes the trimmed gate list).

### Parallel Opportunities

- T009 [P] (Phase 3 setup) parallel with T005-T008 (Phase 2).
- Inside Phase 4: T018-T024 [P] (different doc files) can all run in parallel. T011-T013 (deletions) can run in any order vs each other. T014-T017 (script + config + code edits) target different files and can also be parallelized, though T014 requires T006 done (it references the new path).
- Polish T028 (SC checks) doesn't strictly depend on T027 (Workflow gates) -- but practically they're run sequentially to inspect output.

---

## Parallel Example: After Phase 1 Completes

```bash
# Phase 2 (foundational) starts the heavy lifting:
T005 -> T006 -> T007 -> T008    # rehome architectural specs (sequential -- same target dir)

# In parallel (different source/target paths):
T009 -> T010                     # migrate active proposal

# After Phase 2 + Phase 3 complete:
T011, T012, T013                 # parallel deletions
T014                             # script trim (needs T006 done)
T015, T016, T017                 # config + template + code (different files)
T018, T019, T020, T021, T022, T023, T024   # all [P] -- different doc files

# Then sequentially:
T025                             # constitution amendment
T026                             # CHANGELOG creation

# Verification (sequential for inspection):
T027 -> T028 -> T029 -> T030
```

---

## Implementation Strategy

### Single-Author Strategy (default)

One person, one editor session, in order: T001 -> T030 sequentially. Phase 2 (T006) is the biggest single block of mechanical work (26 git mv invocations). The full set takes one focused session of ~2-3 hours including verification.

### Two-Author Strategy (if pairing)

After Phase 1, fork:

- Author A: T005-T008 (rehome -- Phase 2)
- Author B: T009-T010 (migrate active proposal -- Phase 3)

Merge points before Phase 4 begins. After Phase 4's deletions (T011-T013) and script trim (T014) are done sequentially, the doc-reference updates (T018-T024) can fan out to either author since they touch different files.

### Cannot Be Phased

This feature is explicitly a single-PR delivery (FR-014 / SC-007). The phases above are within-PR sequencing, not multi-PR phasing. Splitting Phase 4 across multiple PRs would leave the constitution citing missing paths between merges -- the bifurcation this feature exists to resolve.

---

## Notes

- All `git mv` operations preserve history; `git log --follow docs/architecture/<topic>.md` traces back into `openspec/specs/<topic>/spec.md` after the merge.
- The default commit-boundary suggestion in `quickstart.md` is one commit per phase. Squash-merge at PR time per the project's standard convention.
- The 26 architectural spec rehomes are mechanically uniform -- if the implementation agent is comfortable batch-scripting them (e.g., with a small bash loop over the topic list in `data-model.md`), T006 collapses to a few lines of shell rather than 26 individual invocations. The data-model.md table is the source of truth for the topic list.
- `docs/generated/` may not exist on this branch (depends on whether anyone has run `generate_docs.py` recently). T013's `2>/dev/null || true` handles either case.
- The "constitutional amendment" framing in Phase 5 is real, not ceremonial. The constitution's own Governance section anticipates exactly this kind of edit and prescribes the version-bump + Sync Impact Report block that T025 produces. Treating it as more than a doc edit keeps the change auditable.
