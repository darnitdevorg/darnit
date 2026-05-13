---
description: "Task list for feature 013-plugin-composition"
---

# Tasks: Composition of compliance implementations

**Input**: Design documents under `/specs/013-plugin-composition/`
**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: Included. Composition is a compliance-critical primitive; the spec defines 26 explicit acceptance scenarios (5 user stories × multiple scenarios each). Test-fixture-driven validation through the production loader is the spec's stated approach (R-010, contracts/resolver-api.md §Test contract).

**Organization**: Tasks are grouped by user story so each story can be implemented, tested, and delivered as an independent MVP increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story (US1..US5) — Setup/Foundational/Polish have no story label
- Every task names exact file paths

## Path Conventions

Single Python workspace. All new code lands inside `packages/darnit/src/darnit/`; all tests under `tests/darnit/`. No new top-level package.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Test infrastructure — fixture directory, mock source TOMLs, conftest helper providing an injectable `source_loader` so tests don't have to register real entry points.

- [X] T001 Create `tests/darnit/fixtures/composite/` directory (with a placeholder `__init__.py` and a short `README.md` explaining the fixture-driven testing approach from R-010).
- [X] T002 [P] Author `tests/darnit/fixtures/composite/_sources/mock-source-a.toml` — a minimal non-composite framework with 5 controls spanning levels 1/2/3 and domains AC/VM/QA. Set `[metadata].name = "mock-source-a"`, `version = "1.5.0"`. Controls: `MOCK-AC-01.01` (L1), `MOCK-AC-02.01` (L1), `MOCK-VM-01.01` (L2), `MOCK-VM-02.01` (L3), `MOCK-QA-01.01` (L2). Each control has one trivial `file_must_exist` pass with `path = "DOES_NOT_EXIST.fixture"` (intentionally unsatisfiable — tests are SHAPE-only per F-3, so a FAIL result is the expected outcome whenever the audit pipeline actually runs).
- [X] T003 [P] Author `tests/darnit/fixtures/composite/_sources/mock-source-b.toml` — a minimal non-composite framework with 3 level-1 controls and `[metadata].version = "0.9.0"`. Controls: `MOCK-B-01.01`, `MOCK-B-02.01`, `MOCK-B-03.01`. Use the same `file_must_exist` with `path = "DOES_NOT_EXIST.fixture"` pattern as T002.
- [X] T004 [P] Author `tests/darnit/fixtures/composite/_sources/mock-source-c-leaf.toml` — a non-composite source with 2 controls (`LEAF-01.01`, `LEAF-02.01`) used as the ultimate origin in the three-level recursive scenario. Use the same unsatisfiable `file_must_exist` path as T002.
- [X] T005 [P] Author `tests/darnit/fixtures/composite/_sources/mock-source-mid-composite.toml` — a composite that pulls `include_all` from `mock-source-c-leaf`. Used as the middle layer of the three-level chain in US4's positive scenario.
- [X] T006 Add `tests/darnit/conftest.py` fixtures `composite_fixtures_dir` (returns the absolute path to `_sources/`) and `fixture_source_loader` (returns a `Callable[[str], FrameworkConfig | None]` that loads any of the `_sources/*.toml` files by slug **via `darnit.config.merger._parse_framework_only(path)` — NOT `load_framework_config`**). The fixture loader MUST be parse-only so tests exercise the same F-1 path as production: composition recursion is owned by the resolver under one shared `_resolution_stack`. Document this constraint in a docstring on the fixture so future contributors don't switch it back to a resolving loader.

**Checkpoint**: fixtures + loader helper available; foundational schema work can begin.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: New pydantic schema entities, error class hierarchy, resolver skeleton, and the loader integration shim. Every user story depends on this phase.

**⚠️ CRITICAL**: No user story work begins until this phase is complete.

