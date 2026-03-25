# Tasks: Detailed STRIDE Threat Modeling

**Input**: Design documents from `/specs/006-detailed-stride-threats/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Source**: `packages/darnit-baseline/src/darnit_baseline/threat_model/`
- **Tools**: `packages/darnit-baseline/src/darnit_baseline/tools.py`
- **Tests**: `tests/darnit_baseline/threat_model/`

## Phase 1: Setup

**Purpose**: No project initialization needed — existing package structure is in place. This phase verifies the starting state.

- [x] T001 Verify existing tests pass with `uv run pytest tests/ --ignore=tests/integration/ -q` before making changes
- [x] T002 Verify ruff lint passes with `uv run ruff check .` before making changes

---

## Phase 2: Foundational (Data Model Extensions)

**Purpose**: Extend core data models that ALL user stories depend on. No behavior changes yet — only new types and fields.

**CRITICAL**: No user story work can begin until this phase is complete.

- [x] T003 Add `RankedControl` dataclass to `packages/darnit-baseline/src/darnit_baseline/threat_model/models.py` with fields: `control: str`, `effectiveness: str` ("high"/"medium"/"low"), `rationale: str`
- [x] T004 Add `AttackChain` dataclass to `packages/darnit-baseline/src/darnit_baseline/threat_model/models.py` with fields: `id: str`, `name: str`, `description: str`, `threat_ids: list[str]`, `categories: list[StrideCategory]`, `shared_assets: list[str]`, `composite_risk: RiskScore`
- [x] T005 Add `DetailLevel` enum to `packages/darnit-baseline/src/darnit_baseline/threat_model/models.py` with values `SUMMARY = "summary"` and `DETAILED = "detailed"`
- [x] T006 Extend `Threat` dataclass in `packages/darnit-baseline/src/darnit_baseline/threat_model/models.py` with new optional fields: `exploitation_scenario: list[str] = field(default_factory=list)`, `data_flow_impact: str = ""`, `ranked_controls: list[RankedControl] = field(default_factory=list)`, `attack_chain_ids: list[str] = field(default_factory=list)`
- [x] T007 Extend `ThreatAnalysis` dataclass in `packages/darnit-baseline/src/darnit_baseline/threat_model/models.py` with `attack_chains: list[AttackChain] = field(default_factory=list)`
- [x] T008 Export new types (`RankedControl`, `AttackChain`, `DetailLevel`) from `packages/darnit-baseline/src/darnit_baseline/threat_model/__init__.py`
- [x] T009 Write backward compatibility tests in `tests/darnit_baseline/threat_model/test_models.py`: verify `Threat()` can be constructed without new fields, verify new fields have correct defaults, verify `ThreatAnalysis()` backward compat

**Checkpoint**: Data models extended. All existing tests still pass. No behavior changes yet.

---

## Phase 3: User Story 1 — Richer Threat Descriptions (Priority: P1) MVP

**Goal**: Every threat entry includes an exploitation scenario (>=3 steps), data-flow impact description, and controls ranked by effectiveness with rationale.

**Independent Test**: Run `generate_threat_model` against a sample repo and verify each threat has `exploitation_scenario`, `data_flow_impact`, and `ranked_controls` populated.

### Implementation for User Story 1

- [x] T010 [P] [US1] Create scenario template bank in new file `packages/darnit-baseline/src/darnit_baseline/threat_model/scenarios.py`: define `SCENARIO_TEMPLATES` dict keyed by threat sub-type (unauthenticated_endpoint, hardcoded_secret, injection_sql, injection_xss, injection_command, injection_path_traversal, injection_ssrf, injection_code, missing_rate_limit, missing_audit_log, server_action_no_auth) with each template containing `steps: list[str]` (>=3), `data_flow_pattern: str`, and `control_rankings: list[dict]` with effectiveness and rationale
- [x] T011 [US1] Create `get_scenario(threat_sub_type: str) -> dict | None` function in `packages/darnit-baseline/src/darnit_baseline/threat_model/scenarios.py` that returns the matching template or None (extension point for future LLM enrichment)
- [x] T012 [US1] Modify `analyze_stride_threats()` in `packages/darnit-baseline/src/darnit_baseline/threat_model/stride.py` to call `get_scenario()` for each threat and populate `exploitation_scenario`, `data_flow_impact`, and `ranked_controls` fields on the `Threat` object using the template data
- [x] T013 [US1] Update Markdown generator in `packages/darnit-baseline/src/darnit_baseline/threat_model/generators.py` `generate_markdown_threat_model()` to render exploitation scenario as numbered steps, data-flow impact line, and ranked controls as a table (control | effectiveness | rationale) per threat — this is the default "detailed" rendering
- [x] T014 [US1] Update Markdown generator to show all 6 STRIDE categories even when empty, with explanation of what was checked and why no threats were found (FR-009)
- [x] T015 [US1] Update Markdown generator to group and summarize findings when a single STRIDE category has >10 threats, showing representative examples instead of listing all (FR-010)
- [x] T016 [P] [US1] Update SARIF generator in `packages/darnit-baseline/src/darnit_baseline/threat_model/generators.py` `generate_sarif_threat_model()` to include `exploitationScenario`, `dataFlowImpact`, `rankedControls` in rule properties (FR-011)
- [x] T017 [P] [US1] Update JSON generator in `packages/darnit-baseline/src/darnit_baseline/threat_model/generators.py` `generate_json_summary()` to include `exploitation_scenario`, `data_flow_impact`, `ranked_controls` per threat (FR-011)
- [x] T018 [US1] Export `get_scenario`, `SCENARIO_TEMPLATES` from `packages/darnit-baseline/src/darnit_baseline/threat_model/__init__.py`
- [x] T019 [US1] Write tests in `tests/darnit_baseline/threat_model/test_scenarios.py`: verify all threat sub-types have templates, each template has >=3 steps, `get_scenario()` returns None for unknown types
- [x] T020 [US1] Write tests in `tests/darnit_baseline/threat_model/test_generators.py`: verify detailed Markdown output contains exploitation scenario steps, data-flow impact, ranked controls table, empty category explanations, and >10 finding grouping

**Checkpoint**: User Story 1 complete. Every threat has rich detail. Existing tests still pass.

---

## Phase 4: User Story 2 — Data Flow Diagrams (Priority: P2)

**Goal**: Markdown reports include a Mermaid data-flow diagram showing entry points, data stores, trust boundaries, and external actors.

**Independent Test**: Run `generate_threat_model` with `output_format=markdown` and verify a Mermaid `flowchart LR` diagram appears in the report.

### Implementation for User Story 2

- [x] T021 [US2] Create `generate_mermaid_dfd(assets: AssetInventory, threats: list[Threat]) -> str` function in `packages/darnit-baseline/src/darnit_baseline/threat_model/generators.py` that builds a Mermaid `flowchart LR` string with: external actors (inferred from entry point types), entry point nodes, data store nodes, auth mechanism nodes, `subgraph` blocks for trust boundaries (authenticated vs unauthenticated zones based on `EntryPoint.authentication_required`), and edges showing data flow between components
- [x] T022 [US2] Add >50 node simplification logic to `generate_mermaid_dfd()`: when total nodes exceed 50, show only high-risk paths (entries connected to CRITICAL/HIGH threats) with a note referencing the full asset inventory table (FR-012)
- [x] T023 [US2] Wire `generate_mermaid_dfd()` into `generate_markdown_threat_model()` in `packages/darnit-baseline/src/darnit_baseline/threat_model/generators.py`: insert diagram after Asset Inventory section, only when both entry points and data stores are discovered (SC-003), skip when assets are empty
- [x] T024 [US2] Export `generate_mermaid_dfd` from `packages/darnit-baseline/src/darnit_baseline/threat_model/__init__.py`
- [x] T025 [US2] Write tests in `tests/darnit_baseline/threat_model/test_generators.py`: verify Mermaid diagram appears when entry points + data stores exist, verify trust boundary subgraphs present when auth detected, verify diagram absent when no assets, verify >50 node simplification

**Checkpoint**: User Story 2 complete. Markdown reports contain data flow diagrams.

---

## Phase 5: User Story 3 — Configurable Detail Level (Priority: P2)

**Goal**: `generate_threat_model` accepts a `detail_level` parameter; "summary" produces compact output, "detailed" (default) produces full output.

**Independent Test**: Invoke with `detail_level=summary` and `detail_level=detailed`, verify outputs differ in depth. Summary should be <=40% the length of detailed (SC-005).

### Implementation for User Story 3

- [x] T026 [US3] Add `detail_level: str = "detailed"` parameter to `generate_threat_model()` in `packages/darnit-baseline/src/darnit_baseline/tools.py` per contract; validate value and fall back to "detailed" for invalid input; pass to Markdown generator only (SARIF/JSON ignore it)
- [x] T027 [US3] Add `detail_level: str = "detailed"` parameter to `generate_markdown_threat_model()` in `packages/darnit-baseline/src/darnit_baseline/threat_model/generators.py`; when "summary", render each threat as single line: title + risk score + top control only; omit exploitation scenarios, data-flow impact, ranked controls table, Mermaid DFD, and attack chains section
- [x] T028 [US3] Write tests in `tests/darnit_baseline/threat_model/test_generators.py`: verify summary output contains only title/risk/top control, verify detailed output contains full sections, verify summary length <= 40% of detailed length, verify SARIF/JSON unaffected by detail_level

**Checkpoint**: User Story 3 complete. Detail level toggle works. Both modes produce valid output.

---

## Phase 6: User Story 4 — Attack Chain Detection (Priority: P3)

**Goal**: Report identifies compound attack paths from predefined STRIDE category combinations with shared-asset tiebreaker, each with a composite risk score.

**Independent Test**: Run against a repo with unauthenticated endpoints + hardcoded secrets, verify "Attack Chains" section appears with composite risk score.

### Implementation for User Story 4

- [x] T029 [P] [US4] Create `packages/darnit-baseline/src/darnit_baseline/threat_model/chains.py` with `CHAIN_PATTERNS` dict defining 5 patterns: S+I (Credential Theft → Data Exfiltration), T+E (Input Manipulation → Privilege Escalation), R+I (Repudiation + Information Disclosure), D+T (Denial of Service + Tampering), S+E (Spoofing + Elevation of Privilege) — each with name, description template, and category pair
- [x] T030 [US4] Implement `calculate_composite_risk(threats: list[Threat]) -> RiskScore` in `packages/darnit-baseline/src/darnit_baseline/threat_model/chains.py` using formula: `max(individual_scores) + 0.1 * sum(other_scores)`, capped at 1.0; derive RiskLevel from the composite score using existing thresholds
- [x] T031 [US4] Implement `detect_attack_chains(threats: list[Threat], assets: AssetInventory) -> list[AttackChain]` in `packages/darnit-baseline/src/darnit_baseline/threat_model/chains.py`: for each CHAIN_PATTERN, check if both categories have threats AND share at least one asset (entry point, data store, or code file); build `AttackChain` objects with `TC-{N:03d}` IDs; back-reference chain IDs into participating `Threat.attack_chain_ids`
- [x] T032 [US4] Wire `detect_attack_chains()` into the threat model pipeline: call after `analyze_stride_threats()` in `generate_threat_model()` in `packages/darnit-baseline/src/darnit_baseline/tools.py`; pass results to generators
- [x] T033 [US4] Add "Attack Chains" section to Markdown generator in `packages/darnit-baseline/src/darnit_baseline/threat_model/generators.py`: render each chain with name, description, constituent threats, shared assets, and composite risk score; when no chains found, state "No compound attack paths identified"; skip section entirely in summary mode
- [x] T034 [P] [US4] Add attack chains to SARIF generator: `run.properties.attackChains` array with chain objects including `attackChainIds` per result in `packages/darnit-baseline/src/darnit_baseline/threat_model/generators.py`
- [x] T035 [P] [US4] Add attack chains to JSON generator: top-level `attack_chains` array with id, name, categories, composite_risk, threat_ids in `packages/darnit-baseline/src/darnit_baseline/threat_model/generators.py`
- [x] T036 [US4] Export `detect_attack_chains`, `calculate_composite_risk`, `CHAIN_PATTERNS` from `packages/darnit-baseline/src/darnit_baseline/threat_model/__init__.py`
- [x] T037 [US4] Write tests in `tests/darnit_baseline/threat_model/test_chains.py`: verify all 5 patterns defined, verify composite risk formula (max + 0.1*sum capped at 1.0), verify shared-asset tiebreaker required (no chain without shared assets), verify chain IDs back-referenced into Threat objects, verify empty result when no patterns match

**Checkpoint**: User Story 4 complete. Attack chains detected and rendered in all output formats.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Validation, regression testing, and cleanup across all stories.

- [x] T038 Run `uv run pytest tests/ --ignore=tests/integration/ -q` to verify all existing + new tests pass (SC-006)
- [x] T039 Run `uv run ruff check .` and `uv run ruff format .` to fix any lint/format issues
- [x] T040 Run `uv run python scripts/validate_sync.py --verbose` to verify spec-implementation sync
- [x] T041 Write end-to-end integration test in `tests/darnit_baseline/threat_model/test_integration.py`: invoke `generate_threat_model()` with a sample repo fixture in all 3 formats × 2 detail levels; verify Markdown detailed output has scenarios + DFD + chains; verify Markdown summary is <=40% length; verify SARIF/JSON include all new fields; verify no-assets edge case
- [x] T042 Run `uv run python scripts/generate_docs.py` and commit any changes to `docs/generated/`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — verify starting state
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — core enrichment, MVP
- **US2 (Phase 4)**: Depends on Phase 2 — can run in parallel with US1 (different functions in generators.py, but same file — coordinate)
- **US3 (Phase 5)**: Depends on Phase 3 (needs detailed rendering to exist before adding summary mode)
- **US4 (Phase 6)**: Depends on Phase 2 — can run in parallel with US1/US2 (new file chains.py, then wiring)
- **Polish (Phase 7)**: Depends on all user stories complete

### User Story Dependencies

- **US1 (P1)**: Depends on Phase 2 only. No other story dependencies. **MVP target.**
- **US2 (P2)**: Depends on Phase 2 only. Independent of US1.
- **US3 (P2)**: Depends on US1 (summary mode must render against the detailed format).
- **US4 (P3)**: Depends on Phase 2 only. Independent of US1/US2.

### Within Each User Story

- New modules (scenarios.py, chains.py) before stride.py/generators.py modifications
- stride.py changes before generator changes
- Generator changes before tools.py wiring
- Tests after implementation within each story

### Parallel Opportunities

- **Phase 2**: T003–T007 can be done in sequence (same file) but T009 can run after they're done
- **US1**: T010+T011 (scenarios.py) parallel with T016+T017 (SARIF/JSON generators)
- **US2**: Independent of US1 — can run in parallel
- **US4**: T029 (chains.py) independent of US1/US2 — can start as soon as Phase 2 is done; T034+T035 (SARIF/JSON) parallel with T033 (Markdown)

---

## Parallel Example: User Story 1

```bash
# These can run in parallel (different files):
Task T010: "Create scenario template bank in scenarios.py"
Task T011: "Create get_scenario() function in scenarios.py"

