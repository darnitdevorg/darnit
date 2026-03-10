# Tasks: Getting Started Guide for Contributors

**Input**: Design documents from `/specs/005-getting-started-guide/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, quickstart.md

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: Create directory structure and establish document skeleton

- [x] T001 Create directory `docs/getting-started/`
- [x] T002 Create directory `docs/tutorials/`

**Checkpoint**: Directory structure ready for content creation

---

## Phase 2: Foundational (Shared Content)

**Purpose**: Write the environment setup and development workflow guides that ALL user stories depend on. These documents are shared prerequisites — every contributor path starts here.

**CRITICAL**: No user story work can begin until this phase is complete, because both framework and implementation paths reference these foundational guides.

- [x] T003 Write `docs/getting-started/environment-setup.md` — prerequisites (Python 3.11+, uv, gh CLI, git), fork-based workflow setup, cloning, `uv sync`, verifying the install by running tests. Consolidate setup content from CONTRIBUTING.md lines 9-27 and README.md lines 403-416. Include minimum tool versions and installation links. Cover macOS/Linux primary, WSL note for Windows. (FR-001, FR-002)
- [x] T004 Write `docs/getting-started/development-workflow.md` — pre-commit validation checklist (ruff check, pytest, validate_sync.py, generate_docs.py), branch naming conventions, commit message format, PR process, upstream rebase workflow. Consolidate from CONTRIBUTING.md lines 29-80. (FR-006)

**Checkpoint**: Foundation ready — contributors can set up their environment and understand the development workflow. User story phases can now begin.

---

## Phase 3: User Story 1 — Framework Developer Onboarding (Priority: P1)

**Goal**: A new contributor can understand the framework architecture, navigate the codebase, and make framework changes confidently.

**Independent Test**: A developer with no prior knowledge follows the framework path and successfully modifies a built-in handler or adds a test within 30 minutes.

### Implementation for User Story 1

- [x] T005 [US1] Write `docs/getting-started/framework-development.md` — package structure explanation (darnit, darnit-baseline, darnit-testchecks), separation rules (framework MUST NOT import implementations), ComplianceImplementation protocol, plugin discovery via entry points. Include three Mermaid diagrams: (1) package structure and relationships, (2) sieve pipeline 4-phase flow (file_must_exist → exec/pattern → llm_eval → manual), (3) plugin discovery mechanism (entry points → discovery → protocol calls). Cover how to add/modify built-in handlers, how to extend the sieve pipeline. Consolidate architecture content from README.md lines 90-107. (FR-003, FR-004)
- [x] T006 [P] [US1] Write `docs/getting-started/testing.md` — testing strategy overview, how to run framework tests (`uv run pytest tests/darnit/ -v`), how to run implementation tests (`uv run pytest tests/darnit_baseline/ -v`), how to run all tests, how to add new test files, test organization conventions, what to test when modifying framework code. Consolidate from IMPLEMENTATION_GUIDE.md lines 1518-1665. (FR-011)

**Checkpoint**: User Story 1 complete — framework developer path is fully documented. A contributor can set up (Phase 2), understand architecture, and develop on the framework.

---

## Phase 4: User Story 2 — Implementation Developer Onboarding (Priority: P1)

**Goal**: A new contributor can understand TOML control definitions, CEL expressions, and create or modify compliance implementations.

**Independent Test**: A developer follows the implementation path and successfully adds a new control to the OpenSSF Baseline TOML and verifies it in audit output within 30 minutes.

### Implementation for User Story 2

- [x] T007 [US2] Write `docs/getting-started/implementation-development.md` — TOML control definition format (metadata, passes, severity, help URLs), pass types (file_must_exist, exec, pattern, manual), handler registration via `register_handlers()`, entry point configuration in pyproject.toml, remediation registry structure, MCP tool registration. Consolidate from IMPLEMENTATION_GUIDE.md lines 182-312 (package setup, impl class), 389-610 (TOML config overview), 813-1299 (custom handlers), 1302-1516 (remediation + MCP tools). (FR-005)
- [x] T008 [P] [US2] Write `docs/getting-started/cel-reference.md` — CEL syntax rules (C-style operators: `&&`, `||`, `!` not Python `and`/`or`/`not`), available context variables (`output.stdout`, `output.stderr`, `output.exit_code`, `output.json`, `response.*`, `files`, `matches`, `project.*`), custom functions (`file_exists()`, `json_path()`), TOML literal string escaping rules (`\.` not `\\.` for regex dots), common pitfalls with examples. Consolidate CEL content from IMPLEMENTATION_GUIDE.md lines 389-610. (FR-010)
- [x] T009 [US2] Write `docs/tutorials/add-new-control.md` — complete copy-paste tutorial showing every step to add a new control to the OpenSSF Baseline implementation. Must include: (1) choosing a control ID, (2) adding the TOML control definition with metadata, passes, severity, (3) adding a CEL expression for the exec pass, (4) running `uv run python scripts/validate_sync.py --verbose` to verify sync, (5) running the audit and showing the new control in output, (6) expected output at each step. Self-contained — no external references needed. (FR-008)
- [x] T010 [US2] Write `docs/tutorials/create-new-implementation.md` — complete copy-paste tutorial showing every step to create a new compliance implementation from scratch. Must include: (1) creating the package directory structure, (2) writing pyproject.toml with entry points, (3) writing the implementation class implementing ComplianceImplementation protocol, (4) writing the TOML framework config with at least 2 sample controls, (5) writing the register() function, (6) installing the package with `uv pip install -e`, (7) verifying the framework discovers the plugin, (8) running an audit showing the new controls. Every file shown in full, every command shown with expected output. (FR-009)

**Checkpoint**: User Story 2 complete — implementation developer path is fully documented with both reference guide and copy-paste tutorials.

---

## Phase 5: User Story 3 — Environment Setup and Troubleshooting (Priority: P2)

**Goal**: Contributors can self-diagnose and resolve common setup and development issues without asking maintainers.

**Independent Test**: Intentionally omit a setup step (e.g., skip `gh auth login`) and verify the troubleshooting guide identifies and resolves the issue.

### Implementation for User Story 3

- [x] T011 [US3] Write `docs/getting-started/troubleshooting.md` — at least 5 common issues with symptoms, causes, and solutions. Must cover: (1) tests failing due to missing `gh auth login`, (2) `uv sync` failures (wrong Python version, missing uv), (3) validate_sync.py failures after code changes, (4) ruff linting errors and how to auto-fix, (5) import errors from circular dependencies or missing packages, (6) fork workflow issues (upstream not configured, rebase conflicts). Format each issue as: **Symptom** → **Cause** → **Solution** with exact commands. (FR-007)

**Checkpoint**: User Story 3 complete — troubleshooting guide covers common friction points.

---

## Phase 6: User Story 4 — Architecture Understanding (Priority: P2)

**Goal**: Contributors can build a mental model of the entire system before diving into code.

**Independent Test**: A new contributor can explain the end-to-end flow of a control check after reading the architecture documentation.

### Implementation for User Story 4

Note: The primary architecture content was created in T005 (framework-development.md with Mermaid diagrams). This phase ensures the architecture understanding is accessible from the hub and index documents, completing the navigation story.

- [x] T012 [US4] Write `docs/getting-started/README.md` — index document with two clearly labeled learning paths: "I want to work on the framework" (links to environment-setup → framework-development → testing → development-workflow) and "I want to create/modify an implementation" (links to environment-setup → implementation-development → cel-reference → tutorials → testing → development-workflow). Include a brief architecture overview paragraph with link to framework-development.md for diagrams. Link to troubleshooting. (FR-012)
- [x] T013 [US4] Write `GETTING_STARTED.md` at repository root — short hub document (under 100 lines) with: project name, one-paragraph description, prerequisites summary, two learning path sections (framework path, implementation path) each with 3-4 bullet points linking to docs/getting-started/ sub-guides, link to tutorials, link to troubleshooting, link to existing CONTRIBUTING.md for contribution policy. (FR-013)

**Checkpoint**: User Story 4 complete — contributors have a clear entry point and can navigate to their relevant path within 1 minute.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Consolidate existing docs and validate the complete documentation system

- [x] T014 Trim `README.md` — remove contributor dev setup content (lines ~90-107 package structure, ~177-196 creating plugins, ~403-416 dev setup/tests). Replace with brief summaries linking to `GETTING_STARTED.md` and relevant sub-guides. Keep all user-facing content (features, installation, quick start, configuration, MCP tools, security). (FR-014)
- [x] T015 [P] Trim `CONTRIBUTING.md` — remove detailed setup/workflow content (lines ~9-80). Keep Code of Conduct reference, high-level contribution policy, and questions/support section. Add links to `docs/getting-started/environment-setup.md`, `docs/getting-started/development-workflow.md`, and `GETTING_STARTED.md`. (FR-014)
- [x] T016 [P] Trim `docs/IMPLEMENTATION_GUIDE.md` — keep title, introduction, and architecture overview (lines ~1-101) as conceptual reference. Keep sieve pipeline section (~715-810) and quick reference appendix (~1752-1817). Replace all other sections with brief summaries linking to appropriate sub-guides in docs/getting-started/ and docs/tutorials/. (FR-014)
- [x] T017 Validate all internal links — check that every relative link in all new and modified documents resolves correctly. Verify Mermaid diagrams render (check syntax). Ensure no dead links to removed sections in trimmed documents. Verify hub → sub-guide → hub back-links work.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2
- **US2 (Phase 4)**: Depends on Phase 2 (independent of US1)
- **US3 (Phase 5)**: Depends on Phase 2 (independent of US1, US2)
- **US4 (Phase 6)**: Depends on Phases 3, 4, 5 (needs all sub-guides to exist for linking)
- **Polish (Phase 7)**: Depends on Phase 6 (needs hub and index to exist before trimming originals)

### User Story Dependencies

- **US1 (P1)**: Can start after Phase 2 — no dependencies on other stories
- **US2 (P1)**: Can start after Phase 2 — no dependencies on other stories
- **US3 (P2)**: Can start after Phase 2 — no dependencies on other stories
- **US4 (P2)**: Depends on US1, US2, US3 (index and hub link to all sub-guides)

### Within Each User Story

- Reference guides before tutorials (tutorials reference concepts from guides)
- Content creation before linking/indexing
- All sub-guides before hub document

### Parallel Opportunities

- T001 and T002 can run in parallel (different directories)
- T003 and T004 can run in parallel (different files, no dependencies)
- US1 (T005-T006) and US2 (T007-T010) and US3 (T011) can all start in parallel after Phase 2
- T006 and T005 are parallel within US1 (different files)
- T008 and T007 are parallel within US2 (different files)
- T014, T015, T016 — T015 and T016 are parallel (different files); T014 should go first since README is the most visible
- T009 depends on T007 (tutorial references concepts from guide)
- T010 depends on T007 (tutorial references concepts from guide)

---

## Parallel Example: User Stories 1 + 2 + 3

```text
# After Phase 2 (Foundational) is complete, launch all three stories in parallel:

