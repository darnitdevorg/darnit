# Tasks: Threat Model Remediation Handler

**Input**: Design documents from `/specs/007-threatmodel-remediation-handler/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, quickstart.md

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

## Path Conventions

- **Source**: `packages/darnit-baseline/src/darnit_baseline/`
- **Threat Model**: `packages/darnit-baseline/src/darnit_baseline/threat_model/`
- **TOML**: `packages/darnit-baseline/openssf-baseline.toml`
- **Tests**: `tests/darnit_baseline/threat_model/`

## Phase 1: Setup

**Purpose**: Verify starting state before making changes.

- [x] T001 Verify existing tests pass with `uv run pytest tests/ --ignore=tests/integration/ -q`
- [x] T002 Verify ruff lint passes with `uv run ruff check .`

---

## Phase 2: Foundational

**Purpose**: No foundational work needed — the sieve handler registry and threat model engine already exist. Proceed directly to user stories.

---

## Phase 3: User Story 1 — Dynamic Threat Model During Remediation (Priority: P1) MVP

**Goal**: SA-03.02 remediation generates a project-specific threat model using the dynamic STRIDE analysis engine instead of a static template.

**Independent Test**: Run `remediate_audit_findings` targeting SA-03.02. Verify THREAT_MODEL.md contains project-specific threats, not generic template text.

### Implementation for User Story 1

- [x] T003 [US1] Create `packages/darnit-baseline/src/darnit_baseline/threat_model/remediation.py` with `generate_threat_model_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult` function that: extracts `path` and `overwrite` from config; checks if file exists and respects overwrite flag; calls the analysis pipeline (`detect_frameworks`, `discover_all_assets`, `discover_injection_sinks`, `analyze_stride_threats`, `detect_attack_chains`, `identify_control_gaps`); generates Markdown with `generate_markdown_threat_model()` using `detail_level="detailed"`; writes the report to `os.path.join(context.local_path, path)`; returns `HandlerResult` with PASS status and evidence including the file path and threat count
- [x] T004 [US1] Register the new handler with the sieve handler registry in `packages/darnit-baseline/src/darnit_baseline/implementation.py`: import `get_sieve_handler_registry` from `darnit.sieve.handler_registry`; in `register_handlers()`, call `sieve_registry.register("generate_threat_model", phase="deterministic", handler_fn=generate_threat_model_handler, description="Generate dynamic STRIDE threat model")` with plugin context set
- [x] T005 [US1] Update SA-03.02 remediation config in `packages/darnit-baseline/openssf-baseline.toml`: replace the `handler = "file_create"` entry with `handler = "generate_threat_model"`; keep `path = "THREAT_MODEL.md"`, `template = "threat_model_basic"` (for fallback content), and `overwrite = false`; remove the `llm_enhance` field (dynamic analysis replaces it); keep `project_update` section unchanged
- [x] T006 [US1] Export `generate_threat_model_handler` from `packages/darnit-baseline/src/darnit_baseline/threat_model/__init__.py`
- [x] T007 [US1] Write tests in `tests/darnit_baseline/threat_model/test_remediation.py`: test handler produces dynamic content (not template text) when given a repo path with assets; test handler respects overwrite=false (skips when file exists); test handler respects overwrite=true (regenerates); test handler returns error for invalid/inaccessible repo path; test handler writes report even when no assets discovered (report explains no assets found)

**Checkpoint**: SA-03.02 remediation produces dynamic threat models. All existing tests still pass.

---

## Phase 4: User Story 2 — Fallback to Static Template on Failure (Priority: P2)

**Goal**: If the dynamic analysis pipeline raises an exception, the handler falls back to writing the static template content instead of failing.

**Independent Test**: Mock the analysis pipeline to raise an exception. Verify the handler writes the template content and reports the fallback in its result message.

### Implementation for User Story 2

- [x] T008 [US2] Add fallback logic to `generate_threat_model_handler` in `packages/darnit-baseline/src/darnit_baseline/threat_model/remediation.py`: wrap the analysis pipeline call in a try/except; on exception, use `config.get("content", "")` (the pre-resolved template content from the executor) as the file content; if template content is empty, return HandlerResult with ERROR status; otherwise write the template content to the path and return PASS with a message noting "Dynamic analysis unavailable — created from template"
- [x] T009 [US2] Write fallback tests in `tests/darnit_baseline/threat_model/test_remediation.py`: test handler falls back to template content when analysis raises an exception; test fallback result message mentions "template"; test handler returns ERROR when both analysis fails AND no template content available

**Checkpoint**: Fallback behavior verified. Remediation never fails silently.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Validation, regression testing, and cleanup.

- [x] T010 Run `uv run pytest tests/ --ignore=tests/integration/ -q` to verify all existing + new tests pass (SC-004)
- [x] T011 Run `uv run ruff check .` and `uv run ruff format .` to fix any lint/format issues
- [x] T012 Run `uv run python scripts/validate_sync.py --verbose` to verify spec-implementation sync
- [x] T013 Run `uv run python scripts/generate_docs.py` and check for changes to `docs/generated/`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — verify starting state
- **US1 (Phase 3)**: Depends on Phase 1 — core handler implementation, MVP
- **US2 (Phase 4)**: Depends on US1 (adds fallback to existing handler)
- **Polish (Phase 5)**: Depends on all user stories complete

### User Story Dependencies

- **US1 (P1)**: No dependencies beyond existing codebase. **MVP target.**
- **US2 (P2)**: Depends on US1 (modifies the handler created in US1).

### Within Each User Story

- Handler implementation before registration
- Registration before TOML config update
- Tests after implementation

### Parallel Opportunities

- T001 and T002 can run in parallel (different commands)
- Within US1: T003 (handler) and T005 (TOML) touch different files but T005 references the handler name, so do T003 first
- T010-T013 in polish phase can largely run in parallel

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Verify starting state
2. Complete Phase 3: User Story 1 — dynamic handler + registration + TOML update
3. **STOP and VALIDATE**: Run remediation against a test repo, verify dynamic output
4. Run existing tests to confirm no regressions

### Incremental Delivery

1. Phase 1 → US1 → Dynamic handler working (MVP!)
2. Add US2 → Fallback on failure → Test independently
3. Polish → Full validation and cleanup

---

## Notes

- This is a small, focused feature: 1 new file, 2 modified files, 1 test file
- The handler reuses existing analysis code — no new analysis logic
- Template content for fallback is pre-resolved by the executor via the `template` field in TOML
- The `llm_enhance` field is removed from SA-03.02 config since dynamic analysis produces project-specific content