# After T012 (stride.py wiring), these can run in parallel (different generator functions):
Task T016: "Update SARIF generator with new fields"
Task T017: "Update JSON generator with new fields"
```

## Parallel Example: Across Stories

```bash
# After Phase 2 completes, these can start simultaneously:
US1 (T010): "Create scenarios.py"     # new file
US2 (T021): "Create generate_mermaid_dfd()"  # new function in generators.py
US4 (T029): "Create chains.py"        # new file
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Verify starting state
2. Complete Phase 2: Extend data models
3. Complete Phase 3: User Story 1 — richer threat descriptions
4. **STOP and VALIDATE**: Every threat has exploitation scenario, data-flow impact, ranked controls
5. Run existing tests to confirm no regressions

### Incremental Delivery

1. Phase 1 + Phase 2 → Foundation ready
2. Add US1 → Rich threat detail → Test independently (MVP!)
3. Add US2 → Data flow diagrams → Test independently
4. Add US3 → Detail level toggle → Test independently
5. Add US4 → Attack chains → Test independently
6. Polish → Full validation and cleanup

### Optimal Execution Path

1. Phase 1 → Phase 2 (sequential, same file)
2. US1 + US2 + US4 in parallel (different files/functions)
3. US3 after US1 (depends on detailed rendering)
4. Phase 7 after all stories

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- US3 is the only story with a dependency on another story (US1)
- All generators.py modifications touch different functions — coordinate but can interleave
- Scenario templates are the LLM extensibility point — keep `get_scenario()` interface clean
- Commit after each phase checkpoint
