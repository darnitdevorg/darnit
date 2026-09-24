---

description: "Task list for feature 039: Wire detect_filter Into Context Detection"
---

# Tasks: Wire detect_filter Into Context Detection

**Input**: Design documents from `/specs/039-wire-detect-filter/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: included. SC-001 through SC-009 each name a fixture, and contracts/detect-filter.md carries 11 numbered obligations.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 (placeholder rejected), US2 (broken filter visible), US3 (undeclared key caught)
- Paths are repository-relative from `/Users/mlieberman/Projects/darnit`

**One decision the plan did not settle: T012.** `get_context_value` and `load_context` take only a path and a key; neither can resolve which filter applies. FR-014 requires re-evaluation on read anyway. Decide it deliberately before writing the read path, because the obvious shape fails open.

---

## Phase 1: Setup

- [X] T001 Declare `detect_filter: str | None = None` on `ContextDefinitionConfig` in `packages/darnit/src/darnit/config/framework_schema.py`, with a comment stating that the candidate binds as `value` and that true keeps. The model keeps `extra="allow"`; FR-010 is a CI check, not a schema change.
- [X] T002 [P] Add a test to `tests/darnit/config/test_context_schema.py` asserting the shipped `security_contact` definition in `openssf-baseline.toml` parses with `detect_filter` populated as a declared field rather than landing in `model_extra`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the evaluation module every story depends on.

- [X] T003 Create `packages/darnit/src/darnit/context/detect_filter.py` with a `FilterDecision` enum (`KEEP`, `REJECT`, `UNEVALUABLE`) and a module docstring recording why `REJECT` and `UNEVALUABLE` are distinct: one says the filter judged the value, the other says it could not, and collapsing them reproduces the defect this feature fixes.
- [X] T004 Implement scalar evaluation in `detect_filter.py` using `evaluate_cel(expression, {"value": candidate})` from `darnit/sieve/cel_evaluator.py`. Pass a plain dict rather than a `CELContext` -- that type is shared with the control sieve, where `value` would be meaningless (research.md R1).
- [X] T005 Handle both failure paths in `detect_filter.py` (research.md R3): a malformed expression RAISES `CELCompilationError` out of `evaluate_cel`, while a wrong-typed value or missing binding RETURNS `CELResult(success=False)`. Checking only `result.success` lets a bad expression crash context collection; catching only the exception misses type errors. Both map to `UNEVALUABLE`.
- [X] T006 Compile once per key rather than once per element in `detect_filter.py`, so a malformed expression is reported once naming the key instead of once per list element.
- [X] T007 Implement element-wise evaluation for list candidates in `detect_filter.py` (FR-012): evaluate per element, keep the passers, report the discarded count (FR-013). Never bind a list whole -- see T008 for why.
- [X] T008 [P] Write `tests/darnit/context/test_detect_filter.py` covering contract obligations DF-1 through DF-6. DF-4 is the load-bearing one: assert that a list containing a rejected element is not kept. CEL's `contains` on a list is membership rather than substring, so `["a@example.com"].contains("example.com")` is false and the negated filter returns true -- binding a list whole silently KEEPS the value the filter exists to reject (research.md R2).

**Checkpoint**: a value and an expression produce a decision. Stories can begin.

---

## Phase 3: User Story 1 - A placeholder address is not adopted as the security contact (Priority: P1)

**Goal**: the filter actually runs, on both detection routes, before anything is stored.

**Independent test**: a repo whose `SECURITY.md` contains only `security@example.com`. Run context collection. Nothing is stored for `security_contact`.

**Depends on**: Phase 2.

- [X] T009 [US1] Apply the filter at the single choke point in `packages/darnit/src/darnit/config/context_storage.py:547-557`, after both detection routes converge on `current_value` and before the auto-accept threshold is consulted (FR-004, FR-005). One call site covers the `detect` pipeline and the sieve fallback; filtering inside each route separately is two places to keep in step and the fallback is the one that gets forgotten.
- [X] T010 [US1] Resolve the key's `detect_filter` from the already-loaded framework definition at that call site in `context_storage.py` -- the definition is in scope there, unlike on the read path.
- [X] T011 [P] [US1] Add tests to `tests/darnit/config/test_context_storage.py` for DF-7 and DF-8: a rejected candidate from the `detect` pipeline and one from the sieve fallback are each neither stored nor auto-accepted, asserted at confidence 1.0 so the test fails if filtering moves after the threshold check.
- [X] T012 [P] [US1] Add a test to `tests/darnit/config/test_context_storage.py` asserting a real security contact is still stored, with the stored value byte-identical to today (SC-003).

**Checkpoint**: #165 and #150's reported case is fixed for repositories audited from now on.

---

## Phase 4: User Story 2 - A filter that cannot run is visible rather than silent (Priority: P1)

**Goal**: replacing a silent no-op with a different silent no-op would repeat the bug.

**Independent test**: define a context key with a malformed `detect_filter`. Run detection. The failure is reported and names the key.

**Depends on**: Phase 2. Independent of US1 -- different concern, same module.

- [X] T013 [US2] Report rejections and unevaluable filters in `context_storage.py` at a level visible in default output, naming the context key and, for unevaluable, the expression (FR-007).
- [X] T014 [US2] Distinguish "the filter rejected this" from "detection found nothing" in the reported message in `packages/darnit/src/darnit/config/context_storage.py` (FR-008), so an operator can tell why a key is unset.
- [X] T015 [US2] Include the discarded-element count alongside surviving elements for list-valued keys in `packages/darnit/src/darnit/config/context_storage.py` (FR-013), so a maintainer list arriving shorter than the evidence suggests is explicable.
- [X] T016 [P] [US2] Add tests to `tests/darnit/config/test_context_storage.py` asserting a malformed expression is reported, names the key, and does not propagate out of context collection (DF-5).
- [X] T017 [P] [US2] Add a test to `tests/darnit/config/test_context_storage.py` asserting the three outcomes produce distinguishable messages: rejected, unevaluable, and nothing detected.

**Checkpoint**: a guard that cannot run says so.

---

## Phase 5: The Read Path (FR-014, FR-015)

**Purpose**: repositories audited before this fix. Separated from US1 because it is a different code path with a design question of its own, and because without it the feature protects only repositories that have never been audited.

- [X] T018 Decide how the read path resolves a key's filter, and record the decision in `research.md`. `get_context_value(local_path, key, category)` and `load_context(local_path)` in `context_storage.py` take no framework, and the three product callers are `context_storage.py:226`, `context_storage.py:242`, and `remediation/context_validator.py:81` -- the last being remediation input, which FR-014 names explicitly. Options: (a) optional parameter defaulting to no filtering, (b) resolve the framework config inside the read path, (c) re-check one layer up where the framework is known. **Prefer (b) or (c) over (a): an optional parameter that defaults to not filtering means a fourth caller silently skips the guard, which is this feature's own defect class.**
- [X] T019 Implement re-evaluation on read per T018 in `packages/darnit/src/darnit/config/context_storage.py`, treating a failing stored value as unset for control verification, compliance calculation and remediation input (FR-014).
- [X] T020 Ensure the read path in `packages/darnit/src/darnit/config/context_storage.py` never writes (FR-015). A stored value may carry a human confirmation, and Principle IV does not let the framework silently revoke one.
- [X] T021 Add a test to `tests/darnit/config/test_context_storage.py` for DF-9: a stored value that now fails its filter reads as unset, and the `.project/` file is byte-identical afterwards.
- [X] T022 [P] Add a test asserting `remediation/context_validator.py` does not receive a filtered-out value as remediation input.
- [X] T023 [P] Add a test asserting existing `get_context_value` behaviour for keys with no filter is unchanged -- `tests/darnit/config/test_context_storage.py` already exercises `has_releases`, which has no filter and must keep passing untouched.

**Checkpoint**: the population most affected by the bug is covered on their next audit.

---

## Phase 6: User Story 3 - An undeclared context key is caught, not accepted in silence (Priority: P2)

**Goal**: the recurrence guard. `detect_filter` and `value_if_fail` were the same defect found by two unrelated bug reports.

**Independent test**: add an undeclared key to a `[context.*]` block in a shipped TOML. Validation fails naming the key.

**Depends on**: T001, so `detect_filter` is declared and the current TOMLs pass.

- [X] T024 [US3] Add a `validate_context_keys()` check to `scripts/validate_sync.py` that reads every shipped framework TOML, and fails when a `[context.*]` block contains a key not declared as a field on `ContextDefinitionConfig`, naming the key and the file (FR-010).
- [X] T025 [US3] Register the new check in `run_validations()` in `scripts/validate_sync.py` alongside the existing three.
- [X] T026 [P] [US3] Write `tests/darnit/config/test_validate_context_keys.py` for DF-11: the check fails on a TOML with an undeclared `[context.*]` key and passes on the currently shipped TOMLs.
- [X] T027 [US3] Run `uv run python scripts/validate_sync.py --verbose` and confirm it passes with `detect_filter` now declared. It would have failed before T001, which is the point.

**Checkpoint**: the next unwired key is a CI failure rather than a bug report.

---

## Phase 7: Polish and Cross-Cutting Concerns

- [X] T028 Verify SC-007 via `tests/darnit/config/test_context_storage.py` by comparing stored context before and after the change for a repository whose context keys declare no filter -- byte-identical.
- [X] T029 Confirm SC-009: every edge case in spec.md has a test, including the empty list, the boolean-valued key, and a filter declared on a key with no detection configured.
- [X] T030 [P] Run the quickstart walkthrough end to end: a repo with a template `SECURITY.md` stores nothing for `security_contact`, and the same repo with a real address stores it.
- [X] T031 [P] Update the `detect_filter` comment in `packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml:302` -- it currently reads "Filter: reject detected values containing ..." which was aspirational; make it describe behaviour that now exists.
- [ ] T032 File a follow-up issue for the remaining `extra="allow"` exposure on `ContextDefinitionConfig` (`packages/darnit/src/darnit/config/framework_schema.py`): the CI check covers shipped TOMLs only, so a third-party plugin's misspelled context key still loads silently. Tightening the schema is a behaviour change for plugin authors and was deliberately kept out of this feature.
- [X] T033 Run the full gate: `uv run ruff check .`, `uv run pytest tests/ --ignore=tests/integration/ --ignore=tests/darnit/parity/tier2 -q`, `uv run python scripts/validate_sync.py --verbose`.
- [X] T034 Run `uv run ruff format` on touched files only. A repository-wide format run reformats hundreds of unrelated files.

---

## Dependencies

```text
Phase 1 (T001-T002)
    |
