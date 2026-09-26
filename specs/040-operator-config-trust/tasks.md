# Tasks: Operator Configuration and Trust Model

**Input**: Design documents from `/specs/040-operator-config-trust/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included. The spec's success criteria (SC-001 to SC-006) are defined as test-suite outcomes, and the project works test-first. Write each story's tests before its implementation and confirm they fail first.

**Organization**: Tasks are grouped by user story so each story can be implemented and tested independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1-US5 map to the user stories in spec.md

## Path Conventions

- Core: `packages/darnit/src/darnit/`
- Baseline implementation: `packages/darnit-baseline/src/darnit_baseline/`
- Tests: `tests/darnit/`, `tests/darnit_baseline/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Spec-first documentation and package skeletons.

- [X] T001 Confirm the prerequisite change restricting repository-supplied configuration (`load_user_config(..., trusted=False)`) is merged on main; rebase this branch on it (plan.md "Sequencing and dependencies" step 1)
- [X] T002 Update `docs/architecture/framework-design.md` first: add sections for operator configuration, the repository trust boundary, project assertions and their outcomes (honored/pending/contradicted), and `contradicted_by` (constitution Development Workflow)
- [X] T003 [P] Create package skeleton `packages/darnit/src/darnit/config/operator/__init__.py` exporting the public loader API
- [X] T004 [P] Create package skeleton `packages/darnit/src/darnit/trust/__init__.py`
- [X] T005 [P] Create test package directories `tests/darnit/config/operator/__init__.py`, `tests/darnit/trust/__init__.py`, `tests/darnit/assertions/__init__.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Models and path resolution every story depends on.

**CRITICAL**: No user story work can begin until this phase is complete.

- [X] T006 [P] Write tests for the user config directory (XDG absolute-only rule, `~/.config` fallback on Linux and macOS, `%APPDATA%` on Windows, relative `XDG_CONFIG_HOME` ignored) in `tests/darnit/stores/test_platform_paths_config.py`
- [X] T007 Add `user_config_dir()` to `packages/darnit/src/darnit/stores/defaults/platform_paths.py` per research R1, and make existing XDG handling in that module ignore relative values
- [X] T008 [P] Write tests for `OperatorConfig` models (required `schema_version = 1`, unknown keys rejected with dotted key path, env values are variable names, defaults per data-model.md) in `tests/darnit/config/operator/test_schema.py`
- [X] T009 Implement `OperatorConfig` and nested models (`operator` with `identity`, `plugins`, `mcp_servers`, `controls`, `custom_controls`, `stores`, `llm`, `trust`, `policy`) with `extra="forbid"` in `packages/darnit/src/darnit/config/operator/schema.py` per contracts/operator-config.md
- [X] T010 [P] Write tests for `RepositoryIdentity` normalization (scp-like, `ssh://`, `https://`, trailing `.git`, ports and user info stripped, case folding for github.com, gitlab.com and operator-listed hosts, unknown aliases fail closed) in `tests/darnit/trust/test_identity.py`
- [X] T011 Implement `canonical_identity()` and `RepositoryIdentity` (with `source` and `trusted_eligible`) in `packages/darnit/src/darnit/trust/identity.py` per research R3

**Checkpoint**: Foundation ready. User story work can begin.

---

## Phase 3: User Story 1 - Operator configures darnit once, outside any repository (Priority: P1) MVP

**Goal**: One user-level operator configuration, found identically by CLI, MCP server, and harness; repository content cannot configure the tool.

**Independent Test**: quickstart.md sections 1 and 2.

### Tests for User Story 1

- [X] T012 [P] [US1] Write loader tests (resolution order explicit path > default location > built-in defaults; missing explicit path is an error; missing default file is not; digest and source recorded) in `tests/darnit/config/operator/test_loader.py`
- [X] T013 [P] [US1] Write containment tests (configuration path inside the audited repository refused after resolving symlinks and `XDG_CONFIG_HOME`; checked per audit target) in `tests/darnit/config/operator/test_containment.py`
- [X] T014 [P] [US1] Write permission-check tests (owner and group/world-write checks on file and parents; warn by default, refuse in strict mode; strict mode enabled by `--strict-operator-config`, by recognized CI, or by the file, and never disabled by the file; Windows not checkable) in `tests/darnit/config/operator/test_permissions.py`
- [X] T015 [P] [US1] Write the planted-configuration suite for SC-001: every setting a repository could try to supply (in `.baseline.toml`, `.project/`, and an operator-config-shaped file) has no effect and is listed in `ignored_repository_settings` in `tests/darnit/config/operator/test_repository_cannot_configure.py`
- [X] T016 [P] [US1] Write driver-parity tests for SC-002 (CLI, MCP tool function, harness report the same `operator_config.digest` and apply the same pass override) in `tests/darnit/config/operator/test_driver_parity.py`