# US1 (Framework):
Task T005: "Write framework-development.md with Mermaid diagrams"
Task T006: "Write testing.md" [P] (parallel with T005)

# US2 (Implementation) — in parallel with US1:
Task T007: "Write implementation-development.md"
Task T008: "Write cel-reference.md" [P] (parallel with T007)
# Then sequential within US2:
Task T009: "Write add-new-control tutorial" (after T007)
Task T010: "Write create-new-implementation tutorial" (after T007)

# US3 (Troubleshooting) — in parallel with US1 and US2:
Task T011: "Write troubleshooting.md"
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2)

1. Complete Phase 1: Setup (directories)
2. Complete Phase 2: Foundational (environment-setup, development-workflow)
3. Complete Phase 3: US1 — Framework developer path
4. Complete Phase 4: US2 — Implementation developer path
5. **STOP and VALIDATE**: Both P1 paths are documented end-to-end
6. Create hub and index (Phase 6), trim originals (Phase 7)

### Incremental Delivery

1. Setup + Foundational → Contributors can set up their environment
2. Add US1 (framework path) → Framework contributors unblocked
3. Add US2 (implementation path + tutorials) → Implementation contributors unblocked
4. Add US3 (troubleshooting) → Self-service issue resolution
5. Add US4 (hub + index) + Polish → Complete navigation and consolidated docs
6. Each phase adds standalone value

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- All content should be sourced from existing codebase, CLAUDE.md, constitution, and existing docs — not invented
- Mermaid diagrams must be tested in GitHub's renderer before merging
- Tutorials must be validated end-to-end by actually running the steps
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
