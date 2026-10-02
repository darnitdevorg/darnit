# Research: Remediation Safety

**Feature**: 043-remediation-safety | **Date**: 2026-10-02

## Current state

Paths are relative to `packages/`.

| Area | Today | Defect |
|---|---|---|
| Branch protection tool | `darnit/remediation/github.py:98` `enable_branch_protection(dry_run=False, branch="main")` builds a fixed object and runs `gh api -X PUT .../protection` (:268). MCP wrapper `darnit_baseline/tools.py:525` also defaults `dry_run=False`. | #473: no read of current protection; `required_status_checks`, `restrictions` sent as null; `require_code_owner_reviews`, `required_linear_history` forced false; assumes `main`. Rulesets are only read to print a warning. |
| Declarative platform fixes | 7 `api_call` handlers in `openssf-baseline.toml` (:503, 555, 620, 676, 2075, 2957, 3378) with `endpoint` + `payload_template`; handler `sieve/builtin_handlers.py:1065` reads `url`, returns ERROR "No URL"; with a URL it returns INCONCLUSIVE "requires execution context" and the executor (`remediation/executor.py`) counts only FAIL/ERROR as failure. | #472: today every one errors; a rename alone turns them into reported successes that call nothing; a real call would send full-object payloads (`templates/*_payload.tmpl`). AC-03.01 and AC-02.01 are `safe = true`. |
| Success detection | `darnit_baseline/tools.py:1320` gates commit/PR on whether the output text contains the error emoji. | #472, FR-019. |
| Safety flags | `framework_schema.py:506-510` declares `safe`, `requires_api`, `requires_confirmation`, `dry_run_supported`; `dry_run_command` appears in TOML. Only `safe` is read (`darnit_baseline/remediation/orchestrator.py:406`), and only to tag `needs_review` after applying. | #483, FR-024, FR-025. |
| Dry run | `executor.py:535` skips handler calls and returns "Would execute handler" plus the rendered config. `HandlerContext` (`sieve/handler_registry.py:135`) has no mode field. No handler honors dry run; `yaml_inject` writes unconditionally (#166). | #483, FR-021/022. |
| File creation outcome | `file_create_handler` (`builtin_handlers.py:1013`) returns PASS "File already exists" with `action: skipped`; the orchestrator marks the control `applied` (:633). | #475. |
| Re-check | None. `run_sieve_audit(controls=...)` (`darnit/tools/audit.py:758`) accepts a subset but always writes the audit cache (:1082), so a subset run would replace the full-audit cache. | FR-018. |
| Project references | `update_config_after_file_create` (`darnit/config/resolver.py:81`) overwrites unless equal; orchestrator calls it with the first `file_create` path even when the file was skipped (`orchestrator.py:573-588`). Wrong mapping rows: DO-01.01 (README -> `quality.changelog`), DO-02.01 (bug template -> `security.policy`), GV-01.01 (GOVERNANCE.md -> `governance.maintainers`), GV-01.02 (MAINTAINERS.md -> `governance.code_of_conduct`), LE-01.01 (LICENSE -> `legal.contributor_agreement`). | #482. |
| Git tools | `server/tools/git_operations.py`: branch tool stashes and pops for an existing branch, on pop failure runs `checkout --theirs .project/` and `stash drop` (:77-85); commit tool runs `git add -A` (:169); PR tool pushes and opens a PR. Nothing records which files a run wrote. No tests. | #474. |
| Context guard | `darnit_baseline/tools.py` `remediate_audit_findings`: `except Exception: pass  # proceed with remediation anyway`. | FR-020. |
| Other writers | `create_security_policy` hard-codes `dry_run=False`; `remediate_community_spec` (`darnit-csl/.../mcp_tools.py:71`) has no preview and edits README directly; `darnit run` (`cli.py:747`) remediates with no `--dry-run`. | FR-001 (platform part), FR-010 (unrecorded writes). |
| Platform calls | `core/utils.py`: `gh_api_with_status` (GET only) with test responder `RecordedGhApi`; writes call `subprocess` directly. | Testability; FR-006. |

GitHub API facts used below (docs.github.com, REST 2026-03-10):

- `PUT .../branches/{b}/protection` requires `required_status_checks`, `enforce_admins`, `required_pull_request_reviews`, `restrictions` (null disables each); omitted optional booleans (`required_linear_history`, `allow_force_pushes`, `allow_deletions`, `block_creations`, `required_conversation_resolution`, `lock_branch`, `allow_fork_syncing`) default to false. It is a full replacement.
- GET and PUT shapes differ (`enforce_admins` `{enabled}` vs boolean; restrictions as objects vs logins/slugs; status checks `checks[{context, app_id}]`).
- Granular endpoints exist for `enforce_admins`, `required_pull_request_reviews` (PATCH), `required_status_checks` (PATCH), `required_signatures`, `restrictions` and its user/team/app lists. There is no granular endpoint for `allow_deletions`, `allow_force_pushes`, `required_linear_history`, `required_conversation_resolution`, `block_creations`, `lock_branch`, `allow_fork_syncing`.
- `GET /repos/{o}/{r}/branches/{b}` returns `protected` (and 404 for a missing branch); this distinguishes "not protected" from "no access" without relying on error text.
- `GET /repos/{o}/{r}/rules/branches/{b}` returns all active rules for the branch, repository and organization level.
- The organization two-factor requirement is read-only in the API; it can be enabled only in the web UI. Enabling it removes outside collaborators (and bot accounts) without 2FA.
- `PATCH /repos/{o}/{r}` partial-update semantics are not documented; `private` is documented with a default. Send only the field being changed and read it back.
- Private vulnerability reporting: `GET` returns `{enabled}`, `PUT` enables, `DELETE` disables.
- `gh api`: `-f` sends strings only; use `--input -` with a JSON body; exit code 1 for any HTTP failure; status from `--include`.

## R1. One platform-change engine; remove `api_call`

**Decision**: Add a core platform-change engine (`darnit/remediation/platform/`) and a remediation handler `platform_setting` whose TOML declares a *requirement* on a named target, not a payload:

```toml
[[controls."OSPS-AC-03.02".remediation.handlers]]
handler = "platform_setting"
target = "branch_protection"
require = { prevent_deletion = true }
```

The engine reads the target's current state, decides whether the requirement already holds, computes the minimal operations, previews them, applies them under the remediation policy (R4), and reads back. Remove the `api_call` handler, its schema section, and the seven payload templates. `enable_branch_protection` becomes a thin tool over the same engine (FR-009).

**Rationale**: A payload template cannot express "change only what is needed without weakening anything" (FR-003); a requirement can. One engine gives one place for read-first, approval binding, read-back, and policy.

**Alternatives considered**: Fix `api_call` to read `endpoint` and merge payloads into the current state generically (a JSON merge cannot know that two approvals is stricter than one, or translate GET to PUT shapes); keep `api_call` for plugins (it has never worked, so no plugin relies on it; leaving it violates FR-009).

## R2. Targets and requirement vocabulary

**Decision**: Three GitHub targets in core, each with its own reader, comparator, and planner:

| Target | Requirements | Read | Write |
|---|---|---|---|
| `branch_protection` | `require_pull_request`, `require_approvals = N` (at least N), `prevent_deletion`, `prevent_force_push`, `enforce_admins`, `require_status_checks = [contexts]` (superset of current) | branch (`protected`), protection (if protected), branch rules | see R3 |
| `repository` | `visibility = "public"` (high-impact) | `GET /repos/{o}/{r}` | `PATCH` with only that field |
| `vulnerability_reporting` | `enabled = true` | `GET .../private-vulnerability-reporting` | `PUT` |

Requirement names match the existing check handler's (`github_branch_protection`: `require_pull_request`, `prevent_deletion`, `require_approvals` + `required_approvals_minimum`), so a control's check and its fix speak the same vocabulary. A requirement satisfied by an active ruleset counts as satisfied (no write).

Control mapping:

- AC-03.01 -> `branch_protection` `require_pull_request`; AC-03.02 -> `prevent_deletion`; QA-07.01 -> `require_approvals = 1`.
- QA-01.01 -> `repository` `visibility = "public"` (high-impact).
- VM-03.01 -> `vulnerability_reporting` `enabled`.
- AC-01.01 (organization 2FA) -> manual only: the platform offers no API to set it, so no policy can make darnit apply it. The manual steps state the impact (collaborators and bots without 2FA are removed).
- AC-02.01 (allow forking) -> remediation removed; the control is manual-only until #513 fixes what it measures.

**Rationale**: Comparators per target encode "stricter" correctly (counts are minimums, booleans have a safe direction, lists are supersets). Keeping GitHub targets in core matches today's placement of `remediation/github.py` and keeps Baseline TOML-only (Principle I, III).

**Alternatives considered**: Per-control Python fixers in darnit-baseline (duplicates read/approve/read-back per control); a generic JSON-pointer requirement language (cannot express "at least", ruleset equivalence, or shape translation).

## R3. Minimal branch protection change

**Decision**:

1. Resolve the branch: the repository default branch from `GET /repos/{o}/{r}` unless the caller names one (FR-007). Error if unreadable.
2. `GET .../branches/{b}`: missing branch -> ERROR; `protected = false` -> state "unprotected"; `protected = true` -> `GET .../protection`. Any read failure -> ERROR, no write (FR-002).
3. Unprotected: one `PUT` that sets only the required settings; every other field is sent at its platform default, which equals the current (unprotected) state, so nothing is lost.
4. Protected:
   - review requirements -> `PATCH .../required_pull_request_reviews`, sending only the fields that must tighten (`required_approving_review_count` raised to the minimum, never lowered);
   - `enforce_admins` -> `POST .../enforce_admins`; `require_status_checks` -> `POST .../required_status_checks/contexts` with only the missing contexts (existing contexts and `checks` are kept; if status checks are not configured at all, `PATCH .../required_status_checks` creates them);
   - `prevent_deletion` / `prevent_force_push` (no granular endpoint) -> one full `PUT` built by translating the GET response into the PUT shape with every existing value preserved and only the required booleans changed.
   - The translator is total over a known field list; if the GET response contains a field it does not know, the planner refuses with ERROR "cannot preserve unknown protection setting <field>" rather than risk dropping it.
5. Several requirements on the same branch (AC-03.01, AC-03.02, QA-07.01 in one run) are planned together into one change set (edge case: no second full replacement undoes the first).

**Rationale**: Granular endpoints cannot drop unrelated settings; the full PUT is used only where unavoidable and only from a verified-complete translation (FR-003).

**Alternatives considered**: Always full PUT from translated GET (maximises reliance on the translator); only granular endpoints (cannot set `allow_deletions`).

## R4. Remediation policy in operator configuration

**Decision**: New operator-config section (feature 040 schema, `extra="forbid"`):

```toml
[remediation]
platform = "prompt"      # prompt | manual | auto  (default prompt)
high_impact = "prompt"   # prompt | manual | auto  (default prompt)
```

High-impact = organization-wide settings and repository visibility (FR-008); the target declares its class. `manual` -> no write, report steps. `prompt` -> preview, then write only an approved change set. `auto` -> write without approval. Every mode reads first, plans minimally, and reads back (FR-026). The report records the policy in effect and its operator-config digest. Nothing in the audited repository is read for policy (040 rule).

**Rationale**: Matches the clarification (2026-10-02); reuses the 040 loader, digest, and "only operator config sets tool behaviour" rule.

**Alternatives considered**: One policy for all platform changes (user asked for high-impact to be separately configurable); per-control policy (more surface than needed; can be added later without breaking this shape).

## R5. Approval bound to a change-set digest

**Decision**: A preview returns, per platform target, a `ChangeSet` with a digest:
`"sha256:" + sha256(canonical_json({target, observed, operations}))`, where `observed` is the current values of every field the operations touch plus a digest of the whole observed state. Under `prompt`, the apply call carries `approve = [digest, ...]`. At apply, the engine re-reads the target and re-plans; it writes only if the recomputed digest equals an approved one, else outcome "stale preview, nothing changed" (FR-005). A batch apply never covers a high-impact change set: it must be listed in `approve` by its own digest (FR-008). Approvals are single-use and not persisted; the remediation report records which digests were approved, by whom (operator identity, 040), and when.

**Rationale**: Same pattern as 041 (`confirm_pass_candidate` by evidence digest) and 042 (accept candidate by digest): an agent cannot approve something different from what the person saw, and a state change in between voids the approval.

**Alternatives considered**: Treat `dry_run=False` as approval (agents pass it routinely; violates US1 scenario 5 and the "apply flag alone does not approve" edge case); persist approvals in the 040 store (unnecessary for a single-use, state-bound decision).

## R6. Plan/apply protocol for remediation handlers

**Decision**: `HandlerContext` gains `mode: Literal["plan", "apply"]`. Remediation handlers return planned changes in both modes:

- `file_create`, `yaml_inject`, `project_update` compute `FileChange`s (path, action create/modify/none, resulting content, reason) and never write; the executor is the single writer and applies the same `FileChange`s in apply mode. Preview equals apply by construction (FR-021).
- `platform_setting` returns `ChangeSet`s in plan mode; in apply mode the engine executes approved ones.
- `exec` must declare `effects = "working_tree"` and `offline = true` to be previewable: plan mode runs it in a scratch copy of the working tree (tracked and untracked-not-ignored files) and records the diff as `FileChange`s; apply mode runs it for real and compares the resulting diff to the preview (mismatch reported in the outcome). An exec remediation without those declarations is "cannot be previewed exactly" (FR-023) and is excluded from batch apply unless individually approved. Exec remediations must not change platform state; `validate_sync` rejects shipped exec remediations whose command is `gh`, `curl`, `wget`, or `git push`, and `framework-design.md` states the rule.
- Plugin remediation handlers (for example `generate_threat_model`) that do not declare plan support are treated as "cannot be previewed exactly".

A contract test runs every registered remediation handler in plan mode against a fixture repository with a filesystem snapshot and a recording platform responder, and asserts zero writes (FR-022, SC-005).

**Rationale**: Moving writes to one place makes preview fidelity, the run manifest (R7), conflict checks (FR-011), and ignore rules (FR-014) enforceable once.

**Alternatives considered**: A `dry_run` flag each handler must honor (today's design; one forgotten check reproduces #166); preview by running everything in a scratch copy (unsafe for anything that reaches the network).

## R7. Run manifest and version-control safety

**Decision**: Each apply records a run manifest operator-side (`user_data_root()/remediation/<repo-identity>/<run-id>.json`, 0600, never inside the checkout): run id, files written with resulting content digests, platform change sets applied. The git tools take a `run_id` (default: latest run for the repository):

- Commit stages exactly the manifest paths, with explicit pathspecs, and only those whose current content digest still equals the manifest's (else conflict, nothing committed); ignored paths (`git check-ignore`) are never added (FR-010, FR-014). The commit message carries a `Darnit-Remediation-Run: <run-id>` trailer and the report lists every committed file.
- Before any write, a target path with uncommitted user changes is a conflict and is not written (FR-011).
- Branch creation never stashes. New branch: `git checkout -b` from the current HEAD (uncommitted changes stay in the working tree, untouched). Existing branch: allowed only if the working tree is clean and every commit on it beyond the base carries a darnit run trailer; otherwise stop and explain (FR-012, FR-013). Detached HEAD, `MERGE_HEAD`, `rebase-merge`/`rebase-apply` -> stop before changing anything.
- The PR tool pushes only the remediation branch.

**Rationale**: The manifest is the only reliable answer to "which files did remediation write"; keeping it out of the repository preserves 042's "reads never write" and keeps it out of commits.

**Alternatives considered**: Diff the working tree before and after remediation (fails when the user edits concurrently and when files pre-existed dirty); write the manifest into `.project/` (pollutes the repository and could be committed).

## R8. Outcomes, re-check, and reporting

**Decision**: A typed `RemediationOutcome` per control with `kind` in {`fixed`, `changed_not_passing`, `changed_not_verified`, `unchanged`, `needs_approval`, `needs_confirmation`, `manual`, `error`} (FR-017), what changed (FileChanges and ChangeSets), the re-check result, and the reason. Handler statuses map conservatively: only a definite success with a non-empty change counts as "changed"; INCONCLUSIVE, ERROR, not-run, and "already exists" never count as success. After an apply that changed something, the affected controls are re-checked with `run_sieve_audit(controls=subset, write_cache=False)` (new parameter; a subset run must not replace the full-audit cache). Markdown and JSON reports are rendered from the outcomes; commit and PR steps are gated on outcomes, not text (FR-019). The pending-context guard fails closed (FR-020).

**Rationale**: Principle II applied to remediation: claiming a fix requires the same evidence as claiming a PASS.

**Alternatives considered**: Re-run a full audit after remediation (slow, and the cache problem remains); trust handler messages (today's defect).

## R9. Project references declared with the remediation

**Decision**: Remove `CONTROL_REFERENCE_MAPPING`. A `file_create` handler may declare `project_reference = "<section.field>"`. After apply, the reference is recorded only if that file was created in this run (manifest), and only if the field is empty or already equal (FR-015). A Baseline test checks every declared `project_reference` against the field's known file locations (`DEFAULT_FILE_LOCATIONS`) so a bug template can never be declared as `security.policy` (FR-016). The five wrong rows are dropped or corrected in the TOML.

**Rationale**: TOML-first (Principle III); the mapping sits next to the file it describes, so it cannot drift.

**Alternatives considered**: Fix the table rows only (keeps a second source of truth that drifted once already); infer the field from the filename (guesswork).

## R10. Safety properties in the schema

**Decision**: Keep and enforce `safe` (`false` -> excluded from batch apply unless individually approved by its preview digest, FR-024). Keep `requires_api` as descriptive metadata (it is not a safety property). Remove `requires_confirmation` (subsumed by `safe = false`), `dry_run_supported`, and `dry_run_command` (replaced by the plan protocol and exec `effects`/`offline`). Re-evaluate `safe` for every shipped remediation: all `platform_setting` handlers are governed by the policy instead; exec remediations default to `safe = false` unless previewable.

**Rationale**: FR-025: a declared safety property must be enforced or absent.

## R11. Entry points

**Decision**:

- `remediate_audit_findings`: keeps `dry_run=True`; adds `approve: list[str] | None` and returns the run id; structured outcomes; fail-closed guard.
- `enable_branch_protection`: `dry_run=True` default; parameters become requirements for the engine; adds `approve` and `branch=None` (default branch).
- `commit_remediation_changes`, `create_remediation_pr`, `create_remediation_branch`: `run_id` parameter; R7 rules.
- `create_security_policy`: routed through the executor's writer and manifest; keeps its explicit-create semantics.
- `remediate_community_spec`: adds `dry_run=True`; README edit becomes a `FileChange` through the executor.
- `darnit run`: platform changes follow the policy; under `prompt` it asks on `/dev/tty` when interactive (feature 027 pattern) and otherwise reports `needs_approval`.
- Skills (`darnit-remediate`, `darnit-comply`): show the preview including change-set digests and impact; pass back only digests the person approved.

**Rationale**: Every writer goes through the same executor, engine, and manifest (FR-009, FR-010).

## R12. Testing platform writes

**Decision**: Extend the `gh` responder to `(method, endpoint, body) -> (body, status, error)` and add `gh_api_write(method, endpoint, payload)` (JSON via `--input -`, status via `--include`). `RecordedGhApi` serves keys such as `PUT /repos/o/r/branches/main/protection` and records request bodies, so tests assert exactly which fields were sent. Fixtures: an unprotected branch, a stricter-than-required protection (two approvals, required checks, push restrictions, code-owner review, linear history), a ruleset-only repository, a read-only token (GET ok, writes 403), a read failure, a GET containing an unknown field.

## R13. Sequencing against other work

- `docs/architecture/framework-design.md` first: section 4 (remediation actions: plan/apply, `platform_setting`, exec `effects`, removal of `api_call`), a new remediation policy and approval section, outcomes.
- After 040-042 merge; independent of the advisory fix. PR #504 also touches the DO-02.01 mapping row; R9 removes the table, so whichever lands second drops the row.
- #420 (atomic rollback) stays out of scope; outcomes report partial application per step.
- #513 later restores an AC-02.01 remediation if one becomes meaningful.

## R14. What counts as "high-impact"

**Decision**: A target declares its impact class. `repository.visibility` and any organization-scoped target are `high_impact`; `branch_protection` and `vulnerability_reporting` are `platform`. The preview of a high-impact change states its impact from what the platform reveals (visibility to public: all code, history, and Actions logs become publicly readable, and existing private forks are detached; organization 2FA: collaborators and bots without 2FA removed).
