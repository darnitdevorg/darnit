---

description: "Task list for feature 022: type AuditState.audit_results"
---

# Tasks: Type AuditState.audit_results

**Input**: Design documents from `/specs/022-type-audit-results/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/check-result.md](contracts/check-result.md), [quickstart.md](quickstart.md)

**Tests**: Not requested. The change is runtime-invariant and its acceptance is a static check (SC-001, SC-002). One negative-verification step (deliberate typo -> mypy flags -> revert) is executed by hand during implementation, not codified as a pytest test (see `research.md` R7).

**Organization**: One user story (US1). Phase 1 captures the mypy baseline so we can prove "zero NEW errors" at the end. Phase 2 (Foundational) is empty. Phase 3 (US1) has three sequential impl tasks (types first, then producer, then consumer -- same-file/same-symbol dependencies preclude parallelism). Phase 4 (Verification) runs the static + runtime + lint gates. No polish phase.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the mypy baseline so the "zero NEW errors" acceptance in SC-001 has a documented number to compare against.

- [X] T001 Record the baseline mypy error count from `main` (or the current tree, whichever is faster to check) by running: `uv run mypy packages/darnit/src/darnit/agent/state.py packages/darnit/src/darnit/agent/graph.py packages/darnit/src/darnit/sieve/models.py packages/darnit/src/darnit/tools/audit.py packages/darnit/src/darnit/cli.py 2>&1 | tail -30`. Save the exact output as a comment for the PR description. Confirmed baseline (measured 2026-08-04, **19 errors total**): `agent/graph.py` 4 errors (`arg-type` at lines 74/75, missing return annotation at 318, `attr-defined` at 321); `sieve/models.py` 1 error (missing return annotation at 171); `tools/audit.py` 10 errors (missing return annotation at 28; 2x `no-any-return` at 181/199; 1x `no-untyped-call` at 350; 6x `dict-item` at 1124-1141); `cli.py` 4 errors (3x `var-annotated` at 83/297/376; 1x `no-any-return` at 1088). None related to `audit_results`. No file changes.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: None. This feature is a single-slice type-annotation refactor; there are no framework-level scaffolding tasks. Proceed directly to Phase 3.

---

## Phase 3: User Story 1 - Typed audit results across the agent boundary (Priority: P1) MVP

**Goal**: `AuditState.audit_results` is `list[CheckResult]`, where `CheckResult` is a `TypedDict` defined in `sieve/models.py`. `SieveResult.to_legacy_dict()` is annotated as returning `CheckResult`. `AuditState` helpers use typed access. Zero new mypy errors on the touched files; runtime unchanged.

**Independent Test**: `uv run mypy packages/darnit/src/darnit/agent/state.py packages/darnit/src/darnit/agent/graph.py packages/darnit/src/darnit/sieve/models.py packages/darnit/src/darnit/tools/audit.py packages/darnit/src/darnit/cli.py` produces the same-or-fewer error count as T001's baseline, with zero errors mentioning `audit_results`. `uv run pytest tests/ --ignore=tests/integration/ -m "not slow" -q` shows the same pass/fail counts as `main`.

### Implementation for User Story 1

Tasks in this section are sequential -- each depends on the symbol the previous one introduces or annotates. No `[P]` markers.

- [X] T002 [US1] Add `CheckStatus`, `PassHistoryResult`, `PassHistoryEntry`, and `CheckResult` to `packages/darnit/src/darnit/sieve/models.py`. Import `Literal`, `NotRequired`, `TypedDict` from `typing`. Place the new declarations just below the existing `PassAttempt` / above `SieveResult` (or wherever ordering satisfies the forward references -- `PassHistoryResult` must be defined before `PassHistoryEntry`, which must be defined before `CheckResult`). Copy the exact field lists from `data-model.md` verbatim (`id`, `status`, `details`, `level` required; the eight optional keys via `NotRequired`). Add a short docstring on `CheckResult` pointing at `sieve/models.py:111` (`to_legacy_dict`) as the primary producer and `tools/audit.py:492` as the sparse producer. Do NOT re-export from `__init__.py`; consumers import from `darnit.sieve.models` directly.

- [X] T003 [US1] Annotate `SieveResult.to_legacy_dict()` at `packages/darnit/src/darnit/sieve/models.py:111` to return `CheckResult` instead of `dict[str, Any]`. Do NOT change the method body. Verify by running `uv run mypy packages/darnit/src/darnit/sieve/models.py` -- expected outcome: the existing line-171 error is unchanged and no new errors appear for the annotation swap. If mypy complains that the returned literal dict does not match `CheckResult` (e.g., because it wants a `TypedDict` constructor call), wrap the initial `result = {...}` in `result: CheckResult = {...}` to give the checker the type context. Do NOT change any key names or values.

- [X] T004 [US1] Update `packages/darnit/src/darnit/agent/state.py`: (a) add `from darnit.sieve.models import CheckResult` at the top-of-file imports (framework-internal edge; does not cross plugin boundary per Rule 1). (b) Change `audit_results: list[dict[str, Any]] = field(default_factory=list)` at line 61 to `audit_results: list[CheckResult] = field(default_factory=list)`. (c) Update the docstring at line 43 from "Raw result dicts from the latest audit run." to "Typed check results (CheckResult) from the latest audit run.". (d) Leave `remediation_results: list[dict[str, Any]]` at line 75 unchanged (out of scope per spec Assumptions). (e) Leave `context_values: dict[str, Any]` unchanged (unrelated). Do NOT rewrite the helper method bodies -- their `r["id"]` / `r.get("status")` calls become typed-lookups automatically once the field annotation changes.

- [X] T005 [US1] Update `packages/darnit/src/darnit/tools/audit.py`: (a) At line ~492, the sparse `all_results.append({"id": control_id, "status": "N/A", "details": "Excluded via .baseline.toml", "level": spec.level or 1})` construction: if mypy complains about the anonymous dict literal not being assignable to `list[CheckResult]`, either annotate the local dict `excluded_result: CheckResult = {...}` before appending or use `cast(CheckResult, {...})`. Prefer the annotated-local pattern (no `typing.cast` import needed if the file does not already use it). (b) At line ~530 (`result_dict["when"] = when_clause`): no change; `when` is listed as an optional key on `CheckResult` and this ad-hoc attach is grandfathered per `contracts/check-result.md`. (c) Widen the return annotations of `run_sieve_audit()` at line 319 (`tuple[list[dict[str, Any]], dict[str, int]]` -> `tuple[list[CheckResult], dict[str, int]]`) and `run_checks()` at line 269 (`tuple[list[dict[str, Any]], dict[str, str]]` -> `tuple[list[CheckResult], dict[str, str]]`). Add `from darnit.sieve.models import CheckResult` to the imports if not already present. Do NOT change any function body or dict shape.

**Checkpoint**: `AuditState.audit_results` is typed; the producer and the sparse-excluded path both emit `CheckResult`; the two `AuditState` helper methods inherit the type. Runtime behavior unchanged.

---

## Phase 4: Verification

Verifies the acceptance bar from spec.md. Runs in order after Phase 3.

- [X] T006 [US1] Static acceptance (SC-001): run the same mypy command from T001 and diff against the baseline. `uv run mypy packages/darnit/src/darnit/agent/state.py packages/darnit/src/darnit/agent/graph.py packages/darnit/src/darnit/sieve/models.py packages/darnit/src/darnit/tools/audit.py packages/darnit/src/darnit/cli.py 2>&1 | tail -30`. Expected: same-or-fewer errors than baseline; ZERO new errors mentioning `audit_results`. If any new error appears, fix it before proceeding.

- [X] T007 [US1] Negative acceptance (SC-002): temporarily change `packages/darnit/src/darnit/agent/state.py:86` from `return [r["id"] for r in self.audit_results if r.get("status") == "FAIL"]` to `return [r["idd"] for r in self.audit_results if r.get("status") == "FAIL"]`. Run `uv run mypy packages/darnit/src/darnit/agent/state.py`. Expected: mypy prints an error resembling `TypedDict "CheckResult" has no key "idd"  [typeddict-item]`. Revert the typo (`git checkout -- packages/darnit/src/darnit/agent/state.py` or manual edit) and rerun mypy to confirm the file is clean again. Record the negative-verification error in the PR description as evidence of enforcement.

- [X] T008 [US1] Runtime regression (SC-003): `uv run pytest tests/ --ignore=tests/integration/ -m "not slow" -q`. Expected: same pass/fail count as `main` post-feature-021 (2276 pass; 1 preexisting failure `test_upstream_spec_unchanged` unrelated to feature 022). If any test that used to pass now fails, the change is not type-only -- investigate.

- [X] T009 [US1] Wheel-install regression paranoia (bonus): `uv run pytest tests/packaging/test_wheel_install_config.py -m slow -v`. Expected: 3 pass. Feature 022 does not touch packaging, so failures would be surprising and indicate an unintended cross-effect.

- [X] T010 [US1] Lint + spec-sync gates: `uv run ruff check .` (expect clean) and `uv run python scripts/validate_sync.py --verbose` (expect all three checks pass). These are the two constitution dev-workflow gates that apply to any change touching framework code.

**Checkpoint**: Acceptance complete. Ready for PR.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: independent; records the baseline for comparison.
- **Foundational (Phase 2)**: empty; skip.
- **US1 impl (Phase 3)**: T002 -> T003 -> T004 -> T005 (each depends on the symbol introduced/annotated by the previous).
- **Verification (Phase 4)**: T006 depends on T005 (all impl done). T007 depends on T006 (baseline clean before injecting the typo). T008-T010 depend on T005 but not on each other; they can run in any order but do not need to run in parallel (all are fast).

### User Story Dependencies

- **US1**: only user story in this feature.

### Within Phase 3

- All tasks touch different files but introduce/consume symbols in sequence: `CheckResult` (T002) must exist before `to_legacy_dict()` is annotated (T003); `to_legacy_dict()` must return `CheckResult` before `AuditState.audit_results` (T004) is typed on it; `audit.py` (T005) also imports `CheckResult`. Do NOT parallelize.

### Parallel Opportunities

- None in the implementation phase. Type-annotation refactors on shared symbols are inherently sequential.
- In Phase 4, T008 (pytest) and T009 (wheel-install pytest) could run in parallel from a walltime standpoint, but they are cheap enough that sequential execution is fine.

---

## Implementation Strategy

### MVP (this is the MVP)

One user story, one PR. Nothing to slice further.

1. T001: baseline mypy error count.
2. T002-T005 in order: types, producer annotation, state field, tools annotations.
3. T006 static verification.
4. T007 negative-verification (revert after).
5. T008-T010 regression sweep + lint + sync.
6. PR review, merge.

### Not applicable

- Parallel team strategy: one contributor, one afternoon of work.

---

## Notes

- [P] tasks = different files, no dependencies. This feature has no [P] tasks (see above).
- No AI sign-off in commit or PR body per the project's OpenSSF-adjacent policy.
- Preserve ASCII-only style. Existing files in scope use ASCII; do not introduce non-ASCII characters in any of the touched files or in this feature's spec artifacts.
- No test file changes should be needed. If any test starts failing because of an annotation change, stop and diagnose -- the design goal is runtime-invariant.
- Feature 022 is the second of two BLOCKING pre-Stage-1 prereqs identified in the pre-Stage-1 architecture review. Feature 021 (config path fix) shipped in PR #362. After 022 lands, the next work is issue #359 (E2E `cmd_run` tests), then RFC-0001 Stage 1 harness driver.
- `remediation_results` typing is a natural parallel change but out of scope for this feature. File a follow-up issue only if the smell of "one typed field, one untyped field on the same dataclass" is worth tracking; otherwise defer to when Stage 1 or the remediation refactor forces the question.
