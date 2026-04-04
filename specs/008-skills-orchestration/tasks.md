# Tasks: Skills-Based Orchestration Layer with Audit Profiles

**Input**: Design documents from `/specs/008-skills-orchestration/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Tests are included for Python changes (audit profiles). Skill files are prompt templates tested manually via Claude Code.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup

**Purpose**: Create directory structure for skills and profile support

- [x] T001 Create skills directory at packages/darnit-baseline/skills/
- [x] T002 [P] Create test file for audit profile schema at tests/darnit/config/test_audit_profiles.py with empty test class
- [x] T003 [P] Create test file for profile filtering at tests/darnit/tools/test_audit_profile_filter.py with empty test class
- [x] T004 [P] Create test file for baseline profiles at tests/darnit_baseline/test_profiles.py with empty test class

---

## Phase 2: Foundational — Audit Profile Schema and Resolution

**Purpose**: Add `AuditProfileConfig` to the framework schema and implement profile resolution logic. This MUST be complete before any user story can use `--profile`.

**CRITICAL**: No profile-related user story work can begin until this phase is complete.

- [x] T005 Add `AuditProfileConfig` Pydantic model to packages/darnit/src/darnit/config/framework_schema.py — fields: `description` (str, required), `controls` (list[str], default []), `tags` (dict[str, Any], default {}), with validator ensuring at least one of controls or tags is non-empty
- [x] T006 Add `audit_profiles: dict[str, AuditProfileConfig]` field (default {}) to `FrameworkConfig` in packages/darnit/src/darnit/config/framework_schema.py
- [x] T007 Add `resolve_profile()` function to packages/darnit/src/darnit/config/profile_resolver.py (new file) — accepts profile name string + dict of implementations, returns (impl_name, AuditProfileConfig). Handles short names, `impl:profile` qualified names, ambiguity errors, and not-found errors per contracts/mcp-profile-parameter.md
- [x] T008 Add `resolve_profile_control_ids()` function to packages/darnit/src/darnit/config/profile_resolver.py — accepts AuditProfileConfig + list of all ControlSpec, returns filtered list of control IDs. Handles explicit control lists, tag-based filters, and union of both
- [x] T009 Write tests for AuditProfileConfig validation (non-empty constraint, field types) in tests/darnit/config/test_audit_profiles.py
- [x] T010 [P] Write tests for resolve_profile() (short name, qualified name, ambiguous, not found) in tests/darnit/config/test_audit_profiles.py
- [x] T011 [P] Write tests for resolve_profile_control_ids() (explicit IDs, tag filter, union, invalid IDs) in tests/darnit/config/test_audit_profiles.py

**Checkpoint**: Profile schema parses from TOML, resolution logic works. Run `uv run pytest tests/darnit/config/test_audit_profiles.py -v` to verify.

---

## Phase 3: User Story 1 — Run a Compliance Audit via Skill (Priority: P1) MVP

**Goal**: A user types `/audit` in Claude Code and gets a complete compliance report. PENDING_LLM controls are resolved by Claude inline.

**Independent Test**: Run `/audit` in a repository with `.project/` context and verify a formatted report is returned with pass/fail/warn statuses and compliance percentages.

### Implementation for User Story 1

- [x] T012 [US1] Create `/audit` skill definition at packages/darnit-baseline/skills/audit.md — structured prompt that: (1) calls `audit_openssf_baseline` MCP tool, (2) inspects results for PENDING_LLM controls and resolves them using Claude's reasoning, (3) formats a compliance report with per-level percentages, (4) lists WARN controls with explanations, (5) notes available remediations and suggests `/remediate`
- [x] T013 [US1] Add `--profile` parameter handling to the `/audit` skill in packages/darnit-baseline/skills/audit.md — when provided, pass `profile` parameter to `audit_openssf_baseline` MCP tool
- [x] T014 [US1] Add `profile` parameter to `audit_openssf_baseline` handler in packages/darnit-baseline/src/darnit_baseline/tools.py — resolve profile to control ID list using `resolve_profile()` and `resolve_profile_control_ids()`, pass filtered list to `run_sieve_audit(controls=...)`
- [x] T015 [US1] Write tests for profile filtering in audit tool in tests/darnit/tools/test_audit_profile_filter.py — verify that passing a profile name results in only those controls being evaluated

**Checkpoint**: `/audit` skill works end-to-end. Profile filtering works when `--profile` is passed. Run tests with `uv run pytest tests/darnit/tools/test_audit_profile_filter.py -v`.

---

## Phase 4: User Story 2 — Guided Context Collection via Skill (Priority: P1)

**Goal**: A user types `/context` and is guided through collecting missing project context via structured questions.

**Independent Test**: Run `/context` in a repository with missing context values and verify questions are asked, answers saved to `.project/project.yaml`.

### Implementation for User Story 2

- [x] T016 [US2] Create `/context` skill definition at packages/darnit-baseline/skills/context.md — structured prompt that: (1) calls `get_pending_context` MCP tool, (2) presents auto-detected values for confirmation, (3) asks remaining questions to user, (4) calls `confirm_project_context` for each answer, (5) repeats until status is "complete", (6) reports which controls are now unblocked
- [x] T017 [US2] Add `--profile` parameter handling to the `/context` skill in packages/darnit-baseline/skills/context.md — when provided, pass profile's control IDs to `get_pending_context` to filter questions to profile-relevant controls only

**Checkpoint**: `/context` skill guides user through context collection. Profile-scoped context collection works when `--profile` is passed.

---

## Phase 5: User Story 3 — Full Compliance Pipeline via Skill (Priority: P2)

**Goal**: A user types `/comply` and the system orchestrates audit → context → remediate → PR in one flow.

**Independent Test**: Run `/comply` in a repository with compliance gaps and verify the full pipeline executes with user confirmation gates.

### Implementation for User Story 3

- [x] T018 [US3] Create `/comply` skill definition at packages/darnit-baseline/skills/comply.md — structured prompt that: (1) runs `/audit` skill logic (audit + PENDING_LLM resolution), (2) if WARN controls exist, runs `/context` skill logic, (3) re-audits affected controls, (4) shows remediation plan with safe/unsafe distinction, (5) on confirmation, calls `create_remediation_branch`, `remediate_audit_findings`, `commit_remediation_changes`, `create_remediation_pr` MCP tools in sequence, (6) shows final compliance delta
- [x] T019 [US3] Add `--profile` parameter handling to the `/comply` skill in packages/darnit-baseline/skills/comply.md — passes profile through to audit, context, and remediation steps

**Checkpoint**: `/comply` orchestrates the full pipeline. User sees audit results, answers context questions, confirms remediation, gets a PR.

---

## Phase 6: User Story 4 — Audit with Named Profile (Priority: P2)

**Goal**: Implementation authors define profiles in TOML. Users run `/audit --profile <name>` and only profile controls are evaluated.

**Independent Test**: Define two profiles in TOML with different control sets, run `/audit --profile <name>` for each, verify only correct controls are evaluated.

### Implementation for User Story 4

- [x] T020 [US4] Add `[audit_profiles]` section to packages/darnit-baseline/openssf-baseline.toml with three example profiles: `level1_quick` (tags: level=1), `security_critical` (tags: security_severity_gte=8.0), `access_control` (explicit control IDs for AC domain)
- [x] T021 [US4] Add optional `get_audit_profiles()` method to `OSPSBaselineImplementation` in packages/darnit-baseline/src/darnit_baseline/implementation.py — loads profiles from framework TOML config and returns dict[str, AuditProfileConfig]
- [x] T022 [US4] Document `get_audit_profiles()` as optional protocol method (via comment, checked with hasattr) in packages/darnit/src/darnit/core/plugin.py
- [x] T023 [US4] Add `--profile` flag to `audit`, `plan`, and `remediate` subcommands in packages/darnit/src/darnit/cli.py — wire profile resolution into `cmd_audit()` and `cmd_remediate()` to filter controls before execution
- [x] T024 [US4] Add `darnit profiles` subcommand to packages/darnit/src/darnit/cli.py — lists available profiles across all loaded implementations, with optional `--impl` filter, per contracts/cli-profile-flag.md
- [x] T025 [P] [US4] Write tests for TOML profile parsing in openssf-baseline in tests/darnit_baseline/test_profiles.py — verify profiles load correctly, control lists resolve, tag filters work
- [x] T026 [P] [US4] Write tests for `--profile` CLI flag parsing in tests/darnit/test_cli.py — verify flag accepted on audit/plan commands, profiles subcommand parses correctly
- [x] T027 [US4] Add `profile` parameter to `list_available_checks` handler in packages/darnit-baseline/src/darnit_baseline/tools.py — when profile specified, list only controls in that profile

**Checkpoint**: Profiles defined in TOML, loadable via protocol, filterable via CLI and MCP tools. Run `uv run pytest tests/darnit_baseline/test_profiles.py tests/darnit/test_cli.py -v`.

---

## Phase 7: User Story 5 — Remediation via Skill (Priority: P3)

**Goal**: A user types `/remediate` and gets a dry-run plan, confirms, then gets a branch + PR with fixes.

**Independent Test**: Run `/remediate` after an audit with failures and verify branch creation, fixes applied, PR offered.

### Implementation for User Story 5

- [x] T028 [US5] Create `/remediate` skill definition at packages/darnit-baseline/skills/remediate.md — structured prompt that: (1) checks for cached audit results (runs audit if missing), (2) calls `remediate_audit_findings` with dry_run=true to show plan, (3) distinguishes safe vs unsafe remediations, (4) on confirmation, calls `create_remediation_branch`, `remediate_audit_findings` (dry_run=false), `commit_remediation_changes`, optionally `create_remediation_pr`, (5) shows summary of changes
- [x] T029 [US5] Add `--profile` parameter handling to the `/remediate` skill in packages/darnit-baseline/skills/remediate.md — passes profile to remediation tool to filter to profile controls only
- [x] T030 [US5] Add `profile` parameter to `remediate_audit_findings` handler in packages/darnit-baseline/src/darnit_baseline/tools.py — filter remediation to profile controls only

**Checkpoint**: `/remediate` skill works end-to-end with profile filtering.

---

## Phase 8: User Story 6 — Profile-Aware Context and Remediation (Priority: P3)

**Goal**: When `--profile` is used with `/context` or `/remediate`, only profile-relevant operations are performed.

**Independent Test**: Run `/comply --profile access_control` and verify only AC-domain questions asked and only AC-domain remediations offered.

### Implementation for User Story 6

- [x] T031 [US6] Add `profile` parameter to `get_pending_context` handler in packages/darnit-baseline/src/darnit_baseline/tools.py — filter pending context to only include questions affecting the profile's control set
- [x] T032 [US6] Write integration test for profile-scoped context gathering in tests/darnit_baseline/test_profiles.py — verify that with a profile, only relevant context questions are returned
- [x] T033 [US6] Write integration test for profile-scoped remediation in tests/darnit_baseline/test_profiles.py — verify that with a profile, only relevant remediations are offered

**Checkpoint**: Profile filtering works across all three pipeline layers.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, validation, and cleanup

- [x] T034 [P] Register skills in project configuration — ensure `/audit`, `/context`, `/comply`, `/remediate` are discoverable as slash commands in Claude Code
- [x] T035 [P] Update CLAUDE.md with skills documentation — add skill descriptions to Active Technologies section
- [x] T036 Run `uv run ruff check .` and fix any linting issues in new/modified files
- [x] T037 Run `uv run pytest tests/ --ignore=tests/integration/ --ignore=tests/darnit_reproducibility/ -q` — verify all tests pass
- [x] T038 Run `uv run python scripts/validate_sync.py --verbose` — verify spec-implementation sync
- [x] T039 Validate quickstart.md scenarios work end-to-end in Claude Code

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 /audit (Phase 3)**: Depends on Foundational — MVP target
- **US2 /context (Phase 4)**: Depends on Foundational — can run in parallel with US1
- **US3 /comply (Phase 5)**: Depends on US1 + US2 (composes both skills)
- **US4 Profiles in TOML (Phase 6)**: Depends on Foundational — can run in parallel with US1/US2
- **US5 /remediate (Phase 7)**: Depends on Foundational — can run in parallel with US1/US2
- **US6 Profile-aware context/remediation (Phase 8)**: Depends on US4 + US5
- **Polish (Phase 9)**: Depends on all desired user stories being complete

### User Story Dependencies

- **US1 (/audit)**: Independent after Foundational
- **US2 (/context)**: Independent after Foundational
- **US3 (/comply)**: Depends on US1 + US2
- **US4 (Profiles TOML)**: Independent after Foundational
- **US5 (/remediate)**: Independent after Foundational
- **US6 (Profile-aware pipeline)**: Depends on US4 + US5

### Within Each User Story

- Skill `.md` file before parameter handling
- Python tool changes before tests
- Tests after implementation

### Parallel Opportunities

- T002, T003, T004 can run in parallel (different test files)
- T009, T010, T011 can run in parallel after T005-T008 (different test functions)
- US1 and US2 can run in parallel after Foundational
- US4 and US5 can run in parallel after Foundational
- T025, T026 can run in parallel (different test files)
- T034, T035 can run in parallel (different files)

---

## Parallel Example: After Foundational

```
# These can all start simultaneously after Phase 2:
Stream A: T012 → T013 → T014 → T015  (US1: /audit skill)
Stream B: T016 → T017                  (US2: /context skill)
Stream C: T020 → T021 → T022 → T023 → T024 → T025, T026 → T027  (US4: profiles)
Stream D: T028 → T029 → T030          (US5: /remediate skill)

# After US1 + US2 complete:
Stream E: T018 → T019                  (US3: /comply skill)

# After US4 + US5 complete:
Stream F: T031 → T032 → T033          (US6: profile-aware pipeline)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (profile schema + resolution)
3. Complete Phase 3: User Story 1 (/audit skill)
4. **STOP and VALIDATE**: Test `/audit` in Claude Code
5. This alone delivers the highest-value workflow

### Incremental Delivery

1. Setup + Foundational → Profile infrastructure ready
2. US1 (/audit) → Single-command audit (MVP!)
3. US2 (/context) → Guided context collection
4. US3 (/comply) → Full pipeline orchestration
5. US4 (Profiles TOML) → Named profiles for implementation authors
6. US5 (/remediate) → Standalone remediation skill
7. US6 (Profile-aware pipeline) → Profile filtering across all layers
8. Polish → Documentation, validation, cleanup

---

## Notes

- Skills are `.md` prompt templates — no compilation/build step needed
- Profile Python changes require linting (`ruff check`) and testing (`pytest`)
- Skill testing is manual via Claude Code — no automated test for prompt behavior
- Profile changes must not break existing MCP tools (SC-005)
- Commit after each task or logical group
