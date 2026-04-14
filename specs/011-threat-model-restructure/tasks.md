# Tasks: Threat Model Output Restructure

**Input**: Design documents from `/specs/011-threat-model-restructure/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Test tasks are included. This project has an existing test suite and the spec requires backward-compat (FR-017) and idempotence (FR-016) verification.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Base: `packages/darnit-baseline/src/darnit_baseline/threat_model/`
Tests: `tests/darnit_baseline/threat_model/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create package scaffolding and extract shared code that all stories depend on.

- [x] T001 Create `renderers/` sub-package with `__init__.py` at `packages/darnit-baseline/src/darnit_baseline/threat_model/renderers/__init__.py`
- [x] T002 Create `renderers/common.py` at `packages/darnit-baseline/src/darnit_baseline/threat_model/renderers/common.py` — extract from `ts_generators.py`: `GeneratorOptions` (line 51), `_severity_band` → `severity_band` (line 91), `_risk_counts` (line 103), `_repo_display_name` (line 116), `_STRIDE_ORDER` (line 63), `_STRIDE_HEADINGS` (line 72), `_STRIDE_ABBREV` (line 81), `VERIFICATION_PROMPT_OPEN/CLOSE` (line 47-48). Add slug helper: `query_id_to_slug(query_id: str) -> str`. Add `top_risks_cap: int = 20` field to `GeneratorOptions` (per FR-005a "default N=20, configurable"). Update `ts_generators.py` imports to use `renderers.common` instead of local definitions.
- [x] T003 Create `tests/darnit_baseline/threat_model/renderers/__init__.py` test package scaffold

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Data model additions and grouping module that all user stories need.

**CRITICAL**: No user story work can begin until this phase is complete.

- [x] T004 Add `FindingGroup` frozen dataclass to `packages/darnit-baseline/src/darnit_baseline/threat_model/discovery_models.py` — fields: `query_id`, `slug`, `stride_category`, `class_name`, `mitigation_hint`, `findings` (tuple), `max_severity_score`. Add `__post_init__` validation per data-model.md. Add optional `fingerprint: str = ""` field to `CandidateFinding` (append as last field with default).
- [x] T005 [P] Add `mitigation_hint: str = ""` field to `PythonQuery` in `packages/darnit-baseline/src/darnit_baseline/threat_model/queries/python.py`, `JsQuery` in `queries/javascript.py`, `GoQuery` in `queries/go.py`, `YamlQuery` in `queries/yaml.py`. Populate per-query defaults for existing queries (one-sentence mitigation guidance per vulnerability class).
- [x] T006 Create `packages/darnit-baseline/src/darnit_baseline/threat_model/grouping.py` — implement `group_by_query_id(findings: list[CandidateFinding], query_registries: dict) -> list[FindingGroup]`. Groups by `source_query_id`, derives slug via `query_id_to_slug()`, picks `class_name` from highest-severity finding's `title`, picks `mitigation_hint` from query registry, sorts groups by `max_severity_score` descending.
- [x] T007 Modify `apply_cap()` in `packages/darnit-baseline/src/darnit_baseline/threat_model/ranking.py` — change return semantics: return `(all_findings_sorted, overflow_hint: TrimmedOverflow)` where `overflow_hint` represents classes beyond display threshold for SUMMARY (no findings dropped). Keep diversity rebalancing logic for sort ordering. Update callers in `ts_generators.py` and `remediation.py` to handle new return shape.
- [x] T008 [P] Write `tests/darnit_baseline/threat_model/test_grouping.py` — test: group by query_id, slug generation matches `query_id.replace(".", "-")`, ordering by max_severity_score, empty input returns empty list, single-group case, all findings in a group share same query_id.
- [x] T009 Update `packages/darnit-baseline/src/darnit_baseline/threat_model/__init__.py` — export `FindingGroup` from the package.

**Checkpoint**: Foundation ready — `renderers/common.py` provides shared helpers, `grouping.py` groups findings, `ranking.py` no longer drops, data model has `FindingGroup`. User story implementation can begin.

---

## Phase 3: User Story 1 — Reviewer gets a readable top-level risk picture (Priority: P1) MVP

**Goal**: Replace single monolithic THREAT_MODEL.md with multi-file output under `docs/threatmodel/` — SUMMARY.md + per-class findings + data-flow.md + raw-findings.json. All findings preserved, summary ≤ ~150 lines.

**Independent Test**: Regenerate threat model on this repo. SUMMARY.md exists and is ≤ 150 lines. Every finding from the old 981-line monolith appears in some detail file. Detail files group by query ID with compact instance tables.