Phase 2 (T003-T008)          <- the evaluation module
    |
    +-- Phase 3 / US1 (T009-T012)   ---> shippable MVP
    +-- Phase 4 / US2 (T013-T017)   <- independent of US1
    |
    +-- Phase 5 read path (T018-T023)   <- needs US1's filter application
    |
Phase 6 / US3 (T024-T027)    <- needs T001 only; can run any time after Phase 1
    |
Phase 7 (T028-T034)
```

US1 and US2 are independent of each other. US3 needs only T001 and can run alongside anything. Phase 5 needs US1, because it reuses the filter application US1 builds.

## Parallel Opportunities

- **US3 alongside everything.** It touches `scripts/validate_sync.py` and a new test file; no overlap with the context code.
- **US1 and US2 together.** Both extend `context_storage.py`, so the implementation tasks (T009, T010, T013-T015) should not be edited concurrently, but their test tasks are independent.
- **Test authoring.** T008, T011, T012, T016, T017, T022, T023, T026 are independent of each other.
- **Not parallel**: T003 through T007 all edit `detect_filter.py`; T009, T010, T013, T014, T015, T019, T020 all edit `context_storage.py`.

## Implementation Strategy

**MVP = Phases 1, 2 and 3.** That closes #165 and #150 for repositories audited from now on, with no read-path change and no CI check. It is a clean stopping point.

**Phase 5 is what makes the fix reach existing users.** Without it, the repositories holding a bad `security_contact` -- the ones audited while the guard was off -- keep it forever. T018 is a real decision, not a formality: the obvious shape (an optional parameter defaulting to no filtering) fails open in exactly the way this feature exists to fix.

**Phase 6 is the part that stops a third instance.** The check is a dozen lines and would have caught both known cases.

---

## Implementation Notes

Recorded during `/speckit-implement`.

- **T001 was half a task as written.** Issue #165 named two models and the task named one. `context_schema.ContextDefinition` also lacked `detect_filter`, and the read path reads that one, so wiring FR-014 required declaring it there too and mapping it across in `get_context_definitions`.
- **There were TWO conversion sites, and fixing one was not enough.** `get_context_definitions` and `get_context_definitions_with_detect` each build a `ContextDefinition` from the framework config. The collection loop uses the second. Having fixed only the first, the filter silently did not fire during real collection -- `security@example.com` was still saved and auto-accepted at confidence 1.0, and only the read path caught it. The tasks warned about exactly this hazard for the two detection routes; it turned out to apply to the two conversion sites instead.
- **T030 is what caught it.** Every unit test passed with the bug present, because they call `_apply_detect_filter` directly or patch the detection routes. Only the end-to-end walkthrough exercised the path where the definition is built. A feature whose whole subject is "a guard that was never wired up" needed a test that runs the real wiring.
- **The new CI check found a third instance immediately.** `presentation_hint` is used on seven context keys in `openssf-baseline.toml` and was not a declared field on `ContextDefinitionConfig`. It is read in ~28 places, so it looked live -- but the TOML value never reaches the definition either, because neither conversion site maps it. It is harmless only because `computed_presentation_hint` independently derives an identical string. Declared as part of this feature so validation is honest; the redundant TOML values are left alone, since changing prompt text is outside this feature's scope.
- **One existing test used the placeholder as sample data.** `test_save_security_contact` saved `security@example.com` and asserted it read back. Under FR-014 it now reads as unset, which is correct. The fixture was changed to a real-looking address and carries a note explaining why, so it does not get changed back.
- **T032 is left open.** It files an issue, which is outward-facing and needs approval first.