### Implementation for User Story 1

- [X] T017 [US1] Implement `load_operator_config(explicit_path, audit_target, strict)` with resolution, validation errors naming file and dotted key, SHA-256 digest, containment check, and permission check (strict from the launch option or CI, or turned on by the file) in `packages/darnit/src/darnit/config/operator/loader.py`
- [X] T018 [US1] Apply operator configuration to effective configuration (operator pass overrides, custom controls, MCP servers, stores, plugin allow list and trusted publishers) with precedence defaults < operator < per-run flags in `packages/darnit/src/darnit/config/merger.py`
- [X] T019 [US1] Record `operator_config {source, digest, permission_check}` and `ignored_repository_settings [{file, key, new_home}]` in audit results in `packages/darnit/src/darnit/tools/audit.py`
- [X] T020 [US1] Add `--operator-config PATH` and `--strict-operator-config` to `audit`, `run`, and `harness` subcommands and wire it into config loading in `packages/darnit/src/darnit/cli.py`
- [X] T021 [US1] Add `--operator-config PATH` and `--strict-operator-config` to `darnit serve` (distinct from the positional framework config) and resolve operator configuration per audit call with the containment check in `packages/darnit/src/darnit/server/factory.py`
- [X] T022 [P] [US1] Pass operator configuration through MCP audit tools (`builtin_audit` and the baseline audit tool) in `packages/darnit/src/darnit/server/tools/builtin_audit.py` and `packages/darnit-baseline/src/darnit_baseline/tools.py`
- [X] T023 [US1] Load operator configuration in the harness, apply its `llm` settings (provider, model, budget) to the LLM step, and include it in the report in `packages/darnit/src/darnit/harness/driver.py` and `packages/darnit/src/darnit/core/llm_step.py`
- [X] T024 [US1] Pass operator configuration through the remaining audit-running paths -- the organization sweep, the ActionPlan MCP tools, and the attestation tool -- in `packages/darnit/src/darnit/tools/audit_org.py`, `packages/darnit/src/darnit/server/tools/harness_loop.py`, and `packages/darnit-baseline/src/darnit_baseline/tools.py`
- [X] T025 [US1] Warn in MCP tool results when the server's working directory or the agent-reported project directory lies inside the audited repository in `packages/darnit/src/darnit/server/factory.py`
- [X] T026 [US1] Implement `darnit config show` (source, digest, permission check, effective settings with secrets redacted) in `packages/darnit/src/darnit/cli.py`
- [X] T027 [US1] Change `darnit install` to write user-scope MCP registrations by default; require an explicit flag with a warning for project scope in `packages/darnit/src/darnit/cli.py`

**Checkpoint**: User Story 1 is functional and testable on its own (MVP).

---

## Phase 4: User Story 4 - CI runs apply trust according to the triggering event (Priority: P2, built before US3 because US3's trust gate depends on it)

**Goal**: Trust decisions from operator `trust.repos` plus CI rules, using identity from the operator target or CI metadata only.

**Independent Test**: quickstart.md section 4.

### Tests for User Story 4

- [X] T028 [P] [US4] Write CI detection tests with GitHub event-payload fixtures (default-branch push trusted when the rule is configured; pull_request, pull_request_target, workflow_run, merge_group untrusted; fork detection by head vs base repository id; unknown event untrusted) in `tests/darnit/trust/test_ci_github.py`
- [X] T029 [P] [US4] Write GitLab CI detection tests (`CI_PIPELINE_SOURCE=push` with `CI_COMMIT_BRANCH == CI_DEFAULT_BRANCH` trusted; any merge-request context untrusted) in `tests/darnit/trust/test_ci_gitlab.py`
- [X] T030 [P] [US4] Write trust-decision tests (identity from operator target or CI metadata only; checkout remotes are `checkout_hint` and never trusted; `upstream` remote never preferred; target/remote mismatch reported; reason strings per data-model.md) in `tests/darnit/trust/test_decision.py`

### Implementation for User Story 4