- [X] T007 Create `packages/darnit/src/darnit/core/composition.py` with the public `__all__` from contracts/resolver-api.md and module-level docstring referencing the spec. Define base class `CompositionError(Exception)` plus the six concrete subclasses (`CompositionMissingSourceError`, `CompositionConflictError`, `CompositionOrphanOverrideError`, `CompositionUnknownFieldError`, `CompositionCycleError`, `CompositionVersionMismatchError`) with the attribute signatures specified in contracts/resolver-api.md §Exceptions. Each subclass overrides `__str__` to render every named attribute.
- [X] T008 [P] Add `ComposeBlock(BaseModel)` to `packages/darnit/src/darnit/config/framework_schema.py` with the fields and validators from data-model.md §Entity 1 (`source`, `include_all`, `include_levels`, `include_controls`, `include_tags`, `exclude_controls`, `version_constraint`). Implement validators V1.1–V1.4 (at-least-one-inclusion, mutual exclusion of `include_all`, PEP 440 specifier parsing via `packaging.specifiers.SpecifierSet`, error message naming malformed specifier).
- [X] T009 [P] Add `OverrideBlock(BaseModel)` to `packages/darnit/src/darnit/config/framework_schema.py` with the fields from data-model.md §Entity 2 (`passes`, `remediation`, `security_severity`, `description`, `docs_url`, `tags`) and validator V2.3 (at-least-one-field-set). **Field names match the real `ControlConfig` schema exactly** — do NOT add aliases for `severity` / `help_url`.
- [X] T010 Extend the existing `FrameworkConfig` class in `packages/darnit/src/darnit/config/framework_schema.py` with `compose: list[ComposeBlock] = Field(default_factory=list)`, `overrides: dict[str, OverrideBlock] = Field(default_factory=dict)`, and `allow_conflicts: bool = False`. Keep `model_config = ConfigDict(extra="allow")` intact; do NOT remove or rename any existing field.
- [X] T011 Implement the `resolve_composition` function skeleton in `packages/darnit/src/darnit/core/composition.py` per data-model.md §Resolution algorithm pseudocode. Cover idempotence (invariant I3.3 — return input unchanged if `compose == []` and `overrides == {}`), the `_resolution_stack` threading (a single stack threaded through every recursive call — this is the ONLY stack; cycle detection's correctness depends on it), basic self-cycle detection (raise `CompositionCycleError` before recursing if `composite_slug in _resolution_stack`), and returning a new `FrameworkConfig` via `model_copy(update={"controls": ..., "compose": [], "overrides": {}})` (invariant I3.2). Leave compose-block iteration and override application as `pass`/`raise NotImplementedError` markers — US1 fills the compose half, US2 fills the override half.
- [X] T012 Refactor `darnit.config.merger.load_framework_config` per contracts/resolver-api.md §Integration contract. Extract a new private helper `_parse_framework_only(path: Path) -> FrameworkConfig` that does the existing pydantic parse + template-path validation but does NOT touch composition. Then make `load_framework_config(path)` a thin wrapper: call `_parse_framework_only(path)`, and IF `config.compose or config.overrides` is non-empty, call `resolve_composition(config)` exactly once before returning. This split is load-bearing for F-1 / FR-012 — the resolver's `source_loader` routes through `_parse_framework_only` so recursive source loads don't re-enter composition with a fresh `_resolution_stack`. Preserve all existing behavior for non-composite frameworks.
- [X] T013 Add a module-level logger `log = logging.getLogger("darnit.core.composition")` in `composition.py` and import it. All log emissions in later tasks route through this logger.

**Checkpoint**: schema accepts composite TOML, loader invokes resolver, resolver short-circuits idempotently. Existing tests still pass; no behavioral change for non-composite frameworks.

---

## Phase 3: User Story 1 — Organization assembles its own compliance baseline (Priority: P1) 🎯 MVP

**Goal**: A composite implementation can declare `[[compose]]` blocks plus inline controls and produce a flat resolved control set through the existing audit pipeline.

**Independent Test**: A minimal `acme-baseline` composite that pulls 3 controls from `mock-source-a` and adds 1 inline control resolves to exactly 4 controls; `darnit list-controls --implementation acme-baseline` lists them; `darnit audit ...` produces a single non-composite-shaped result set. No Python composition code in the implementation class.

### Compose-block resolution

- [X] T014 [P] [US1] Implement `_select_controls(block: ComposeBlock, source_controls: dict) -> set[str]` in `packages/darnit/src/darnit/core/composition.py` per R-009 (intersection semantics). Order: start with full set if `include_all`, else apply `include_levels` ∩ `include_controls` ∩ `include_tags`; finally subtract `exclude_controls`. DEBUG-log empty results.
- [X] T015 [P] [US1] Implement `_load_source_with_cache(slug: str, cache: dict, loader: Callable) -> FrameworkConfig | None` in `composition.py`. Returns `None` if loader returns `None` (caller raises `CompositionMissingSourceError`). Memoizes per slug for the lifetime of one top-level resolution (R-003). The `loader` argument MUST be a parse-only function (the resolver's default routes through `darnit.config.merger._parse_framework_only`, not `load_framework_by_name`) — this is the F-1 fix and is non-negotiable for cycle detection.
- [X] T016 [P] [US1] Implement `_clone_with_provenance(ctrl: ControlConfig, composed_from: str, original_id: str) -> ControlConfig` in `composition.py`. Uses `ctrl.model_copy(update={"tags": {**ctrl.tags, "_composed_from": composed_from, "_original_control_id": original_id}})`. Reads existing `_composed_from` / `_original_control_id` from the source's tags first so recursive provenance preserves the ultimate non-composite origin (R-006 / FR-018).
- [X] T017 [US1] Fill the compose-block iteration loop in `resolve_composition` per data-model.md §Resolution algorithm: for each block, load source via `_load_source_with_cache` (raise `CompositionMissingSourceError` on `None`) — the loader returns a parsed-but-NOT-resolved `FrameworkConfig` per T015 — then **recurse via `resolve_composition(source, _source_cache=..., _resolution_stack=...)`** to drive composition resolution under the SHARED cycle-detection stack (this is how FR-018's recursive composition works AND how F-1's cycle detection holds). Call `_select_controls`, clone each selected control with provenance, and insert into `resolved` dict. Track `contributor: dict[str, str]` per-ID for later conflict messages. Stash inline controls into `resolved` and `contributor` first so they look like a "compose source = self" for conflict-detection purposes.
- [X] T018 [US1] Inject the `source_loader` parameter into `resolve_composition` per contracts/resolver-api.md §Function signature. **Default to a private wrapper that does slug → path via `PluginRegistry` and then loads via `darnit.config.merger._parse_framework_only(path)` — NOT `load_framework_by_name`** (that would re-enter `resolve_composition` with a fresh stack and break F-1's cycle detection). Tests inject the `fixture_source_loader` from T006, which is also parse-only.
- [X] T019 [US1] Stamp inline controls with `_composed_from = "<composite-slug>"` and `_original_control_id = "<own ID>"` so SC-003 holds uniformly across composed and inline controls.

### US1 fixtures and tests

- [X] T020 [P] [US1] Author `tests/darnit/fixtures/composite/basic-include-all.toml` — composes `include_all = true` from `mock-source-a`. Add `test_basic_include_all` in `tests/darnit/test_composition.py` asserting the resolved set equals all 5 mock-source-a controls.
- [X] T021 [P] [US1] Author `tests/darnit/fixtures/composite/include-levels.toml` — `include_levels = [1, 2]` from `mock-source-a`. Add `test_include_levels_filter` asserting the level-3 control (`MOCK-VM-02.01`) is absent.
- [X] T022 [P] [US1] Author `tests/darnit/fixtures/composite/include-controls.toml` — `include_controls = ["MOCK-AC-01.01", "MOCK-QA-01.01"]`. Add `test_include_controls_filter` asserting only those two appear.
- [X] T023 [P] [US1] Author `tests/darnit/fixtures/composite/exclude-after-include.toml` — `include_all = true` + `exclude_controls = ["MOCK-AC-02.01"]`. Add `test_exclude_controls_after_include` asserting AC-02.01 absent and the other four present.
- [X] T024 [P] [US1] Author `tests/darnit/fixtures/composite/intersection-of-includes.toml` — `include_levels = [1]` + `include_controls = ["MOCK-AC-01.01", "MOCK-VM-02.01"]`. Add `test_intersection_of_includes` asserting only `MOCK-AC-01.01` appears (the level filter intersects with the ID filter, so the L3 ID drops out).
- [X] T025 [P] [US1] Author `tests/darnit/fixtures/composite/inline-with-compose.toml` — one `[[compose]]` block + one `[controls."ACME-LOCAL-01.01"]` block. Add `test_provenance_for_inline_controls` asserting the inline control's tags carry `_composed_from = "<composite-slug>"` and `_original_control_id = "ACME-LOCAL-01.01"`, and that composed controls carry the source's slug.
- [X] T026 [P] [US1] Author `tests/darnit/fixtures/composite/missing-source.toml` — `[[compose]]` block names a slug like `"does-not-exist-impl"`. Add `test_missing_source_raises` asserting `CompositionMissingSourceError` raised with `.source == "does-not-exist-impl"`.
- [X] T027 [P] [US1] Author `tests/darnit/fixtures/composite/empty-compose-block.toml` — `[[compose]]` block with only `source = "mock-source-a"` and no inclusion expressions. Add `test_empty_compose_block_rejected` asserting registration error from validator V1.1 names the source slug.
- [X] T028 [P] [US1] Author `tests/darnit/fixtures/composite/diamond.toml` — composes from `mock-source-mid-composite` AND directly from `mock-source-c-leaf`. Add `test_diamond_resolves_once` asserting `LEAF-01.01` and `LEAF-02.01` appear exactly once and that the wrapped `source_loader` was called once per unique slug (use a counting wrapper around `fixture_source_loader`).
- [X] T029 [P] [US1] Author `tests/darnit/fixtures/composite/audit-pipeline.toml` — small composite (3 composed + 1 inline). Add `test_audit_pipeline_unchanged` that uses the standard `tools.audit` entry point through `load_framework_config` and asserts the result list is **shape-identical** to a non-composite audit result: no new keys, no missing keys, control IDs match the resolved set. The test is SHAPE-only — individual control status (PASS/FAIL/WARN/INCONCLUSIVE) is irrelevant; the fixtures use unsatisfiable `file_must_exist` paths (T002–T005) so every audit returns FAIL, which is sufficient because what's being verified is that composition leaves the result-object schema unchanged, not that any particular control passes.

**Checkpoint**: US1 is independently shippable. Resolver handles inclusion/exclusion, source loading, provenance, missing sources, diamonds, and end-to-end audit shape. Conflicts produce a still-incomplete error path until US2 + US3 land — composites that produce conflicts in US1 trigger a `NotImplementedError` from T011's marker. Tests in T020–T029 are constructed to avoid conflicts.

---

## Phase 4: User Story 2 — Override a single inherited control (Priority: P2)

**Goal**: A composite can override specific fields of an inherited control without forking the source.

**Independent Test**: A composite that pulls `MOCK-AC-01.01` from `mock-source-a` and adds `[overrides."MOCK-AC-01.01"]` with a custom `remediation`. The resolved control retains the upstream pass logic; the remediation matches the override.

- [X] T030 [US2] Implement `_validate_override_fields(override: OverrideBlock) -> None` in `packages/darnit/src/darnit/core/composition.py`. Iterate `override.model_fields_set` (Pydantic v2); for each set field, confirm it appears in `ControlConfig.model_fields.keys()`. Raise `CompositionUnknownFieldError(field=..., control_id=...)` on miss.
- [X] T031 [US2] Implement `_apply_override(ctrl: ControlConfig, override: OverrideBlock) -> ControlConfig` in `composition.py`. Build an `update` dict containing only the override's set fields. Handle `passes` (wholesale replacement, FR-006), scalars (`remediation`, `security_severity`, `description`, `docs_url` — direct replacement; these names match the real `ControlConfig` schema), and `tags` (shallow merge with reserved-key guard — silently drop `_composed_from` / `_original_control_id` if present in override.tags, emit WARNING log).
- [X] T032 [US2] Fill the override-application loop at the tail end of `resolve_composition` per data-model.md §Resolution algorithm. For each `override_id` in `composite.overrides`: if not in `resolved` → `CompositionOrphanOverrideError(orphan_id=override_id)`; else call `_validate_override_fields` then `_apply_override`. Replace `resolved[override_id]` with the result. Remove the `NotImplementedError` marker from T011's skeleton.

### US2 fixtures and tests

- [X] T033 [P] [US2] Author `tests/darnit/fixtures/composite/override-remediation.toml` — composes `MOCK-AC-01.01` from `mock-source-a`, overrides only `remediation`. Add `test_overrides_replace_fields` asserting passes match the source verbatim and remediation matches the override string.
- [X] T034 [P] [US2] Author `tests/darnit/fixtures/composite/override-preserves-provenance.toml` — same shape as T033 but assert in `test_overrides_preserve_provenance` that `tags["_composed_from"] == "mock-source-a"` and `tags["_original_control_id"] == "MOCK-AC-01.01"` AFTER the override applies.
- [X] T035 [P] [US2] Author `tests/darnit/fixtures/composite/orphan-override.toml` — `[overrides."DOES-NOT-EXIST"]` with no compose block contributing that ID. Add `test_orphan_override_raises` asserting `CompositionOrphanOverrideError.orphan_id == "DOES-NOT-EXIST"`.
- [X] T036 [P] [US2] Author `tests/darnit/fixtures/composite/unknown-field-override.toml` — `[overrides."MOCK-AC-01.01"]` with a `bogus_field = "x"` entry plus a valid `description` field. Add `test_unknown_field_override_raises` asserting `CompositionUnknownFieldError.field == "bogus_field"`. Also add a sub-test `test_alias_field_names_rejected` using `severity = 8.5` (no underscore prefix) in another override fixture and asserting the same error class with `.field == "severity"` — this pins down the "no friendly aliases" guarantee from F-2.
- [X] T037 [P] [US2] Author `tests/darnit/fixtures/composite/empty-override.toml` — `[overrides."MOCK-AC-01.01"]` with NO fields under it. Add `test_empty_override_block_rejected` asserting V2.3 validator error names the offending control ID.

**Checkpoint**: US2 is independently shippable. Override-only composites work; override-resolves-conflict cases still raise `NotImplementedError` from T011 because the conflict-detection branch is not yet wired — left for US3.

---

## Phase 5: User Story 3 — Conflicting controls resolve predictably (Priority: P2)

**Goal**: Strict-by-default conflict resolution with two named escape hatches (`allow_conflicts` and `[overrides."..."]`).

**Independent Test**: A composite that pulls `MOCK-AC-01.01` from two compose blocks with different selectors fails registration; adding `allow_conflicts = true` makes it succeed last-wins with an INFO log; replacing `allow_conflicts` with an explicit `[overrides."MOCK-AC-01.01"]` block makes it succeed in strict mode.

- [ ] T038 [US3] In `resolve_composition`'s compose-block loop, replace the T011 conflict-marker with the conflict-detection logic from data-model.md pseudocode: when `ctrl_id in resolved` AND `ctrl_id in composite.overrides` → `continue` (override-resolves-conflict, FR-011); else when `composite.allow_conflicts` → INFO log + overwrite (FR-010); else → `raise CompositionConflictError(control_id, sources=(contributor[ctrl_id], block.source))` (FR-009).
- [ ] T039 [US3] Add the INFO log emission: `log.info("Composition conflict on %s: %s overrides %s (allow_conflicts=true)", ctrl_id, block.source, contributor[ctrl_id])` exactly per contracts/resolver-api.md §Side effects.

### US3 fixtures and tests

- [ ] T040 [P] [US3] Author `tests/darnit/fixtures/composite/strict-conflict.toml` — two `[[compose]]` blocks, both `mock-source-a`, both `include_controls = ["MOCK-AC-01.01"]`. Add `test_strict_conflict_raises` asserting `CompositionConflictError.control_id == "MOCK-AC-01.01"` AND `.sources` contains `"mock-source-a"` twice (or whatever the contributor tracking surfaces — verify the error message mentions both opt-outs `allow_conflicts = true` and `[overrides."..."]`).
- [ ] T041 [P] [US3] Author `tests/darnit/fixtures/composite/allow-conflicts-last-wins.toml` — same shape as T040 but two distinct sources (`mock-source-a` and a NEW `_sources/mock-source-a-variant.toml` you create with one differing-field `MOCK-AC-01.01`) and `allow_conflicts = true` at the top level. Add `test_allow_conflicts_last_wins` asserting registration succeeds, the resolved `MOCK-AC-01.01` matches the LATER compose block's source, and `caplog.records` contains an INFO line naming both sources.
- [ ] T042 [P] [US3] Author `tests/darnit/fixtures/composite/override-resolves-conflict.toml` — same dual-source conflict shape as T041 but with `[overrides."MOCK-AC-01.01"]` and `allow_conflicts` UNSET. Add `test_override_resolves_conflict_in_strict_mode` asserting registration succeeds, the override's fields are applied, no `CompositionConflictError` is raised, and **the resolved control's non-overridden fields come from the EARLIER compose block** (not the later one — verifies the earliest-base rule from F-11/FR-011). Also assert no INFO log line is emitted (overrides resolve conflicts silently because the per-control acknowledgement is explicit). Add a companion test `test_override_with_allow_conflicts_still_uses_earliest_base` using the same fixture pattern but with `allow_conflicts = true` added — assert the same earliest-base outcome to lock down the mode-independence of FR-011.

**Checkpoint**: US3 is independently shippable. All three conflict-resolution pathways are tested. The override-resolves-conflict case (T042) is the integration point that proves US2 + US3 cooperate correctly.

---

## Phase 6: User Story 4 — Composition cycles detected and rejected (Priority: P3)

**Goal**: Self-cycles, two-cycles, and arbitrary-length cycles all fail registration with a clear chain-naming error message. Non-cyclic recursive composition succeeds with provenance traced to the ultimate source.

**Independent Test**: Two composites referencing each other fail to register; a non-cyclic three-level chain (A→B→C, C non-composite) resolves with every control's `_composed_from` pointing at C, not B.

- [ ] T043 [US4] Enrich the `CompositionCycleError` raised from `resolve_composition` (existing T011 skeleton) to render `__str__` as the chain joined by ` → ` (e.g., `"Composition cycle detected: acme-baseline → middle-comp → acme-baseline"`). Store `chain: list[str]` as the attribute.

### US4 fixtures and tests

- [ ] T044 [P] [US4] Author `tests/darnit/fixtures/composite/_sources/cycle-a.toml` — composes `include_all` from `cycle-a` (itself). Add `test_self_cycle_raises` asserting `CompositionCycleError.chain == ["cycle-a", "cycle-a"]` and the error message contains `"cycle-a → cycle-a"`.
- [ ] T045 [P] [US4] Author `tests/darnit/fixtures/composite/_sources/cycle-x.toml` + `tests/darnit/fixtures/composite/_sources/cycle-y.toml` — X composes Y, Y composes X. Add `test_two_cycle_raises` asserting `CompositionCycleError` raised on first load with chain `["cycle-x", "cycle-y", "cycle-x"]` (or whichever order matches load order — assert the chain length is 3 and starts+ends with the same slug).
- [ ] T046 [P] [US4] Author `tests/darnit/fixtures/composite/three-level-chain.toml` — composes from `mock-source-mid-composite` (which itself composes from `mock-source-c-leaf`, both created in T004–T005). Add `test_three_level_chain_resolves` asserting registration succeeds, every resolved control's `tags["_composed_from"] == "mock-source-c-leaf"` (the ULTIMATE non-composite source per FR-018), NOT `"mock-source-mid-composite"`.
- [ ] T046b [P] [US4] Regression test for F-1: author `tests/darnit/fixtures/composite/_sources/loader-cycle-x.toml` and `_sources/loader-cycle-y.toml` where X composes Y and Y composes X. Add `test_loader_path_cycle_through_public_loader` that loads X via the production `darnit.config.merger.load_framework_config(...)` (NOT through the injected fixture loader) and asserts `CompositionCycleError` is raised within a short bounded time. **Preferred approach** — wrap the call with `t0 = time.perf_counter(); pytest.raises(CompositionCycleError): load_framework_config(...); assert time.perf_counter() - t0 < 1.0` (no new dependency). Avoid `pytest.timeout` unless `pytest-timeout` is already in the project's dev deps. This test would have hung indefinitely under the pre-F-1 design and is the canonical regression guarantee that the resolver / loader split is correct.

**Checkpoint**: US4 is independently shippable. Cycle protection is in place from foundational (T011) — this story adds the chain-rich error message and exercises the recursive-composition positive path that proves FR-018.

---

## Phase 7: User Story 5 — Version pinning (Priority: P3)

**Goal**: A `[[compose]]` block can pin to a PEP 440 specifier; mismatches fail with a clear error.

**Independent Test**: A composite that pins `mock-source-a >=1.0,<2.0` resolves (installed version is `1.5.0`); changing the pin to `>=2.0` fails registration.

- [ ] T047 [US5] In `_load_source_with_cache` or the compose-block iteration in T017, after loading the source `FrameworkConfig`, evaluate `block.version_constraint` if set: parse with `packaging.specifiers.SpecifierSet(block.version_constraint)`, compare against `source_config.metadata.version` via `Version(...) in specifier_set`. On mismatch, raise `CompositionVersionMismatchError(source=block.source, constraint=block.version_constraint, installed=source_config.metadata.version)`. (The specifier-parse step itself is validated at TOML load time by T008's V1.3 validator; this is the runtime version check.)

### US5 fixtures and tests

- [ ] T048 [P] [US5] Author `tests/darnit/fixtures/composite/version-pin-satisfied.toml` — composes `mock-source-a` with `version_constraint = ">=1.0,<2.0"`. Add `test_version_pin_satisfied` asserting registration succeeds.
- [ ] T049 [P] [US5] Author `tests/darnit/fixtures/composite/version-pin-violated.toml` — composes `mock-source-a` with `version_constraint = ">=2.0"`. Add `test_version_pin_violated` asserting `CompositionVersionMismatchError` raised with `.source`, `.constraint`, and `.installed = "1.5.0"`.
- [ ] T050 [P] [US5] Add `test_version_pin_missing_uses_floating` reusing `basic-include-all.toml` (T020) — no `version_constraint`. Assert registration succeeds against the installed source version with no version-check error path entered.

**Checkpoint**: US5 is independently shippable. Composites can pin or float per the spec's FR-013/FR-014 split.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Performance verification, idempotence smoke, doc sync, and the quickstart-walkthrough end-to-end check.

- [ ] T051 [P] Add `test_idempotent_resolution` in `tests/darnit/test_composition.py`: load `basic-include-all.toml` via `load_framework_config` once, call `resolve_composition` on the result a second time, assert the second call returns a structurally equal `FrameworkConfig` (same `controls` dict, still empty `compose` and `overrides`) — invariant I3.3.
- [ ] T052 [P] Add `test_resolution_performance` in `tests/darnit/test_composition.py`: build a synthetic source with 50 controls, a composite with 5 inline controls plus an `include_all` block, time the `resolve_composition` call, assert `elapsed < 0.2` seconds. Use `pytest.mark.benchmark` or simple `time.perf_counter`.
- [ ] T053 [P] Update `packages/darnit/src/darnit/core/composition.py` module docstring to reference contracts/resolver-api.md and contracts/toml-schema.md as canonical references for the surface.
- [ ] T054 Run `uv run python scripts/validate_sync.py --verbose` and address any framework-design spec drift surfaced by the new composition primitives.
- [ ] T055 Run `uv run python scripts/generate_docs.py` and commit any resulting `docs/generated/` changes.
- [ ] T056 Lint and type-check: `uv run ruff check . && uv run ruff format --check .`
- [ ] T057 Full test run: `uv run pytest tests/ --ignore=tests/integration/ -q`. All previously-passing tests must remain green; the new composition tests added in T020–T050 / T051–T052 must pass.
- [ ] T058 End-to-end quickstart walkthrough: follow [quickstart.md](./quickstart.md) Steps 1–4 verbatim against a locally-installed `acme-baseline` package backed by the real `darnit-baseline` + `darnit-gittuf`. Verify `list-controls`, `audit`, and provenance-tag inspection all behave as documented.
- [ ] T059 Add a Composition section to `docs/IMPLEMENTATION_GUIDE.md` (or create one if absent) summarizing: when to compose vs. fork, the three conflict-resolution paths, and how provenance flows through audit results. Link to the spec, plan, and quickstart.
- [ ] T060 Rebase from upstream (`git fetch upstream && git rebase upstream/main`) and verify the workspace still passes T056 + T057 before opening the PR.
- [ ] T061 [P] Add `test_existing_implementations_unaffected` in `tests/darnit/test_composition.py` covering SC-008 (F-5). Parametrize over the four installed implementations (`darnit-baseline`, `darnit-gittuf`, `darnit-hello`, `darnit-testchecks`); for each, call `darnit.config.merger.load_framework_config(impl.get_framework_config_path())`. Assert `cfg.compose == []`, `cfg.overrides == {}`, `cfg.allow_conflicts is False`, and `len(cfg.controls) > 0`. Snapshot the resolved `controls.keys()` for each implementation against a baseline fixture stored at `tests/darnit/snapshots/<impl>-control-ids.json` (auto-generate the snapshots on first run if missing, with a TODO comment to manually commit them).
- [ ] T062 [P] Add `test_cli_implementation_flag_with_composite` in `tests/darnit/test_cli.py` covering FR-017 (F-6). Use a temporary composite installed via an entry point (or directly via a TOML file path), invoke `darnit audit --implementation <composite-slug> <tmp_path>` and `darnit list-controls --implementation <composite-slug>` through the CLI's `main([...])` entry point (no subprocess needed), and assert both return exit code 0 and produce output containing the expected control IDs.
- [ ] T063 [P] Add `test_dual_audit_tool_exposure` in `tests/darnit/test_composition.py` covering the spec's MCP-tool-ownership edge case (F-7). Register a composite alongside its source (both must be discoverable). Inspect the MCP server's tool registry and assert both `audit_<source-slug>` and `audit_<composite-slug>` are present and non-colliding. Invoke each through its handler entry point against a `tmp_path`; assert both return shape-valid result objects without raising.

---

## Dependencies

```text
Setup (T001–T006)
        │
        ▼
Foundational (T007–T013) ──────── BLOCKS ALL USER STORIES
        │
        ├──────────────────────┬──────────────────────┬──────────────────┬──────────────────┐
        ▼                      ▼                      ▼                  ▼                  ▼
   US1 (T014–T029)        US4 (T043–T046)        US5 (T047–T050)
        │                      │                      │
        ▼                      │                      │
   US2 (T030–T037)             │                      │
        │                      │                      │
        ▼                      │                      │
   US3 (T038–T042)             │                      │
        │                      │                      │
        └──────────────────────┴──────────────────────┴────────────────► Polish (T051–T060)
```

**Story-level dependencies**:

- **US1** depends only on Foundational. It is the MVP increment.
- **US2** depends on US1 because the override pass operates on an already-resolved control set.
- **US3** depends on US2 because the override-resolves-conflict pathway (T038, T042) requires the override application loop from US2.
- **US4** depends only on Foundational. Cycle protection lives in T011's skeleton; this phase enriches the error and adds the recursive-positive scenario. Can run in parallel with US2/US3.
- **US5** depends only on Foundational. The version check is independent of conflicts and overrides. Can run in parallel with US2/US3/US4.

**Within-story parallelism**: fixtures and tests marked `[P]` are independent — different fixture files, different test functions. Implementation tasks marked `[P]` operate on distinct helper functions or distinct schema entities and don't share lines. Sequential tasks within a story (no `[P]`) modify the same function body (e.g., the `resolve_composition` body) and must run in listed order.

---

## Implementation Strategy

### MVP (Story 1 only)

Ship T001–T029. Composites can pull slices from non-composite sources, add inline controls, and produce audit results. No overrides, no conflict resolution, no cycle detection beyond the foundational guardrail, no version pinning. This is sufficient for the Story 1 acceptance scenarios (1–4) and unblocks early dogfooding by security architects with simple postures.

### Incremental delivery order

1. **MVP**: Foundational + US1 (29 tasks; the smallest shippable increment).
2. **Override safety net**: + US2 (5 tasks; adds the "without forking" promise).
3. **Predictable multi-source composites**: + US3 (5 tasks; unblocks composites that pull from two sources with overlapping IDs, which is realistic the moment composites cross framework families).
4. **Recursive composition + cycle clarity**: + US4 (4 tasks; necessary the moment one composite becomes another's source).
5. **Reproducibility for compliance users**: + US5 (4 tasks; needed by regulator-driven users but not by most teams).
6. **Polish & docs**: + Phase 8 (10 tasks; verify performance, sync docs, walk the quickstart end-to-end).

### Parallel-team strategy

After Foundational (T013) is merged, four developer-pairs can work in parallel:

- Pair A: US1 (T014–T029) — owns the resolver core.
- Pair B: US4 (T043–T046) — owns cycle messages + recursive positive scenario.
- Pair C: US5 (T047–T050) — owns version-pin enforcement.
- Pair D: starts on Phase 8 doc tasks (T053, T059) that don't depend on resolver internals.

US2 and US3 must wait for US1 to land (they extend `resolve_composition`'s body in-place); they can run sequentially by a single pair after US1 merges.

### Suggested PR boundaries

- **PR 1**: Setup + Foundational (T001–T013). All-green tests, no behavior change for non-composite frameworks.
- **PR 2**: US1 (T014–T029). MVP increment.
- **PR 3**: US2 (T030–T037).
- **PR 4**: US3 (T038–T042). This PR closes the spec's two main composition footguns (silent conflicts and orphan overrides).
- **PR 5**: US4 + US5 (T043–T050). Can be bundled because both are P3 guardrails with small surface area.
- **PR 6**: Polish (T051–T060).

---

## Format validation summary

- ✅ Every task starts with `- [ ]`.
- ✅ Every task has a sequential `T###` ID.
- ✅ Every task names an exact file path or directory (in tasks that don't, like T054/T055/T056/T057/T060, the description is a single command — no path applies).
- ✅ Setup, Foundational, and Polish tasks carry NO `[Story]` label.
- ✅ Every US1–US5 phase task carries the correct `[US#]` label.
- ✅ `[P]` markers gate strictly on file-disjointness AND no incomplete dependencies.
- ✅ Total task count: 64. Setup: 6. Foundational: 7. US1: 16. US2: 8. US3: 5. US4: 5 (T043, T044, T045, T046, T046b — the last is the F-1 loader-path cycle regression). US5: 4. Polish: 13 (T051–T060 plus T061/T062/T063 for F-5/F-6/F-7).