### Implementation for User Story 1

- [x] T010 [P] [US1] Create `renderers/summary.py` at `packages/darnit-baseline/src/darnit_baseline/threat_model/renderers/summary.py` — implement `render_summary(groups: list[FindingGroup], sidecar_matches: dict, result: DiscoveryResult, options: GeneratorOptions, overflow_hint: TrimmedOverflow | None) -> str`. Render: executive summary table (repo, date, languages, totals), top-risks table capped at `options.top_risks_cap` rows (default 20) by max severity with `<mitigated>/<total>` stance column and links to `findings/<slug>.md`, overflow line ("and N more classes" linking to `findings/`), unmitigated findings section (uncapped — every group with ≥1 unmitigated instance), links to data-flow.md and raw-findings.json, recommendations section, verification prompts, limitations. For US1 (no sidecar yet), `sidecar_matches` is empty dict → all findings show as `0/N` and all appear in unmitigated section.
- [x] T011 [P] [US1] Create `renderers/group_file.py` at `packages/darnit-baseline/src/darnit_baseline/threat_model/renderers/group_file.py` — implement `render_group_file(group: FindingGroup, sidecar_matches: dict) -> str`. Render: H1 = class_name, STRIDE category, rule ID, max severity. Mitigation section (group's `mitigation_hint` or "no guidance available"). Representative examples: 1–3 `<details>` collapsible snippets from highest-severity instances. Instance table: ALL findings as Markdown table with columns `#`, `File`, `Line`, `Severity`, `Confidence`, `Status` (from sidecar or "Unmitigated"). No per-row code blocks. Footer with total count.
- [x] T012 [P] [US1] Create `renderers/data_flow.py` at `packages/darnit-baseline/src/darnit_baseline/threat_model/renderers/data_flow.py` — extract `_render_asset_inventory` (line 193), `_render_dfd` (line 265), `_detect_attack_chains` (line 496), `_render_attack_chains` (line 451) from `ts_generators.py`. Implement `render_data_flow(result: DiscoveryResult, options: GeneratorOptions) -> str`. Output matches current format (asset tables + Mermaid diagram + attack chains) wrapped in standalone doc with H1 "Data Flow Analysis".
- [x] T013 [P] [US1] Create `renderers/raw_json.py` at `packages/darnit-baseline/src/darnit_baseline/threat_model/renderers/raw_json.py` — implement `render_raw_json(result: DiscoveryResult, all_findings: list[CandidateFinding], sidecar_matches: dict) -> str`. Output: JSON with `metadata` (repo, date, languages, files_scanned, opengrep_available), `findings` array (every finding with query_id, category, title, severity, confidence, file, line, snippet, fingerprint, and optional `mitigation` object from sidecar), `entry_points`, `data_stores`, `file_scan_stats`. Per output-format-contract.md.
- [x] T014 [US1] Refactor `packages/darnit-baseline/src/darnit_baseline/threat_model/ts_generators.py` into backward-compat façade — `generate_markdown_threat_model()` calls new renderers (summary + all group files + data_flow) and concatenates into single string. Must preserve all 9 H2 sections that `TestMarkdownRequiredSections` (test line 156) asserts. Remove extracted helper bodies (now in renderers/), keep thin wrappers that delegate to `renderers.*`. Keep `generate_sarif_threat_model()` and `generate_json_summary()` in place (unchanged). Update all internal imports to use `renderers.common`.
- [x] T015 [US1] Rewrite `generate_threat_model_handler()` in `packages/darnit-baseline/src/darnit_baseline/threat_model/remediation.py` — new pipeline: discover → rank (no drop) → group_by_query_id → render multi-file output. Write files: `docs/threatmodel/SUMMARY.md`, `docs/threatmodel/data-flow.md`, `docs/threatmodel/raw-findings.json`, `docs/threatmodel/findings/<slug>.md` for each group. Use `os.makedirs(exist_ok=True)` + `open()` relative to `context.local_path`. Derive output dir from `config["path"]` parent. Pass empty dict for `sidecar_matches` (US2 adds real sidecar). Update `_build_llm_consultation` to reference new file paths. Return `HandlerResult` with `evidence.path = "docs/threatmodel/SUMMARY.md"` and `evidence.files_written = [all paths]`.
- [x] T016 [P] [US1] Write `tests/darnit_baseline/threat_model/renderers/test_summary.py` — test: summary has Executive Summary H2 and Top Risks H2, top-risks table has one row per group, ≤20 rows with overflow line when >20 groups, unmitigated section lists all groups when sidecar_matches is empty, summary output ≤150 lines for a fixture with 30 groups of 10 findings each. Also test single-group edge case: fixture with exactly 1 FindingGroup → top-risks table has exactly 1 data row, no overflow line, unmitigated section has 1 entry, links point to exactly 1 detail file.
- [x] T017 [P] [US1] Write `tests/darnit_baseline/threat_model/renderers/test_group_file.py` — test: output has H1 with class name, STRIDE category displayed, mitigation section present, representative snippets ≤3, instance table row count equals finding count in group, no per-row code blocks, status column defaults to "Unmitigated" when sidecar_matches is empty.
- [x] T018 [P] [US1] Write `tests/darnit_baseline/threat_model/renderers/test_data_flow.py` — test: output contains Mermaid fenced block, asset inventory tables present (entry points, data stores), attack chains section present. Assert parity with existing `TestMarkdownRequiredSections` DFD assertions.
- [x] T018a [P] [US1] Write empty-scan and single-class boundary tests in `tests/darnit_baseline/threat_model/renderers/test_summary.py` — (1) Empty scan (FR-019): call `render_summary()` with `groups=[]` and empty `DiscoveryResult`. Assert output is valid Markdown, contains "0" in total findings, top-risks table has zero data rows, unmitigated section is empty or states no findings, no detail file links. Also test `render_raw_json()` with empty findings list — assert valid JSON with `"findings": []`. (2) Single-class edge case: fixture with exactly 1 `FindingGroup` → top-risks table has exactly 1 data row, no overflow line, unmitigated section has 1 entry, links point to exactly 1 detail file.
- [x] T019 [US1] Verify backward-compat façade — run existing `tests/darnit_baseline/threat_model/test_ts_generators.py` (all 8 test classes). All must pass without modification. If any fail, fix the façade, not the tests.
- [x] T020 [US1] Update `tests/darnit_baseline/threat_model/test_remediation.py` — change assertions in `TestDynamicGeneration` (line 24), `TestOverwriteBehavior` (line 57), `TestEdgeCases.test_creates_parent_directories` (line 98) to expect `docs/threatmodel/SUMMARY.md` instead of `THREAT_MODEL.md`. Add assertion that `docs/threatmodel/findings/` directory is created and contains ≥1 `.md` file. Add assertion that `docs/threatmodel/raw-findings.json` is valid JSON.

**Checkpoint**: US1 complete. Regenerating a threat model produces `docs/threatmodel/` with SUMMARY.md + per-class detail files + data-flow.md + raw-findings.json. SUMMARY has top-risks table, unmitigated section, and links. All findings preserved. Existing tests pass via façade. Status columns show "Unmitigated" everywhere (sidecar not wired yet).

---

## Phase 4: User Story 2 — Maintainer's mitigation decisions survive regeneration (Priority: P2)

**Goal**: Introduce `.project/threatmodel/mitigations.yaml` sidecar. Fingerprint each finding. Match sidecar entries on regen. Show mitigation status in output. Flag stale entries.

**Independent Test**: Hand-author a sidecar entry for a known finding, regenerate, confirm summary shows it as mitigated. Delete the referenced code, regenerate again, confirm sidecar entry flagged stale but not deleted.

### Implementation for User Story 2

- [x] T021 [P] [US2] Add `MitigationStatus` enum, `MitigationEntry` and `MitigationSidecar` dataclasses to `packages/darnit-baseline/src/darnit_baseline/threat_model/discovery_models.py` — per data-model.md. Export from `__init__.py`.
- [x] T022 [US2] Create `packages/darnit-baseline/src/darnit_baseline/threat_model/sidecar.py` — implement: `compute_fingerprint(finding: CandidateFinding, repo_root: Path) -> str` (sha256 of query_id + repo-relative path + whitespace-normalized snippet, 16 hex prefix), `load_sidecar(repo_root: Path) -> MitigationSidecar | None` (return None if file missing; raise on malformed per FR-018), `save_sidecar(repo_root: Path, sidecar: MitigationSidecar) -> None` (preserve header comments, preserve entry ordering), `match_findings(findings: list[CandidateFinding], sidecar: MitigationSidecar) -> dict[str, MitigationEntry]` (fingerprint → entry lookup), `detect_stale(sidecar: MitigationSidecar, active_fingerprints: set[str]) -> bool` (set stale flags, return True if any changed). Sidecar path: `.project/threatmodel/mitigations.yaml` relative to repo_root. Per sidecar-format-contract.md.
- [x] T023 [US2] Wire sidecar into `generate_threat_model_handler()` in `packages/darnit-baseline/src/darnit_baseline/threat_model/remediation.py` — after grouping: compute fingerprints for all findings, load sidecar, match findings, detect stale. Pass `sidecar_matches` dict to all renderers (summary, group_file, raw_json). If stale flags changed, save sidecar. If sidecar is malformed, handler returns error HandlerResult (FR-018).
- [x] T024 [P] [US2] Write `tests/darnit_baseline/threat_model/test_sidecar.py` — test: `compute_fingerprint` determinism (same input = same hash), fingerprint changes when file path changes, fingerprint changes when snippet changes, fingerprint stable across whitespace-only reformatting. `load_sidecar` with valid YAML, missing file (returns None), malformed YAML (raises). `match_findings` with matching and non-matching fingerprints. `detect_stale` marks missing fingerprints stale, clears stale when fingerprint reappears, returns True only when flags changed. `save_sidecar` preserves entry ordering and header comments.
- [x] T025 [US2] Write integration test in `tests/darnit_baseline/threat_model/test_sidecar_integration.py` — end-to-end: create a tmp repo with a known finding, write a sidecar entry marking it mitigated, run `generate_threat_model_handler`, assert SUMMARY.md shows `1/N` in the top-risks stance column, assert finding is NOT in unmitigated section, assert `raw-findings.json` finding has `mitigation` object. Then remove the finding's source code, re-run handler, assert sidecar entry has `stale: true`.

**Checkpoint**: US2 complete. Sidecar entries carry mitigation decisions across regenerations. Stale entries are flagged, never deleted. Summary and detail files reflect sidecar status. Empty sidecar (first run) still works — same as US1 behavior.

---

## Phase 5: User Story 3 — Compliance audit recognizes the new canonical location (Priority: P3)

**Goal**: Update OSPS-SA-03.02 to accept `docs/threatmodel/SUMMARY.md` as evidence. Preserve all legacy paths. Add legacy file migration warning.

**Independent Test**: Run OSPS-SA-03.02 audit with only new-layout file → passes. Run with only legacy file → still passes.

### Implementation for User Story 3

- [x] T026 [P] [US3] Update `packages/darnit-baseline/openssf-baseline.toml` SA-03.02 section — change `locator.discover` to `["docs/threatmodel/SUMMARY.md", "THREAT_MODEL.md", "docs/THREAT_MODEL.md", "docs/threat-model.md", "docs/security/threat-model.md", "threatmodel/SUMMARY.md"]`, change `location_hint` to `"docs/threatmodel/SUMMARY.md"`, change `remediation.handlers[0].path` to `"docs/threatmodel/SUMMARY.md"`, change `remediation.project_update.set` to `{"security.threat_model.path" = "docs/threatmodel/SUMMARY.md"}`.
- [x] T027 [P] [US3] Update `packages/darnit-baseline/src/darnit_baseline/config/mappings.py` — prepend `"docs/threatmodel/SUMMARY.md"` and `"threatmodel/SUMMARY.md"` to `DEFAULT_FILE_LOCATIONS["security.threat_model"]` list.
- [x] T028 [P] [US3] Update `packages/darnit-baseline/src/darnit_baseline/remediation/enhancer.py` — add `"docs/threatmodel/SUMMARY.md": "threat_model"` to `LLM_ENHANCEABLE_FILES`. Keep legacy `"THREAT_MODEL.md"` entry.
- [x] T029 [P] [US3] Update `packages/darnit-baseline/src/darnit_baseline/tools.py` — in `generate_threat_model` MCP tool function (~line 884): when `output_path` points into `docs/threatmodel/` or is unset, use multi-file pipeline; when explicit single-file path, use backward-compat façade.
- [x] T030 [US3] Add legacy file handling to `generate_threat_model_handler()` in `packages/darnit-baseline/src/darnit_baseline/threat_model/remediation.py` — if `THREAT_MODEL.md` exists at `context.local_path` root when handler runs, log a warning and include `migration_note` in `HandlerResult.evidence` ("Legacy THREAT_MODEL.md detected; new canonical location is docs/threatmodel/SUMMARY.md. You may remove the legacy file."). Do NOT delete or overwrite the legacy file.
- [x] T031 [US3] Write `tests/darnit_baseline/threat_model/test_discovery_paths.py` — test: create temp repo with only `docs/threatmodel/SUMMARY.md` → SA-03.02 file_exists pass passes. Create temp repo with only `THREAT_MODEL.md` → still passes. Create temp repo with both → passes (prefers new location). Create temp repo with `threatmodel/SUMMARY.md` → passes.

**Checkpoint**: US3 complete. OSPS-SA-03.02 accepts all 6 discovery paths. Legacy repos continue passing. New-layout repos pass. Migration note surfaced when legacy file detected.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Dogfood, validate end-to-end, clean up.

- [x] T032 Dogfood: regenerate threat model on this repo using `generate_threat_model_handler` or MCP tool. Verify: `docs/threatmodel/SUMMARY.md` exists and is ≤ 150 lines, `docs/threatmodel/findings/` has one `.md` per unique `source_query_id`, `docs/threatmodel/data-flow.md` has Mermaid block, `docs/threatmodel/raw-findings.json` is valid JSON, old `THREAT_MODEL.md` at root is untouched.
- [x] T033 Idempotence check (FR-016): run regen twice with no code changes, `diff` all output files — must be byte-identical.
- [x] T034 Run full pre-commit checklist: `uv run ruff check .`, `uv run pytest tests/ --ignore=tests/integration/ -q`, `uv run python scripts/validate_sync.py --verbose`, `uv run python scripts/generate_docs.py && git diff docs/generated/`
- [x] T035 [P] Run `uv run ruff check --fix .` and `uv run ruff format .` to fix any lint/format issues introduced across all new files.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational (Phase 2) — no dependencies on other stories
- **US2 (Phase 4)**: Depends on US1 (Phase 3) — needs the multi-file handler pipeline to wire sidecar into
- **US3 (Phase 5)**: Depends on US1 (Phase 3) — needs the new canonical path to exist. Can run in parallel with US2.
- **Polish (Phase 6)**: Depends on all user stories being complete

### User Story Dependencies

- **US1 (P1)**: Foundational → US1 (standalone MVP)
- **US2 (P2)**: US1 → US2 (adds sidecar on top of multi-file output)
- **US3 (P3)**: US1 → US3 (updates discovery paths for new output location). Can parallelize with US2.

### Within Each User Story

- Renderers (T010-T013) are parallel — different files, no deps
- Façade refactor (T014) depends on renderers existing
- Handler rewrite (T015) depends on façade and grouping
- Tests can start as soon as their module is implemented

### Parallel Opportunities

**Phase 2**: T005 (query dataclass hints) and T008 (grouping tests) can run in parallel with T004 and T006
**Phase 3**: T010, T011, T012, T013 (4 renderers) can all run in parallel; T016, T017, T018 (renderer tests) can run in parallel
**Phase 4**: T021 (data model additions) and T024 (sidecar tests) can run in parallel
**Phase 5**: T026, T027, T028, T029 (4 config updates) can all run in parallel

---

## Parallel Example: User Story 1

```text
# Round 1: Launch all 4 renderers in parallel (different files):
T010: Create renderers/summary.py
T011: Create renderers/group_file.py
T012: Create renderers/data_flow.py
T013: Create renderers/raw_json.py

# Round 2: Façade (depends on renderers):
T014: Refactor ts_generators.py as façade

# Round 3: Handler + tests in parallel:
T015: Rewrite generate_threat_model_handler
T016: Test summary renderer         [parallel]
T017: Test group file renderer       [parallel]
T018: Test data flow renderer        [parallel]

# Round 4: Verify backward compat + update existing tests:
T019: Run existing test suite
T020: Update test_remediation.py
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T003)
2. Complete Phase 2: Foundational (T004-T009)
3. Complete Phase 3: US1 (T010-T020)
4. **STOP and VALIDATE**: Regenerate on this repo, verify SUMMARY.md ≤ 150 lines, all findings preserved, existing tests pass via façade
5. This alone delivers the core value: a readable threat model

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. Add US1 → readable multi-file output (MVP!)
3. Add US2 → mitigation decisions persist across regens
4. Add US3 → compliance audit accepts new location
5. Polish → dogfood, idempotence, lint

### Parallel Strategy

With two developers:
1. Both complete Setup + Foundational together
2. Developer A: US1 (MVP)
3. Once US1 done:
   - Developer A: US2 (sidecar)
   - Developer B: US3 (compliance paths) — can start as soon as US1 is done

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks in same phase
- [Story] label maps task to specific user story for traceability
- Each user story is independently completable and testable (US2 and US3 build on US1 but are independently verifiable)
- Commit after each completed phase
- Stop at any checkpoint to validate story independently
- FR-017 (backward compat) is verified explicitly at T019 — do not skip