- [X] T031 [P] [US4] Implement CI platform and event detection and the `push-default-branch` rule (including HEAD equals the CI commit check) in `packages/darnit/src/darnit/trust/ci.py` per research R4
- [X] T032 [US4] Implement `decide_trust(target, operator_config, checkout)` producing `TrustDecision` with `ci_facts` in `packages/darnit/src/darnit/trust/decision.py`
- [X] T033 [US4] Stop preferring an `upstream` remote and keep the host in parsed identities; mark checkout-derived identity as a hint only in `packages/darnit/src/darnit/core/utils.py` (`detect_repo_from_git`, `_parse_github_url`)
- [X] T034 [US4] Accept an explicit `--repo HOST/NS/NAME` target on CLI and harness and an optional `host` argument on MCP audit tools; record `trust {repository, identity_source, trusted, reason, ci_facts}` in results in `packages/darnit/src/darnit/cli.py`, `packages/darnit/src/darnit/harness/driver.py`, and `packages/darnit/src/darnit/tools/audit.py`
- [X] T035 [US4] Record a trust decision for every audit-running path not covered by T034: in the organization sweep use each enumerated repository as the operator target (identity source `operator_target`), and include the decision in the ActionPlan tools and attestation tool, in `packages/darnit/src/darnit/tools/audit_org.py`, `packages/darnit/src/darnit/server/tools/harness_loop.py`, and `packages/darnit-baseline/src/darnit_baseline/tools.py`
- [X] T036 [US4] Implement `darnit config trust add|list|remove` editing only `[trust].repos` in the operator configuration file in `packages/darnit/src/darnit/cli.py`

**Checkpoint**: Trust decisions are reported for every run.

---

## Phase 5: User Story 2 - Project assertions live in .project/ (Priority: P1)

**Goal**: Not-applicable claims read from `.project/darnit.yaml`, reported as the project's assertions with reason and asserter.

**Independent Test**: quickstart.md section 3 step 1 (reporting fields only).

### Tests for User Story 2

- [X] T037 [P] [US2] Write tests for reading claims from `.project/darnit.yaml` `controls` (optional `asserted_by`, default `repository content`, unknown control id reported and ignored, missing reason recorded) in `tests/darnit/assertions/test_project_assertions.py`
- [X] T038 [P] [US2] Write tests that darnit-written `.project/` files still conform to the upstream schema after adding `asserted_by` (darnit data only in the extension file) in `tests/darnit/assertions/test_project_schema_conformance.py`

### Implementation for User Story 2

- [X] T039 [US2] Add optional `asserted_by` to the `.project/darnit.yaml` control override model in `packages/darnit/src/darnit/config/schema.py`
- [X] T040 [US2] Implement `collect_assertions(project_config, framework)` returning `ProjectAssertion` records (explicit claims) in `packages/darnit/src/darnit/trust/assertions.py`
- [X] T041 [US2] Make audit paths read project assertions from `.project/` instead of repository `.baseline.toml` status overrides, and unify the currently divergent N/A handling so every driver path reports assertion-backed results the same way, in `packages/darnit/src/darnit/tools/audit.py` and `packages/darnit/src/darnit/config/control_loader.py`

**Checkpoint**: Claims are read from `.project/` and reported with their origin.

---

## Phase 6: User Story 3 - Not-applicable claims count only when trusted and uncontradicted (Priority: P1)

**Goal**: The honored/pending/contradicted state machine, context-value assertions, operator-side confirmations, and labelling in reports and attestations.

**Independent Test**: quickstart.md section 3 steps 1-5.

### Tests for User Story 3

- [ ] T042 [P] [US3] Write state-machine tests (trusted + reason + no contradiction = honored; untrusted = pending; missing reason = pending; declared evidence unobtainable = pending; contradicted = claim ignored and evidence reported) in `tests/darnit/assertions/test_outcomes.py`
- [ ] T043 [P] [US3] Write context-value assertion tests (a `.project/` context value that would make controls not applicable is an assertion per affected control with origin `context_value:<key>`; untrusted repository gets pending for each) in `tests/darnit/assertions/test_context_value_assertions.py`
- [ ] T044 [P] [US3] Write confirmation-store tests (stored under the data root keyed by identity, control, claim, evidence digest; applies only on exact match; lapses on expiry and on evidence change; never written to the audited repository) in `tests/darnit/trust/test_confirmations.py`
- [ ] T045 [P] [US3] Write compliance-math tests for SC-003 (untrusted repository: zero reduction of the compliance denominator before confirmation) and SC-004 (contradicted claims never honored) in `tests/darnit/assertions/test_compliance_effects.py`
- [ ] T046 [P] [US3] Write attestation-labelling tests for SC-006 (every assertion-backed N/A carries `authority: asserted`, `asserted_by`, and confirmation fields when present) in `tests/darnit_baseline/attestation/test_asserted_results.py`

