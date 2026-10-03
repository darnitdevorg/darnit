# Tasks: Remediation Safety

**Input**: Design documents from `/specs/043-remediation-safety/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included. Success criteria SC-001 to SC-007 are reproducible test outcomes (0 weakened settings, 0 unapproved writes, byte-identical user files, preview equals apply), and the project works test-first. Write each story's tests first and confirm they fail.

**Organization**: Grouped by user story so each story can be implemented and verified independently. The plan/apply protocol and the single writer are foundational because every story reads or writes through them.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1-US5 map to the user stories in spec.md

## Path Conventions

- Core: `packages/darnit/src/darnit/`
- Baseline implementation: `packages/darnit-baseline/src/darnit_baseline/`
- CSL implementation: `packages/darnit-csl/src/darnit_csl/`
- Reproducibility implementation: `packages/darnit-reproducibility/src/darnit_reproducibility/`
- Tests: `tests/darnit/`, `tests/darnit_baseline/`, `tests/darnit_csl/`

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 Update `docs/architecture/framework-design.md` first, per contracts/remediation-interfaces.md and data-model.md. Run `uv run python scripts/validate_sync.py --verbose` afterwards.
  - Section 4: the plan/apply protocol for remediation handlers (`HandlerContext.mode`, the `FileChange`/`ChangeSet` outputs, the executor as single writer, `supports_plan`).
  - The new `platform_setting` handler, with requirement keys per target and the "never weaken" rule.
  - The `exec` remediation `effects`/`offline` fields, and the rule that an exec remediation never changes platform state.
  - `file_create.project_reference`.
  - Removal of `api_call` (section 4.4), `requires_confirmation`, `dry_run_supported`, `dry_run_command`.
  - `safe = false` meaning individual approval.
  - A new section on the remediation policy (`[remediation] platform`/`high_impact`: `prompt`/`manual`/`auto`) and digest-bound approval.
  - Remediation outcome kinds and the re-check rule.
  - Git rules: manifest-only commits, no stash, refused states, the `Darnit-Remediation-Run` trailer.
  - The `exec` example that uses `gh api -X PUT` in section 4.3 must be replaced.
- [X] T002 [P] Extend the `gh` test seam: change the responder signature to `(method, endpoint, body) -> (body, status, error)`, keeping GET-only callers working. Make `RecordedGhApi` serve keys like `"PUT /repos/o/r/branches/main/protection"` and record request bodies in `.calls`. Files: `packages/darnit/src/darnit/core/utils.py` and `tests/darnit/core/test_gh_responder.py`.
- [X] T003 [P] Create platform fixtures as `RecordedGhApi` response sets in `tests/darnit/remediation/platform/conftest.py`, with an empty `tests/darnit/remediation/platform/__init__.py`. Use research R12 and quickstart V1:
  - `unprotected`;
  - `stricter` (2 approvals, required checks with `checks[]`, push restrictions with users/teams/apps, code-owner review, linear history, conversation resolution);
  - `satisfied`;
  - `ruleset_only`;
  - `read_only_token` (GETs 200, writes 403);
  - `read_failure` (GET 0/502);
  - `unknown_field` (protection GET with an extra key);
  - `default_branch_release` (`default_branch = "release"`);
  - `private_repo`;
  - `pvr_disabled`.
- [X] T004 [P] Create scratch git repository builders in `tests/darnit/server/conftest.py`, reusing the tree-snapshot helper from `tests/darnit/context_integrity/conftest.py` (move it to `tests/conftest_helpers.py` if needed):
  - `R-dirty`: a modified tracked file, an untracked `.env`, one stash;
  - `R-detached`;
  - `R-merging`: `MERGE_HEAD` present;
  - `R-foreign-branch`: an existing `fix/compliance` with a commit without the trailer;
  - a bare remote for push tests.

---

## Phase 2: Foundational (Blocking Prerequisites)

**CRITICAL**: No user story work can begin until this phase is complete.

- [X] T005 [P] Write model tests in `tests/darnit/remediation/test_plan_model.py`:
  - `FileChange`, `PlanItem`, `RemediationOutcome` and `RemediationRun` validate per data-model.md (`extra="forbid"`; outcome `kind` vocabulary);
  - digests are canonical JSON with `sort_keys` and are stable under dict reordering;
  - `RemediationRun.summary` is computed from `outcomes` only.
- [X] T006 [P] Write operator-config tests in `tests/darnit/config/operator/test_remediation_settings.py`:
  - `[remediation]` absent means `platform = "prompt"`, `high_impact = "prompt"`;
  - `manual` and `auto` are accepted;
  - unknown keys or values stop loading;
  - `darnit config show` prints the section.
- [X] T007 [P] Write manifest tests in `tests/darnit/remediation/test_manifest.py`:
  - the manifest is written under `user_data_root()/remediation/<repository-identity>/<run_id>.json` with mode 0600;
  - a path inside the checkout is refused;
  - the latest run for a repository is found by `run_id=None`;
  - the file list carries `after_digest`.
- [X] T008 [P] Write executor plan/apply tests in `tests/darnit/remediation/test_executor_plan_apply.py`:
  - in `plan` mode, `file_create`, `yaml_inject` and `project_update` return `FileChange`s and the tree snapshot is unchanged (including `yaml_inject`, #166);
  - in `apply` mode the executor writes exactly the planned `FileChange`s and records them in the manifest;
  - a handler that does not declare `supports_plan` is reported as `previewable = False` and is not run in `plan` mode;
  - `file_create` on an existing file yields `action = "none"`, `reason = "already_exists"`.
- [X] T009 [P] Add `FileChange`, `PlanItem`, `RemediationOutcome`, `RemediationRun`, and the digest helper per data-model.md in `packages/darnit/src/darnit/remediation/plan.py`.
- [X] T010 [P] Add `RemediationSettings` (`platform`, `high_impact`: `Literal["prompt", "manual", "auto"]`, default `"prompt"`) to `OperatorConfig`, and print it in `darnit config show`. Files: `packages/darnit/src/darnit/config/operator/schema.py` and `packages/darnit/src/darnit/cli.py`.
- [X] T011 [P] Implement the operator-side run manifest in `packages/darnit/src/darnit/remediation/manifest.py`: `start_run`, `record_file`, `record_change_set`, `set_commit`, `load_run(repository, run_id=None)`. Use the 040 data root and its atomic, 0600, outside-checkout rules (pattern: `trust/confirmations.py`).
- [X] T012 Add `mode: Literal["plan", "apply"] = "apply"` to `HandlerContext`, and a `supports_plan: bool = False` registration flag, in `packages/darnit/src/darnit/sieve/handler_registry.py`.
- [X] T013 Register the `manual` remediation handler with `supports_plan=True` (it has no side effects, so manual remediations stay previewable and batch-eligible). Make `file_create`, `yaml_inject` and `project_update` compute and return their `FileChange`s in evidence (`evidence["file_changes"]`) in both modes and never write themselves, and register them with `supports_plan=True`. Include the resulting content and the reasons `already_exists` and `when_not_met`. File: `packages/darnit/src/darnit/sieve/builtin_handlers.py`.
- [X] T014 Rework `RemediationExecutor` as the single writer, in `packages/darnit/src/darnit/remediation/executor.py`:
  - `plan` mode runs handlers with `mode="plan"` and returns `PlanItem`s; this replaces the "Would execute handler" short-circuit at the dry-run branch;
  - `apply` mode runs the plan, writes the `FileChange`s atomically, and records each in the manifest;
  - the pre-render confirmation pass from 042 is kept;
  - only a definite success with a non-empty change counts as changed; INCONCLUSIVE, ERROR, not-run and `action = "none"` never count.
- [X] T015 Add `gh_api_write(method, endpoint, payload) -> (body, status, error)` in `packages/darnit/src/darnit/core/utils.py`. It sends JSON with `gh api -X METHOD --input -`, reads the status from `--include`, and goes through the responder seam (T002).

**Checkpoint**: Plan/apply and the single writer exist and pass their tests. Existing remediation callers still work through `apply` mode.

---

## Phase 3: User Story 1 - Platform settings change only by approved, minimal changes (Priority: P1) MVP

**Goal**: Every platform write reads first, changes only what the control needs without weakening anything, runs under the operator policy with a digest-bound approval, and is verified by a read-back.

**Independent Test**: quickstart.md V1 and V2.

### Tests for User Story 1

- [ ] T016 [P] [US1] Write branch-protection planner tests in `tests/darnit/remediation/platform/test_branch_protection.py`:
  - `unprotected`: one PUT that sets only the required fields.
  - `stricter`: the plan for `require_pull_request` + `prevent_deletion` + `require_approvals = 1` lists only `allow_deletions: true -> false`; the PUT body preserves every other field, including `checks[]`, restriction logins/slugs, code-owner review and linear history (SC-001).
  - `satisfied` and `ruleset_only`: no operations; `satisfied_by` is `already` or `ruleset`.
  - `unknown_field`: ERROR "cannot preserve unknown protection setting"; no operation.
  - `read_failure` and an unreadable default branch: ERROR with cause; no operation (FR-002).
  - `default_branch_release`: the target is `release` (FR-007).
  - Review count is raised through `PATCH .../required_pull_request_reviews` and never lowered.
  - `enforce_admins` uses `POST .../enforce_admins` only when it is off; `require_status_checks` adds only missing contexts and keeps existing `contexts` and `checks`.
- [ ] T017 [P] [US1] Write GET-to-PUT translator round-trip tests in `tests/darnit/remediation/platform/test_protection_translate.py`: every known field of a recorded protection GET maps to the PUT shape and back without loss, and an unrecognised key raises.
- [ ] T018 [P] [US1] Write tests for the `repository` and `vulnerability_reporting` targets in `tests/darnit/remediation/platform/test_targets.py`:
  - `private_repo` with `visibility = "public"` gives a PATCH with only that field, class `high_impact`, and impact notes;
  - an already-public repo gives no operation;
  - `pvr_disabled` gives `PUT .../private-vulnerability-reporting`;
  - an already-enabled state gives no operation.
- [ ] T019 [P] [US1] Write policy and approval tests in `tests/darnit/remediation/platform/test_policy.py` and `tests/darnit/remediation/platform/test_approval.py` (SC-002):
  - `prompt` without a digest gives `needs_approval` and 0 writes;
  - `prompt` with the digest gives exactly the planned writes;
  - a digest recorded against a different observed state gives `unchanged` (`stale_preview`) and 0 writes;
  - a batch approval does not cover a high-impact change set;
  - `manual` gives 0 writes and steps in the outcome;
  - `auto` writes without a digest and records the policy;
  - a `[remediation]` table in the audited repository's files is ignored;
  - `read_only_token` gives an error and 0 changed fields after read-back;
  - a partial write (the reviews PATCH succeeds, the following PUT is rejected) gives outcome `error` listing exactly the one changed field from the read-back, and the control is not `fixed`;
  - a repository on a forge other than GitHub gives outcome `manual` with 0 platform calls.
- [ ] T020 [P] [US1] Write `enable_branch_protection` tool tests in `tests/darnit_baseline/test_enable_branch_protection.py`:
  - the default call previews only;
  - `branch=None` uses the default branch;
  - passing `required_approvals=1` against `stricter` keeps 2;
  - `status_checks` add to the existing checks and never remove any;
  - the tool and the TOML `platform_setting` for AC-03.01 produce the same change set (FR-009).

### Implementation for User Story 1

- [ ] T021 [P] [US1] Implement `PlatformTarget`, `ObservedState`, `ChangeOperation`, `FieldChange`, `ChangeSet` and the digests per data-model.md in `packages/darnit/src/darnit/remediation/platform/model.py`, with an `__init__.py`.
- [ ] T022 [US1] Implement the targets in `packages/darnit/src/darnit/remediation/platform/targets.py` (research R2, R3):
  - **Readers:** default branch from `GET /repos`; `GET .../branches/{b}` (`protected`); protection GET; `GET .../rules/branches/{b}`; repo GET; PVR GET.
  - **Translator:** total over the known field list from research; raises on unknown keys.
  - **Comparators:** booleans toward the required value; counts as minimums; status-check contexts as a superset.
  - **Granular writes:** `enforce_admins` via `POST .../enforce_admins`; missing status-check contexts via `POST .../required_status_checks/contexts` (or `PATCH .../required_status_checks` when none are configured).
  - **Planners:** unprotected means one PUT; protected means the reviews PATCH, plus one translated full PUT only for `prevent_deletion`/`prevent_force_push`; all requirements on one branch merge into one change set; impact class and impact notes per target.
- [ ] T023 [US1] Implement policy resolution and approval matching in `packages/darnit/src/darnit/remediation/platform/policy.py`:
  - the policy comes from `resolve_operator_config(...)`, never from the repository;
  - `prompt` requires the change set's own digest, and a high-impact change set is never covered by a batch approval;
  - approvals are recorded with the 040 operator identity and a timestamp.
- [ ] T024 [US1] Implement the engine in `packages/darnit/src/darnit/remediation/platform/engine.py`:
  - `plan(targets, requirements) -> list[ChangeSet]`;
  - `apply(change_sets, approvals, policy)`: re-read, re-plan and compare digests; write with `gh_api_write`; read back; derive the result from the read-back (FR-006); record applied change sets in the manifest.
  - Errors use the 041 `error.class`/`cause`.
  - A repository whose canonical identity is not on GitHub gives a `manual` outcome with the steps and makes no platform call.
- [ ] T025 [US1] Register the `platform_setting` remediation handler (`supports_plan=True`; `ChangeSet`s in evidence; apply through the engine) in `packages/darnit/src/darnit/sieve/builtin_handlers.py`. Add its schema (`target`, `require`, optional `branch`; unknown requirement keys rejected) in `packages/darnit/src/darnit/config/framework_schema.py`.
- [X] T025a [US1] Amend `.specify/memory/constitution.md` (PATCH, 1.3.0 to 1.3.1) so Architecture Constraints Layer 2 lists the built-in remediation actions as `file_create`, `exec`, `platform_setting`, `project_update`, `yaml_inject` (no `api_call`). Add a Sync Impact Report entry, and do it before T026.
- [ ] T026 [US1] Remove the `api_call` handler and its schema section. A TOML that uses it fails validation with a message naming `platform_setting`. Files: `packages/darnit/src/darnit/sieve/builtin_handlers.py`, `packages/darnit/src/darnit/config/framework_schema.py`, `tests/darnit/sieve/test_builtin_handlers.py` (drop the api_call cases).
- [ ] T027 [US1] Migrate the Baseline TOML in `packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml`:
  - AC-03.01 gets `require_pull_request`, AC-03.02 gets `prevent_deletion`, QA-07.01 gets `require_approvals = 1`, QA-01.01 gets `visibility = "public"`, and VM-03.01 gets `enabled = true`, each as a `platform_setting`;
  - AC-01.01 becomes a manual-only remediation, with steps that state collaborators and bots without 2FA are removed;
  - AC-02.01's remediation is removed (manual guidance only, #513);
  - delete `templates/*_payload.tmpl` (7) and their `[templates.*_payload]` entries.
- [ ] T028 [US1] Reimplement `enable_branch_protection` as a wrapper that turns its parameters into requirements and calls the engine (`dry_run=True`, `branch=None`, `approve`). Remove the fixed protection object and the subprocess PUT. Files: `packages/darnit/src/darnit/remediation/github.py`, and the MCP tool in `packages/darnit-baseline/src/darnit_baseline/tools.py`.
- [ ] T029 [US1] Add `approve: list[str] | None` to `remediate_audit_findings` and pass approvals and the operator policy through the orchestrator into the executor and the engine. Return the run id and change-set digests in the response JSON block. Files: `packages/darnit-baseline/src/darnit_baseline/tools.py` and `packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py`.
- [ ] T030 [US1] Make `darnit run` follow the policy for platform changes in `packages/darnit/src/darnit/cli.py` and `packages/darnit/src/darnit/agent/graph.py`. Under `prompt` with a TTY, show each change set and ask on `/dev/tty` (the feature 027 pattern). Without a TTY, the outcome is `needs_approval` with no write.
- [ ] T031 [US1] Update `packages/darnit/src/darnit/skills/darnit-remediate/SKILL.md` and `packages/darnit/src/darnit/skills/darnit-comply/SKILL.md`:
  - show the preview, including before/after fields, impact notes and digests;
  - ask the person;
  - pass back only the digests they approved;
  - never pass `dry_run=false` as a substitute for approval.

**Checkpoint**: SC-001 and SC-002 hold. No path writes platform settings except through the engine.

---

## Phase 4: User Story 2 - Remediation commits contain only remediation's own changes (Priority: P1)

**Goal**: Commits contain exactly the run's manifest files. User changes and stashes are never touched, and unsafe repository states are refused.

**Independent Test**: quickstart.md V3.

### Tests for User Story 2

- [ ] T032 [P] [US2] Write git safety tests on `R-dirty` in `tests/darnit/server/test_git_operations_safety.py` (SC-003). Apply remediation with `branch_name`, `auto_commit` and `create_pr` against the bare remote, then check:
  - the commit's files equal the manifest's;
  - the modified file and `.env` are uncommitted and byte-identical;
  - `git stash list` is unchanged;
  - the trailer is present;
  - only the remediation branch was pushed.
- [ ] T033 [P] [US2] Write refusal and conflict tests in `tests/darnit/server/test_git_operations_refusals.py`:
  - `R-detached`, `R-merging` and `R-foreign-branch` are each refused with a snapshot unchanged;
  - switching to an existing branch with a dirty tree is refused;
  - a target file with uncommitted user changes gives `FileChange(action="none", reason="user_changes_present")`, not written (FR-011);
  - an ignored target is not staged (FR-014);
  - a manifest file edited after remediation is not committed, and a conflict is reported.

### Implementation for User Story 2

- [ ] T034 [US2] Before applying a `FileChange`, check `git status --porcelain -- <path>` and `git check-ignore`. A path with user changes is not written (`action = "none"`, `reason = "user_changes_present"`); an ignored path is written with `ignored = true` and is never staged. File: `packages/darnit/src/darnit/remediation/executor.py`.
- [ ] T035 [US2] Rewrite `create_remediation_branch_impl` in `packages/darnit/src/darnit/server/tools/git_operations.py`:
  - never stash or drop;
  - a new branch uses `git checkout -b` from HEAD;
  - an existing branch requires a clean tree and only trailer-carrying commits beyond the base;
  - refuse on detached HEAD, `MERGE_HEAD`, `rebase-merge` or `rebase-apply`;
  - record the branch in the manifest.
- [ ] T036 [US2] Rewrite `commit_remediation_changes_impl` in `packages/darnit/src/darnit/server/tools/git_operations.py`:
  - take `run_id`; remove `add_all`;
  - stage the manifest paths with explicit pathspecs, only where the current digest equals `after_digest`, never ignored paths;
  - add the `Darnit-Remediation-Run` trailer;
  - list every committed file;
  - record the commit in the manifest.
- [ ] T037 [US2] Make `create_remediation_pr_impl` take `run_id`, push only the manifest's branch, and diff against the branch's base, not a hard-coded `main`. File: `packages/darnit/src/darnit/server/tools/git_operations.py`.
- [ ] T038 [US2] When any git step is requested (`branch_name`, `auto_commit` or `create_pr`), run the repository-state checks from T035 (detached HEAD, merge or rebase in progress, an existing branch with foreign commits, a dirty tree when switching) before applying any remediation, and stop with nothing changed if one fails (FR-013, US2 scenario 3). Pass the run id from `remediate_audit_findings` to the branch, commit and PR steps, and expose `run_id` on the three MCP git tools. Files: `packages/darnit-baseline/src/darnit_baseline/tools.py` and the tool registration in `packages/darnit/src/darnit/server/`.

**Checkpoint**: SC-003 holds.

---

## Phase 5: User Story 3 - Remediation never rewrites unrelated project references (Priority: P2)

**Goal**: References are declared next to the file they describe, and are recorded only for files created in the run, into an empty or equal field.

**Independent Test**: quickstart.md V4.

### Tests for User Story 3

- [ ] T039 [P] [US3] Write reference tests in `tests/darnit_baseline/test_project_reference.py` (SC-006):
  - with `security.policy: SECURITY.md` already set, remediating DO-02.01 leaves it unchanged and the outcome says why;
  - a created file whose field is empty is recorded;
  - a skipped (already-existing) file records nothing;
  - a platform-only remediation records nothing;
  - every `project_reference` in the Baseline TOML matches the field's `DEFAULT_FILE_LOCATIONS` patterns.

### Implementation for User Story 3

- [ ] T040 [US3] Add optional `project_reference` to the `file_create` schema in `packages/darnit/src/darnit/config/framework_schema.py`. After apply, record it in the executor only if the file was created in this run (manifest) and the field is empty or equal. Use the 042 round-trip writer, in `packages/darnit/src/darnit/remediation/executor.py`, and narrow `update_config_after_file_create` accordingly in `packages/darnit/src/darnit/config/resolver.py`.
- [ ] T041 [US3] Declare `project_reference` on the Baseline `file_create` handlers whose file matches a field (VM-02.01, GV-03.01/02, GV-04.01, DO-03.01, and the correct fields for README, GOVERNANCE.md, MAINTAINERS.md, CODE_OF_CONDUCT.md and LICENSE). Declare none for the bug-report template. Remove `CONTROL_REFERENCE_MAPPING` and its orchestrator call. Files: `packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml`, `packages/darnit-baseline/src/darnit_baseline/config/mappings.py`, `packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py`.

**Checkpoint**: SC-006 holds.

---

## Phase 6: User Story 4 - Outcomes say what actually happened (Priority: P2)

**Goal**: Typed per-control outcomes, a cache-neutral re-check, and every report and gate derived from outcomes.

**Independent Test**: quickstart.md V5.

### Tests for User Story 4

- [ ] T042 [P] [US4] Write outcome tests on a mixed fixture in `tests/darnit_baseline/remediation/test_outcomes.py` (SC-004):

  | Fixture case | Expected outcome |
  |---|---|
  | SECURITY.md exists | `unchanged` / `already_exists` |
  | CONTRIBUTING.md created | `fixed` |
  | Changed but still failing | `changed_not_passing` |
  | Re-check lookup fails | `changed_not_verified` |
  | Handler error | `error` |
  | Handler returns INCONCLUSIVE | Never `fixed` |

  Also check:
  - the summary counts equal the outcome counts;
  - every `fixed` control passes a fresh audit;
  - the full-audit cache file is byte-identical after the re-check.
- [ ] T043 [P] [US4] Write gating tests in `tests/darnit_baseline/test_remediation_gating.py`:
  - commit and PR run only when at least one outcome changed files, regardless of symbols in the text;
  - a pending-context check that raises means remediation does not run and the error is returned (FR-020).

### Implementation for User Story 4

- [ ] T044 [US4] Add `write_cache: bool = True` to `run_sieve_audit` and skip the cache write when False, in `packages/darnit/src/darnit/tools/audit.py`.
- [ ] T045 [US4] Build `RemediationOutcome`s per control from the applied `FileChange`s and `ChangeSet`s, then re-check the affected controls with `run_sieve_audit(controls=..., write_cache=False)`, following the data-model transitions. Return a `RemediationRun`. File: `packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py`.
- [ ] T046 [US4] Render the Markdown report and the fenced JSON block from `RemediationRun` (per contract section 5) in `packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py`. In `packages/darnit-baseline/src/darnit_baseline/tools.py`, gate commit/PR on outcomes instead of searching the output text for the error emoji, and make the pending-context guard fail closed.

**Checkpoint**: SC-004 holds.

---

## Phase 7: User Story 5 - The preview is what the apply will do (Priority: P2)

**Goal**: Every shipped remediation previews without side effects, and its apply matches the preview. Steps that cannot be previewed, and unsafe steps, need individual approval. Every declared safety property is enforced.

**Independent Test**: quickstart.md V6.

### Tests for User Story 5

- [ ] T047 [P] [US5] Write the plan contract test in `tests/darnit/remediation/test_plan_contract.py` (SC-005). For every remediation in every shipped framework TOML (Baseline, CSL, reproducibility, gittuf, testchecks), on a fixture repository:
  - plan mode gives 0 filesystem changes (snapshot) and 0 recorded platform writes;
  - plan then apply gives applied changes equal to planned;
  - non-previewable steps are flagged `previewable = False` and are skipped in batch apply without an individual digest.
- [ ] T048 [P] [US5] Write exec preview tests in `tests/darnit/remediation/test_exec_preview.py`:
  - an exec with `effects = "working_tree"` and `offline = true` is previewed in a scratch copy, and the diff appears as `FileChange`s;
  - a real apply whose diff differs from the preview reports the mismatch;
  - an exec without the declarations is `previewable = False`;
  - `validate_sync` rejects a shipped exec remediation whose command is `gh`, `curl`, `wget` or `git push`.
- [ ] T049 [P] [US5] Write safety-property tests in `tests/darnit/remediation/test_safety_properties.py` (SC-007):
  - `safe = false` is excluded from batch apply unless its `PlanItem.digest` is approved;
  - TOML declaring `requires_confirmation`, `dry_run_supported` or `dry_run_command` fails validation with the replacement named.

### Implementation for User Story 5

- [ ] T050 [US5] Implement `exec` remediation plan mode in `packages/darnit/src/darnit/sieve/builtin_handlers.py`: copy tracked and untracked-not-ignored files to a temporary directory, run there only when `effects = "working_tree"` and `offline = true`, and diff the copy into `FileChange`s. In apply mode, run for real and compare. Add `effects`/`offline` to the exec remediation schema in `packages/darnit/src/darnit/config/framework_schema.py`.
- [ ] T051 [US5] Enforce individual approval in batch apply for `safe = false`, `previewable = False` and high-impact items in `packages/darnit/src/darnit/remediation/executor.py`. Remove `requires_confirmation`, `dry_run_supported` and `dry_run_command` from `packages/darnit/src/darnit/config/framework_schema.py`. Add checks to `scripts/validate_sync.py`: the removed properties, `api_call`, and exec remediations calling platform commands.
- [ ] T052 [US5] Update shipped TOML:
  - Baseline: `safe` re-evaluated per remediation; zizmor `effects = "working_tree"`, `offline = true`; the removed properties deleted (`packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml`);
  - reproducibility: `uv lock` with `effects = "working_tree"`, not offline, so it is not previewable; drop `dry_run_command` (`packages/darnit-reproducibility/src/darnit_reproducibility/reproducibility.toml`);
  - any CSL, gittuf, testchecks, hello or example TOML using the removed properties.
- [ ] T053 [US5] Give the plugin remediation handler `generate_threat_model` a plan mode, or register it `supports_plan=False` so it is reported as not previewable, in `packages/darnit-baseline/src/darnit_baseline/implementation.py`.
- [ ] T054 [US5] Add `dry_run: bool = True` to `remediate_community_spec`. Route its README edit through the executor as a `FileChange` so it appears in the preview and the manifest. File: `packages/darnit-csl/src/darnit_csl/mcp_tools.py`.
- [ ] T055 [US5] Route `create_security_policy` through the executor's writer and manifest, keeping its explicit-create semantics. File: `packages/darnit-baseline/src/darnit_baseline/tools.py`.

- [ ] T055a [US5] Make `darnit run` preview by default and write only with `--apply` (FR-027). Update framework-design.md section 15.8 first, then `packages/darnit/src/darnit/cli.py` and `packages/darnit/src/darnit/agent/graph.py`. Update the feature 024 E2E tests that pin `darnit run` output (`tests/darnit/cli/`), naming FR-027, and add tests: no `--apply` writes nothing; `--apply` writes the planned changes.
- [ ] T055b [US4] Map the executor's individual-approval gating (`RemediationResult.needs_approval`, `.approvals`) to a `needs_approval` outcome and into `RemediationRun.approvals` in `packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py` (`_settled_outcome`). Extend the `darnit run` terminal approver to ask for individually-approved plan items by `PlanItem.digest` in `packages/darnit/src/darnit/remediation/platform/policy.py` and `packages/darnit/src/darnit/agent/graph.py`. Tests: `tests/darnit_baseline/remediation/test_outcomes.py` and `tests/darnit/agent/test_remediate_platform_policy.py`.

**Checkpoint**: SC-005 and SC-007 hold.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T056 [P] Update the tests that pinned the old behavior. Each change must state which requirement replaced the pinned behavior. The pinned behaviors: dry run listing handlers; `api_call` INCONCLUSIVE/ERROR; `file_create` "already exists" as PASS; the config overwrite after `file_create`; `add_all`; text-based gating. The files:
  - `tests/darnit/remediation/test_executor.py`
  - `tests/darnit/remediation/test_confirmation_required.py`
  - `tests/darnit/remediation/test_project_update.py`
  - `tests/darnit/remediation/test_executor_scan_vars.py`
  - `tests/darnit/sieve/test_builtin_handlers.py`
  - `tests/darnit/config/test_resolver.py`
  - `tests/darnit/test_config_resolver.py`
  - `tests/darnit/agent/test_graph.py`
  - `tests/darnit_baseline/test_context_validation_dry_run.py`
  - `tests/darnit_baseline/test_remediation_cache.py`
  - `tests/darnit_baseline/test_remediation_project_integration.py`
  - `tests/darnit_baseline/remediation/test_orchestrator.py`
  - `tests/darnit_baseline/remediation/test_asserted_skips.py`
  - `tests/darnit_baseline/remediation/test_all_templates.py`
  - `tests/darnit_baseline/remediation/test_template_rendering.py`
  - `tests/darnit_baseline/remediation/test_remediation_smoke.py`
  - `tests/darnit_baseline/remediation/test_tools_signatures.py`
  - `tests/darnit_baseline/test_integration_e2e.py`
  - `tests/darnit_csl/test_csl.py`
  - `tests/darnit_example/test_remediation.py`
  - `tests/integration/test_mcp_server.py`
- [ ] T057 [P] Update CHANGELOG `[Unreleased]` in `CHANGELOG.md`:
  - **Security:** platform remediation reads first, never weakens settings, and needs approval by default.
  - **BREAKING:**
    - `enable_branch_protection` defaults to preview, and its branch defaults to the repository default;
    - the `api_call` handler is removed;
    - `requires_confirmation`, `dry_run_supported` and `dry_run_command` are removed;
    - `commit_remediation_changes` stages only remediation files, and `add_all` is removed;
    - the OSPS-AC-01.01 and OSPS-AC-02.01 remediations are manual;
    - `remediate_community_spec` defaults to preview.
  - **Added:** the `[remediation]` operator policy; `platform_setting`; `approve` digests; run ids; outcome kinds.
- [ ] T058 [P] Update `docs/` pages that describe remediation, dry run, branch protection or the git workflow (`docs/USAGE_GUIDE.md`, `docs/SECURITY_GUIDE.md`, `docs/IMPLEMENTATION_GUIDE.md`, `packages/darnit-baseline/README.md`) to match framework-design.md. In `CLAUDE.md`, add the remediation rules to the Sieve/Conservative sections.
- [ ] T059 Run quickstart.md V1-V7 and record the results in a "Validation log" section of `specs/043-remediation-safety/quickstart.md`. Use recorded responses and scratch repositories only; V1 live only on a disposable repository.
- [ ] T060 Close or update the issues on merge: #472, #473, #474, #475, #482, #483. Note on #513 that the AC-02.01 remediation was removed. Note on #420 that it stays open. Do not reference unpublished advisories.
- [ ] T061 Run `uv run ruff check .`, `uv run pytest tests/ --ignore=tests/integration/ -q` and `uv run python scripts/validate_sync.py --verbose`, then fix failures.

---

## Dependencies & Execution Order

- **Setup:** T001-T004 come first, and T001 before any code (the spec-first rule). T002-T004 can run in parallel.
- **Foundational:** T005-T015 block all stories.
  - T005-T011 can run in parallel.
  - T012 comes before T013.
  - T014 needs T009, T011 and T013.
  - T015 needs T002.
- **US1 (MVP):** after Foundational.
  - T021 before T022; T022 before T023 and T024.
  - T025 needs T024.
  - T025a before T026; T026 and T027 need T025.
  - T028 needs T024.
  - T029 needs T025.
  - T030 and T031 come last.
- **US2:** independent of US1 after Foundational, so the two can be built in parallel. T034 touches `executor.py` after T014. T038 needs T035 and touches the Baseline `tools.py` after T029 if US1 is done first; otherwise coordinate.
- **US3:** after US2 (needs the manifest from a real run and the T034 executor checks).
- **US4:** after Foundational. T045 and T046 touch the orchestrator and `tools.py` after T029 and T038.
- **US5:** after Foundational. T051 touches `executor.py` after T034. T052 touches the Baseline TOML after T027 and T041.
- **Polish:** last.

## Parallel Opportunities

- Setup T002-T004 run together.
- Foundational tests T005-T008 and models T009-T011 run together.
- US1 tests T016-T020 run together, and US1 and US2 as whole stories can proceed in parallel.
- Within US5, T047-T049 run together, as do T053-T055 (different packages).

## Implementation Strategy

1. **MVP:** Setup, Foundational, then US1. This removes the only path that can weaken or replace platform settings, and makes every platform write approved and verified.
2. **Then US2,** to close the P1 set: no unrelated files committed, no stash lost.
3. **Then US4, US5 and US3.** Outcomes and the re-check, then preview fidelity and safety properties, then references.
4. **Last:** Polish, the CHANGELOG, and quickstart validation.
