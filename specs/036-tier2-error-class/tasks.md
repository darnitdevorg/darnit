---

description: "Task breakdown for feature 036 (distinguishable side-effect failures via error_class)"
---

# Tasks: Distinguishable Side-Effect Failures via `error_class`

**Input**: Design documents from `/specs/036-tier2-error-class/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/error-class.md](contracts/error-class.md), [quickstart.md](quickstart.md)

**Tests**: Tests ARE included. SC-001..SC-007 are all test-verified, and [contracts/error-class.md](contracts/error-class.md) section 9 maps each guarantee to a test module. Test tasks are explicit and, where a guarantee is subtle (CEL preservation), written BEFORE the implementation that satisfies them.

**Organization**: Grouped by user story (US1..US4). Phase 2 (Foundational) carries the type definition, the three field additions, and the CEL-preservation fix -- all four user stories depend on it.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1..US4 from spec.md
- Exact file paths included in every task

## Path Conventions

- Framework code: `packages/darnit/src/darnit/`
- Implementation code: `packages/darnit-baseline/src/darnit_baseline/`
- Framework tests: `tests/darnit/`
- Implementation tests: `tests/darnit_baseline/`

---

## Phase 1: Setup

**Purpose**: Verify preconditions. No new dependencies, no scaffolding.

- [X] T001 Verify the precedent and exception surfaces this feature builds on are importable: `uv run python -c "from darnit.core.authority import Authority; from darnit.sieve.mcp_pool import McpToolTimeout, McpServerHandshakeFailed, McpServerBinaryMissing, McpServerVerificationFailed, McpServerUnusable, McpToolError, McpToolResponseNotJson, McpPoolError; print('ok')"`. All eight MCP exception types must resolve (research.md R-007 maps all eight). If any import fails, halt and reconcile the mapping table in `contracts/error-class.md` section 2.2 against the actual module.

- [X] T001a Capture the pre-feature output baseline BEFORE any code change. On the current `main` (or the merge-base), run an audit against the all-deterministic fixture repo and save the markdown, JSON, and SARIF outputs to `tests/darnit/fixtures/error_class_baseline/` as `baseline.md`, `baseline.json`, `baseline.sarif`. Commit them in their own commit before Phase 2 starts. T027 verifies post-feature output against THESE files. Without this step SC-002 is unfalsifiable -- any golden generated during implementation locks post-feature behavior rather than proving pre-feature equivalence.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The type, the three field additions, and the CEL-preservation fix. Every user story depends on all of these.

**CRITICAL**: No user-story work can begin until this phase is complete.

- [X] T002 Create `packages/darnit/src/darnit/core/error_class.py` defining `ErrorClass = Literal["network", "auth", "timeout", "rate_limit", "not_found", "crashed"]` AND a runtime-checkable `_ERROR_CLASSES: frozenset[ErrorClass] = frozenset((...))` containing the same six values (per FR-002a -- `typing.Literal` has no runtime effect, so the frozenset is what makes validation possible). Mirror the structure of `packages/darnit/src/darnit/core/authority.py`, which pairs its `Authority` Literal with `_TERMINAL_AUTHORITIES: frozenset[Authority]` for the same reason. Module docstring explains the semantic (every value means "the check could not run to completion", none means "ran and the repo does not comply") and notes the deliberate divergence from `authority.py`: that module uses its frozenset for a fail-safe, this one uses it for rejection, because an unknown `error_class` has no safe default. Include the per-value meaning table from `contracts/error-class.md` section 1 as docstring content. Export both names in `__all__`.

- [X] T003 Add `error_class: ErrorClass | None = None` as the LAST field on `HandlerResult` in `packages/darnit/src/darnit/sieve/handler_registry.py` (currently ends at `authority: Authority | None = None`, ~line 81). Extend the class docstring's Attributes block. Add a `__post_init__` enforcing BOTH validation rules from `contracts/error-class.md` section 6: (1) raise `ValueError` when `error_class` is not None and not in `_ERROR_CLASSES` (FR-002a -- unknown-value rejection); (2) raise `ValueError` when `error_class is not None and status == HandlerResultStatus.PASS` (the unrepresentable-shape constraint). Both must be enforced in code, not just documented.

- [X] T004 Add `error_class: ErrorClass | None = None` to the `SieveResult` dataclass in `packages/darnit/src/darnit/sieve/models.py` (place it adjacent to the existing resolving-pass metadata fields). Import `ErrorClass` from `darnit.core.error_class`.

- [X] T005 Add `error_class: NotRequired[str]` to the `CheckResult` TypedDict in `packages/darnit/src/darnit/sieve/models.py`, immediately after the existing `authority: NotRequired[str]` field (~line 152), with a comment mirroring authority's explaining the additive/back-compat rationale. Then update `SieveResult.to_legacy_dict()` to conditionally emit the key only when `self.error_class is not None` -- matching exactly how `authority` is emitted there. Typed as `str` (not `ErrorClass`) because the TypedDict is the deserialization boundary; see data-model.md E-004.

- [X] T006 Create `tests/darnit/sieve/test_error_class_cel_preservation.py` with a test class parameterized over all four `_apply_cel_expr` transitions that construct a new `HandlerResult` (PASS+CEL-true, PASS+CEL-false, FAIL+CEL-true, FAIL+CEL-false per `contracts/error-class.md` section 4). Each case: build an input `HandlerResult` carrying `error_class="timeout"`, run it through `_apply_cel_expr`, assert the output still carries `error_class == "timeout"`. Also cover the two pass-through paths (no `expr` configured; handler returned ERROR/INCONCLUSIVE) which return the same object and are trivially safe. **These tests MUST FAIL before T007.** This is the SC-005 guarantee and the failure mode is silent field-dropping, not an exception -- hence test-first.

- [X] T007 Thread `error_class` through every `HandlerResult(...)` construction site inside `_apply_cel_expr` in `packages/darnit/src/darnit/sieve/orchestrator.py` (~lines 88-180). Feature 026 hit this identical bug with `authority` and fixed it the same way -- follow the existing `authority=handler_result.authority` pattern at each constructor call. Makes T006 pass. Consider (but do NOT bundle) the `dataclasses.replace()` refactor noted in research.md R-003's alternatives -- larger blast radius than this feature warrants.

- [X] T008 In `packages/darnit/src/darnit/sieve/orchestrator.py`, populate `SieveResult.error_class` from the RESOLVING pass's `HandlerResult.error_class` at the same place `resolving_pass_index` and `resolving_pass_handler` are already set. Per FR-009a / clarify Q1: resolving pass only; earlier non-resolving passes' values are discarded, not aggregated (the `pass_history` field already carries the per-pass trail).

**Checkpoint**: `uv run pytest tests/darnit/sieve/test_error_class_cel_preservation.py -v` passes. Full suite still green (`uv run pytest tests/darnit/ tests/darnit_baseline/ --ignore=tests/darnit/parity -q`) -- the field additions are additive and should break nothing.

---

## Phase 3: User Story 1 - Operator sees "network failed" separately from "check failed" (Priority: P1) MVP

**Goal**: An operator running an audit with an expired token can tell from the markdown report alone which controls failed due to auth vs which failed against a working environment.

**Independent Test**: Run the audit driver with `gh api` mocked to return 401. Confirm the markdown report annotates affected controls with their `error_class` and leaves genuinely-failing controls unannotated.

### Tests for User Story 1

- [X] T009 [US1] Create `tests/darnit/sieve/test_error_class_classification.py` with a `TestExecHandlerClassification` class covering the full decision table from `contracts/error-class.md` section 2.1: `subprocess.TimeoutExpired` -> `timeout`; non-zero exit with `API rate limit exceeded` in stderr -> `rate_limit`; non-zero exit with `Bad credentials` in stderr -> `auth`; non-zero exit with unmatched stderr -> `network`; exit in `pass_exit_codes` -> `error_class is None`; exit in `fail_exit_codes` -> `error_class is None` (the check ran, the repo doesn't comply). Include a rate-limit-precedence case: stderr containing BOTH a 403 and `secondary rate limit` must classify as `rate_limit`, not `auth`.

- [X] T010 [P] [US1] Add a `TestHandlerResultValidation` class to `tests/darnit/sieve/test_error_class_classification.py` covering both `__post_init__` rules from T003: (1) `HandlerResult(status=HandlerResultStatus.PASS, message="x", error_class="crashed")` MUST raise `ValueError` (unrepresentable shape); (2) `HandlerResult(status=HandlerResultStatus.ERROR, message="x", error_class="bogus_value")` MUST raise `ValueError` (FR-002a unknown-value rejection -- this is the test that proves the frozenset guard actually runs, since the `Literal` annotation alone would silently accept it); (3) each of the six valid values constructs successfully with a non-PASS status.

### Implementation for User Story 1

- [X] T011 [US1] Add `_GH_RATE_LIMIT_PATTERNS` and `_GH_AUTH_PATTERNS` module-level constants to `packages/darnit/src/darnit/sieve/builtin_handlers.py`, adjacent to the existing `MCP_DEFAULT_TIMEOUT_SECONDS` constant. Contents per data-model.md E-005. Case-insensitive substring matching against the exec handler's captured stderr (already truncated to 500 chars by the existing evidence shape). GitHub-only for v0 per clarify Q4.

- [X] T012 [US1] Add a `_classify_exec_failure(exit_code, stderr, timed_out)` helper to `packages/darnit/src/darnit/sieve/builtin_handlers.py` returning `ErrorClass | None`, implementing the section-2.1 decision table with rate-limit checked BEFORE auth. Wire it into `exec_handler`'s failure paths: the `subprocess.TimeoutExpired` catch (~line 242) and the non-zero-exit branch (~line 272-290). Do NOT set `error_class` on the `pass_exit_codes` success path or the `fail_exit_codes` clean-failure path.

- [X] T013 [US1] Surface `error_class` in the markdown formatter at `packages/darnit/src/darnit/tools/audit.py` (~lines 918-931, the block that already conditionally renders "Resolved by:" and "Pass history:"). Add a conditional line when `error_class` is present. Per FR-010 the exact rendering is refinable; the requirement is that it's visually distinguishable from the verdict. Suggested shape matching quickstart.md: append `[<error_class>]` to the status token, e.g. `x OSPS-LE-02.02: FAIL [auth] - Command failed (exit 1)`.

- [X] T014 [US1] Add a driver-level integration test to `tests/darnit/sieve/test_error_class_classification.py` (class `TestDriverLevelErrorClassSurfacing`): run `run_sieve_audit` with a mocked orchestrator whose exec pass returns a 401-shaped failure, format the results as markdown via the `tools/audit.py` formatter, and assert the affected control's line carries the `error_class` annotation while a cleanly-failing control's line does not. Locks SC-001.

**Checkpoint**: US1 complete. An operator with a broken token can triage the audit correctly from the markdown report.

---

## Phase 4: User Story 2 - Environmental failures land in default log output at WARN (Priority: P1)

**Goal**: Environmental failures log at WARN (not DEBUG) so the default log level surfaces a degraded audit without the operator needing to know to bump verbosity.

**Independent Test**: Run an audit at default log level with some side-effect handlers forced to fail. Confirm stderr carries WARN lines naming the control, the handler, and the `error_class`.

### Tests for User Story 2

- [X] T015 [US2] Add a `TestWarnLoggingAtFourSites` class to `tests/darnit/sieve/test_error_class_classification.py` using `caplog` at WARN level. Four cases, one per classification site (`contracts/error-class.md` section 7): exec handler timeout, MCP handler exception, orchestrator crash-catch, context auto-detect git failure. Each asserts a WARN record exists whose message names the control ID (or context key, for auto-detect), the handler, and the `error_class` value.

- [X] T016 [P] [US2] Create `tests/darnit/test_error_class_happy_path.py` with a `TestNoWarnOnHappyPath` class: run an audit against a fixture repo where every control resolves via deterministic local-only handlers (no network), with `caplog` at WARN. Assert ZERO WARN records originate from this feature's log sites. Locks the FR-014 "silent in the happy path" half of the guarantee that matters for log noise.

### Implementation for User Story 2

- [X] T017 [US2] Bump the exec handler's environmental-failure log lines from DEBUG to WARN in `packages/darnit/src/darnit/sieve/builtin_handlers.py`. Log line must name the control ID (available as `context.control_id`), the handler name, and the `error_class`. Leave happy-path logging (successful invocations, JSON-parse debug) at DEBUG.

- [X] T018 [US2] Add MCP exception classification to `mcp_handler` in `packages/darnit/src/darnit/sieve/builtin_handlers.py` (~lines 1025-1093 area). Implement the full eight-way mapping from `contracts/error-class.md` section 2.2 -- the three named explicitly in FR-006 plus the five the FR's final clause delegates to the contract (`McpServerVerificationFailed` -> `auth`, `McpServerUnusable` -> `network`, `McpToolError` -> `crashed`, `McpToolResponseNotJson` -> `crashed`, `McpPoolError` base -> `crashed`). Bump the corresponding log lines to WARN. FR-006 now makes the contract's table normative, so all eight are in scope.

- [X] T019 [US2] In `packages/darnit/src/darnit/sieve/orchestrator.py`, the outer `try/except Exception` around handler invocation (~lines 410-422) must construct its `HandlerResult` with `error_class="crashed"` and log at WARN (currently DEBUG). The log line must name the control ID, the handler, and the exception type.

- [X] T020 [US2] In `packages/darnit/src/darnit/context/auto_detect.py`, `detect_platform`'s git-subprocess failure path (~lines 516-529) must log at WARN (currently silently swallowed) naming the context key and the classified `error_class` (timeout -> `timeout`, otherwise `network`). Per `contracts/error-class.md` section 2.4 this is a log-line field only -- auto-detect produces context values, not `HandlerResult`s, so no new context-value shape is introduced.

**Checkpoint**: US2 complete. A degraded audit is visible at default log level.

---

## Phase 5: User Story 3 - JSON and SARIF outputs machine-consume `error_class` (Priority: P2)

**Goal**: Downstream tools (dashboards, CI classifiers, ticketing integrations) can branch on `error_class` from the machine-readable outputs.

**Independent Test**: Run an audit producing at least one environmental failure; parse the JSON and SARIF outputs and confirm `error_class` is present at the documented location and absent for cleanly-failing controls.

### Tests for User Story 3

- [X] T021 [US3] Create `tests/darnit_baseline/test_error_class_output_surfaces.py` with a `TestJsonFormatter` class: assert `error_class` appears as a top-level key at the same nesting depth as `status` in BOTH the full JSON shape and the summary JSON shape (per research.md R-006 -- a summary that hides "we couldn't verify" defeats the feature). Assert the key is ABSENT (not `null`, not `""`) for results without an `error_class`, per FR-011.

- [X] T022 [P] [US3] Add a `TestSarifFormatter` class to `tests/darnit_baseline/test_error_class_output_surfaces.py`: assert `sarif_result["properties"]["errorClass"]` carries the value when present and the key is absent otherwise. camelCase matches the file's existing convention (`resolvingPassHandler`, `resolvingPassIndex`, `passHistory`).

### Implementation for User Story 3

- [X] T023 [US3] Emit `error_class` in the JSON formatter at `packages/darnit-baseline/src/darnit_baseline/tools.py` (~lines 206-238). Both shapes: the full JSON serialization (~line 228-238) and the summary shape (~line 206-227). Conditional emit -- `if r.get("error_class") is not None`.

- [X] T024 [US3] Emit `error_class` as `properties["errorClass"]` in `packages/darnit-baseline/src/darnit_baseline/formatters/sarif.py` (~lines 383-391), following the existing `if X is not None: sarif_result["properties"][camelKey] = X` pattern used for the three pass-transparency fields already there.

**Checkpoint**: US3 complete. Machine consumers can split environment problems from repo problems.

---

## Phase 6: User Story 4 - Attestation predicate carries `error_class` when present (Priority: P2)

**Goal**: A signed attestation records when a control's verdict was produced under a degraded environment, so a later verifier isn't misled by a bare verdict.

**Independent Test**: Generate an attestation from an audit run that had at least one environmental failure; parse the predicate and confirm the affected control's entry carries `error_class`.

### Tests for User Story 4

- [X] T025 [US4] Add a `TestAttestationPredicate` class to `tests/darnit_baseline/test_error_class_output_surfaces.py`: build a predicate from a results list where one control carries `error_class="network"`; assert that control's predicate entry has `"error_class": "network"` at the same schema depth as `status`. Assert a control without an `error_class` produces a predicate entry with NO `error_class` key (attestation shape unchanged in the happy path, per US4 acceptance scenario 2).

### Implementation for User Story 4

- [X] T026 [US4] Add conditional `error_class` emit to `packages/darnit-baseline/src/darnit_baseline/attestation/predicate.py`, immediately after the existing `authority` block (~lines 96-101), using the identical pattern: `if r.get("error_class") is not None: control["error_class"] = r["error_class"]`. Additive within the v1 predicate schema -- **no version bump** (research.md R-005 confirms feature 025 set this precedent for `authority`). Add a comment naming this feature and the additive rationale, mirroring the RFC-0001 comment above it.

**Checkpoint**: US4 complete. Attestations no longer make bare claims about degraded audits.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T027 Add a `TestHappyPathByteForByteInvariance` class to `tests/darnit/test_error_class_happy_path.py`: run an audit against the same all-deterministic fixture repo T001a used, and assert the markdown, JSON, and SARIF outputs match `tests/darnit/fixtures/error_class_baseline/{baseline.md,baseline.json,baseline.sarif}` byte-for-byte. Use plain file comparison -- explicitly NOT `syrupy` snapshots, because `--snapshot-update` would let a real regression be absorbed into the expected value, which defeats SC-002's purpose. Locks SC-002, the strongest safeguard against accidental happy-path drift.

- [X] T028 [P] Add a `TestNoNewRuntimeDependency` assertion to `tests/darnit/test_error_class_happy_path.py`: grep the four touched framework source files for third-party imports and assert the set is unchanged from the pre-feature baseline (stdlib `typing`, `re`, `os`, `subprocess`, `tempfile` only). Locks SC-007 / FR-015.

- [X] T029 Run `uv run pytest tests/darnit/ tests/darnit_baseline/ --ignore=tests/darnit/parity -q` and confirm the full suite passes. Expected new tests: T006, T009, T010, T014, T015, T016, T021, T022, T025, T027, T028. All pre-existing tests MUST pass unchanged -- the field additions are additive and the emit sites are all conditionally guarded.

- [X] T030 [P] Run `uv run ruff check` and `uv run ruff format` on ONLY this feature's touched files (not repo-wide -- a repo-wide `ruff format` reformats ~230 unrelated files with accumulated drift; learned during feature 035). Touched files: `core/error_class.py`, `sieve/handler_registry.py`, `sieve/models.py`, `sieve/builtin_handlers.py`, `sieve/orchestrator.py`, `context/auto_detect.py`, `tools/audit.py`, `darnit-baseline/tools.py`, `formatters/sarif.py`, `attestation/predicate.py`, plus the four new test modules.

- [X] T031 Run `uv run python scripts/validate_sync.py --verbose` to confirm the spec-implementation sync check passes (CI enforces this per CLAUDE.md's Development Workflow item 3).

- [X] T032 Walk through [quickstart.md](quickstart.md) Example 1 manually: create a temp git repo, run `GH_TOKEN=invalid_token_value darnit audit <repo> -t level=1`, and confirm (a) the markdown shows `[auth]` on the GitHub-dependent controls, (b) WARN lines appear at default log level, (c) a control that fails on local-file evidence has NO annotation. Verifies the operator-facing story outside pytest fixtures.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: no dependencies. **T001a is a HARD gate on Phase 2** -- it must run against unmodified `main` code, so it cannot be deferred until after any Phase 2 task lands.
- **Phase 2 (Foundational)**: depends on Phase 1 (including T001a). **BLOCKS all user stories.**
  - Internal order: T002 -> T003 -> T004 -> T005 (each needs the prior's type/field; T003's `__post_init__` needs T002's frozenset). Then T006 (test, must fail) -> T007 (makes it pass). T008 depends on T004.
  - T003, T004, T005 all touch different files except T004/T005 which share `sieve/models.py` (sequential).
- **Phase 3 (US1)**: depends on Phase 2. T009/T010 (tests) before T011-T013 (impl). T014 depends on T013.
- **Phase 4 (US2)**: depends on Phase 2. Also depends on T012 from US1 (the `_classify_exec_failure` helper) -- T017 bumps the log level at the site T012 created.
- **Phase 5 (US3)**: depends on Phase 2 only (needs `CheckResult["error_class"]` to exist). Independent of US1/US2.
- **Phase 6 (US4)**: depends on Phase 2 only. Independent of US1/US2/US3.
- **Phase 7 (Polish)**: depends on all desired user stories.

### User Story Dependencies

- **US1 (P1)**: no cross-story dependencies.
- **US2 (P1)**: soft dependency on US1's T012 (`_classify_exec_failure` helper). If US2 is implemented first, T012 moves into US2's phase.
- **US3 (P2)**: fully independent after Phase 2.
- **US4 (P2)**: fully independent after Phase 2.

### Within Each User Story

- Tests before implementation where the guarantee is subtle (T006 before T007 is mandatory -- silent field-dropping).
- Framework changes before implementation-package changes (US3/US4 read a field the framework must already produce).

### Parallel Opportunities

- **T010** is [P] with T009 (both add classes to the same new file, but T010 has no dependency on T009's content -- if implemented by one agent, do them together).
- **T016** is [P] with T015 (different files: `test_error_class_happy_path.py` vs `test_error_class_classification.py`).
- **T022** is [P] with T021 (same file, independent classes -- see note above).
- **T028** is [P] with T027 (same file, independent classes).
- **T030** is [P] with T031 and T032 (lint vs sync-check vs manual walkthrough).
- **US3 and US4 can be worked entirely in parallel** with each other and with US1/US2, once Phase 2 lands. They touch only `darnit-baseline` files plus one shared new test module.

---

## Parallel Example: US3 + US4 after Phase 2

```bash
# Both stories touch only darnit-baseline; no overlap with US1/US2 files.
Task: "T023 JSON formatter emits error_class in darnit-baseline/tools.py"
Task: "T024 SARIF formatter emits properties.errorClass in formatters/sarif.py"
Task: "T026 Attestation predicate conditional emit in attestation/predicate.py"
```

---

## Implementation Strategy

### MVP first (US1 only)

1. Phase 1 (Setup) -- one verification command.
2. Phase 2 (Foundational) -- the type, three field additions, CEL fix. This is the bulk of the risk; T006/T007 is the subtle part.
3. Phase 3 (US1) -- exec classification + markdown surfacing.
4. **STOP and VALIDATE**: run quickstart Example 1 with an invalid token. If the markdown distinguishes auth failures from real findings, the MVP delivers.
5. Open PR draft.

### Incremental delivery

- US2 next (WARN logging) -- turns a report-only improvement into an operator-noticing-immediately improvement.
- US3 + US4 in parallel -- machine surfaces. Both small and independent.
- Phase 7 closes the PR.

### Solo strategy

Straight-through top to bottom. Estimated 4-6 hours including the manual quickstart validation. Phase 2's T006/T007 pair deserves the most care -- the CEL preservation bug is silent, and it's the same bug feature 026 already hit once.

---

## Notes

- [P] tasks: different files or independent classes in the same file, no dependencies on incomplete tasks.
- [Story] label maps each task to US1..US4 for traceability against spec.md.
- Every user story is independently completable and testable after Phase 2.
- Recommended commit boundaries: after Phase 2 (foundation), then one commit per user story phase, then one for Phase 7.
- **Do not bundle** the `dataclasses.replace()` refactor of `_apply_cel_expr` (research.md R-003 alternatives) -- it's the right long-term fix for the field-dropping bug class but a larger blast radius than this feature. File as a follow-up.
- Per CLAUDE.md: no speculative refactors bundled with fixes; no comments explaining WHAT well-named code does.