### Implementation for User Story 3

- [ ] T047 [US3] Add `contradicted_by` to the control schema (reference to a context key's detection with a refuting value, or a named check) in `packages/darnit/src/darnit/config/framework_schema.py`
- [ ] T048 [US3] Implement outcome evaluation (`honored`, `pending`, `contradicted`) using `TrustDecision`, declared evidence, and confirmations in `packages/darnit/src/darnit/trust/assertions.py`
- [ ] T049 [US3] Treat applicability-changing context values read from `.project/` as assertions for each control their applicability conditions would make not applicable (FR-013a) in `packages/darnit/src/darnit/trust/assertions.py` and the applicability evaluation in `packages/darnit/src/darnit/tools/audit.py`
- [ ] T050 [US3] Implement the operator-side confirmation store in `packages/darnit/src/darnit/trust/confirmations.py` using the data root from `packages/darnit/src/darnit/stores/defaults/platform_paths.py`; record `confirmed_by` from `operator.identity` (else the OS user) and compute `expires_at` from `policy.confirmation_expiry_days`
- [ ] T051 [US3] Emit per-control `assertion {outcome, origin, reason, asserted_by, location, confirmation, contradiction}` and apply compliance effects (honored excluded, pending non-compliant) in `packages/darnit/src/darnit/tools/audit.py` (`calculate_compliance` and result assembly)
- [ ] T052 [US3] Extend the confirmation MCP tool to confirm a pending claim by `control_id` and claim, writing to the operator-side store, in `packages/darnit/src/darnit/server/tools/project_data.py`
- [ ] T053 [US3] Make remediation use assertion outcomes instead of raw `.project/darnit.yaml` N/A overrides: skip remediation only for honored claims, never for pending or contradicted ones, in `packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py`
- [ ] T054 [P] [US3] Declare `contradicted_by` release evidence on release-dependent controls and correct the `affects` list of the release context key to include every control that depends on it in `packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml`
- [ ] T055 [US3] Label assertion-backed N/A results in the attestation predicate (`authority: asserted`, `asserted_by`, `confirmed_by`, `confirmed_at`) and treat pending as non-compliant, coordinating with #492, in `packages/darnit-baseline/src/darnit_baseline/attestation/predicate.py`
- [ ] T056 [US3] Render assertion outcomes in markdown and summary outputs (asserted/pending/contradicted with reason and asserter) in `packages/darnit/src/darnit/tools/audit.py`

**Checkpoint**: Compliance math honors claims only under the trust and evidence rules.

---

## Phase 7: User Story 5 - Existing .baseline.toml users migrate with clear guidance (Priority: P2)

**Goal**: Deprecation-period reading, per-setting warnings, and a migration command.

**Independent Test**: quickstart.md section 5.

### Tests for User Story 5

- [ ] T057 [P] [US5] Write deprecation tests (only per-control status/reason read, treated as assertions under the US3 rules; one warning per setting naming its new home; file ignored with a notice after the deprecation flag flips) in `tests/darnit/config/operator/test_baseline_deprecation.py`
- [ ] T058 [P] [US5] Write migration tests (claims written to `.project/darnit.yaml`; proposed operator fragment printed; operator configuration file untouched; existing claims not overwritten without `--force`) in `tests/darnit/config/operator/test_migrate.py`

### Implementation for User Story 5

- [ ] T059 [US5] Implement deprecation-period reading of `.baseline.toml` assertions and the per-setting warning, behind a single release-controlled switch, in `packages/darnit/src/darnit/config/merger.py`
- [ ] T060 [US5] Implement migration logic in `packages/darnit/src/darnit/config/operator/migrate.py` and the `darnit config migrate [REPO] [--force]` command in `packages/darnit/src/darnit/cli.py`
- [ ] T061 [US5] Replace `.baseline.toml` as the parity-corpus fixture marker and migrate fixture files in `tests/darnit/parity/tier1/fixture_meta.py`, `tests/darnit/parity/tier1/conftest.py`, and `tests/darnit/parity/fixtures/`
- [ ] T062 [US5] Migrate remaining tests that construct `.baseline.toml` for tool settings to operator configuration fixtures, and those that assert exclusions to `.project/` claims (test modules listed in research R8), in `tests/`
- [ ] T063 [P] [US5] Update `darnit init` so it no longer creates `.baseline.toml` and instead explains `.project/` claims and operator configuration in `packages/darnit/src/darnit/cli.py`

**Checkpoint**: All user stories are independently functional.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T064 [P] Update `docs/SECURITY_GUIDE.md` configuration sections to describe operator configuration, user-scope registration, trust lists, and CI rules; remove repository-configuration guidance
- [ ] T065 [P] Update agent skills to recommend user-scope registration and describe pending claims and confirmation in `packages/darnit/src/darnit/skills/darnit-audit/SKILL.md`, `darnit-comply/SKILL.md`, `darnit-data/SKILL.md`, and `darnit-remediate/SKILL.md`
- [ ] T066 [P] Update `CLAUDE.md` Context System and Technology Stack sections to replace `.baseline.toml` user overrides with operator configuration and `.project/` claims
- [ ] T067 [P] Add a CHANGELOG entry describing operator configuration, the deprecation of `.baseline.toml`, and the new `config` subcommands in `CHANGELOG.md`
- [ ] T068 Run quickstart.md end to end against scratch repositories and record results in `specs/040-operator-config-trust/quickstart.md` (append a "Validation log" section)
- [ ] T069 Run `uv run ruff check .`, `uv run pytest tests/ --ignore=tests/integration/ -q`, and `uv run python scripts/validate_sync.py --verbose`; fix failures
- [ ] T070 File the upstream `.project/` proposal for an exemption/applicability field and link it from `specs/040-operator-config-trust/research.md` R6

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: none; T001 must be satisfied before merging this feature.
- **Foundational (Phase 2)**: after Setup; blocks all stories.
- **US1 (Phase 3)**: after Foundational. MVP.
- **US4 (Phase 4)**: after Foundational; independent of US1 except that results fields live in the same result assembly (T019, T034).
- **US2 (Phase 5)**: after Foundational.
- **US3 (Phase 6)**: after US2 (assertions) and US4 (trust decisions).
- **US5 (Phase 7)**: after US2 and US3 (deprecated claims follow the same rules); T061-T062 can start after US1.
- **Polish (Phase 8)**: after the stories it documents.

### Story completion order

US1 -> (US4 and US2 in parallel) -> US3 -> US5 -> Polish

### Within each story

Tests first (they must fail), then models, then services, then driver wiring, then outputs.

## Parallel Opportunities

- Phase 1: T003, T004, T005 together.
- Phase 2: T006, T008, T010 (tests) together; then T007, T009, T011 in different files.
- US1: T012-T016 together; T022 alongside T020-T021 (T024 follows T022, same file).
- US4: T028-T030 together; T031 alongside T033.
- US2: T037-T038 together.
- US3: T042-T046 together; T054 alongside T047-T052.
- US5: T057-T058 together; T063 alongside T059-T060.
- Polish: T064-T067 together.

### Parallel example: User Story 3 tests

```text
Task: "State-machine tests in tests/darnit/assertions/test_outcomes.py"
Task: "Context-value assertion tests in tests/darnit/assertions/test_context_value_assertions.py"
Task: "Confirmation-store tests in tests/darnit/trust/test_confirmations.py"
Task: "Compliance-math tests in tests/darnit/assertions/test_compliance_effects.py"
Task: "Attestation-labelling tests in tests/darnit_baseline/attestation/test_asserted_results.py"
```

## Implementation Strategy

### MVP first

1. Phase 1 and Phase 2.
2. Phase 3 (US1): operator configuration in every driver; repository content cannot configure the tool.
3. Stop and validate with quickstart.md sections 1-2. This alone gives operators a supported home for the settings no longer read from repositories.

### Incremental delivery

1. US1 (MVP).
2. US4 and US2 in parallel: trust decisions reported; claims read from `.project/` and labelled.
3. US3: claims affect compliance only under the trust and evidence rules; confirmations.
4. US5: deprecation and migration, then flip `.baseline.toml` to ignored in the following minor release.
5. Polish.

### Notes

- Tasks marked [P] touch different files and have no dependency on incomplete tasks.
- Keep all documentation ASCII-only.
- Commit with DCO sign-off (`git commit -s`).
