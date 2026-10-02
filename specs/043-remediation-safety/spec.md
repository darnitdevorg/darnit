# Feature Specification: Remediation Safety

**Feature Branch**: `043-remediation-safety`

**Created**: 2026-10-02

**Status**: Draft

**Input**: User description: "043: remediation safety. Remediation must never damage a user's repository or platform settings, and must report only what it actually changed. Covers #473, #472, #474, #475, #483 (absorbs #166), and #482. Priority order: platform writes (#473, #472) first as one read-current-state, change-only-what's-needed, confirm-before-write design; then working-tree safety (#474, #482); then truthful reporting (#475, #483). Builds on 040, 041, and 042."

## Background

Remediation is the part of darnit that changes things: it creates files in the repository, edits `.project/` data, commits and opens pull requests, and changes settings on the hosting platform (branch protection, repository settings, organization settings). Constitution Principle II says incorrect results are worse than incomplete ones. For remediation, the equivalent is that a damaging change is worse than no change, and a change reported but not made is worse than an honest "not fixed".

The September 2026 evaluation found:

- The branch protection tool runs for real unless the caller asks for a preview. It does not read the current protection; it replaces the whole protection object with a fixed one. This silently removes required status checks and push restrictions, can lower the number of required approvals, turns off code-owner review and linear history, and assumes the branch is named `main` (#473).
- The declarative platform remediations are harmless today only because the handler reads a field (`url`) that the framework configuration never sets (it uses `endpoint` and `payload_template`), so every one of them errors. Their payloads are full-object replacements. Fixing the field alone would make a batch "remediate all" enforce organization-wide two-factor authentication (which removes every member without it), make a private repository public, and replace branch protection the same way the tool above does. Some of these are marked `safe = true`. Separately, the remediation tool decides success by looking for an emoji in its own output text (#472).
- The commit step stages everything in the working tree (`git add -A`), so unrelated work in progress, local configuration, or a `.env` file is committed and pushed under a compliance commit message. When switching to an existing remediation branch requires stashing, a failed restore drops the user's stash (#474).
- A remediation that creates a file reports "applied" when the file already exists and nothing was written, and no remediation is followed by a re-check of the control, so the summary can claim fixes for controls that still fail (#475).
- The dry run never runs any handler; it lists the handlers that would be called. The preview therefore promises changes that will not happen and omits ones that will. `dry_run_supported` and `requires_confirmation` are declared in the framework schema and set in the configuration but nothing reads them, `safe = false` only tags a result after it has already been applied, and individual handlers (for example the YAML injection handler) do not honor the dry-run flag at all (#483, #166).
- After creating a file, remediation records a reference to it in `.project/` using a fixed control-to-field table. Several rows are wrong (for example, creating a bug report template records it as the project's security policy), and the update overwrites whatever reference was already there (#482).
- The guard that stops remediation while project context is still unconfirmed proceeds with remediation if the guard itself fails.

Feature 042 already ensures remediation consumes only confirmed project values and stops with `confirmation required: <key>`. Feature 041 defines ERROR as a broken measurement. Feature 040 defines operator configuration and trust. This feature does not change those rules; it governs what remediation may change, how it shows the change beforehand, and what it may claim afterwards.

## Clarifications

### Session 2026-10-02

- Q: May darnit apply organization-wide or repository visibility changes itself? -> A: Yes, governed by operator configuration. Default `prompt`: darnit asks the person and, on approval, makes the change itself. The operator may set `manual` (darnit only gives the steps) or `auto` (darnit applies without asking) (FR-008, FR-026).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Platform settings change only by approved, minimal changes (Priority: P1)

A maintainer (directly, or through a coding agent) asks darnit to fix a control that needs a platform setting, such as branch protection for the default branch. darnit reads the current settings, works out the smallest change that satisfies the control without weakening anything already configured, shows exactly what would change, and makes the change only after the person approves that specific change.

**Why this priority**: A wrong platform write can remove review requirements, expose a private repository, or remove people from an organization. These are the most damaging outcomes darnit can produce, and one tool does it today by default.

**Independent Test**: On a test repository whose default branch already has stricter protection than darnit's baseline (two required approvals, required status checks, push restrictions, code-owner review), run the branch protection fix as a preview and as an apply; confirm the preview shows only the missing settings, the apply changes only those, and every pre-existing setting is unchanged afterwards. Repeat with a token that cannot read protection settings and confirm nothing is written.

**Acceptance Scenarios**:

1. **Given** any tool or remediation that changes platform settings, **When** it is called without an explicit request to apply, **Then** it only previews and changes nothing.
2. **Given** existing protection on the default branch, **When** darnit computes the change for a protection control, **Then** the change leaves every existing setting that is equal to or stricter than the control's requirement exactly as it was, and adds or tightens only what the control requires.
3. **Given** settings that already satisfy the control, **When** remediation runs, **Then** nothing is written and the outcome is "already satisfied".
4. **Given** the current settings cannot be read (missing permission, not found, rate limit, network), **When** remediation runs, **Then** nothing is written and the outcome is an error naming the cause.
5. **Given** a preview the person has seen, **When** they approve it, **Then** darnit writes exactly the previewed change; **and if** the current settings changed since the preview, darnit writes nothing and asks for a new preview.
6. **Given** an apply completes, **When** darnit reports the outcome, **Then** the outcome comes from reading the settings back and comparing them with the requirement, not from the text of a response.
7. **Given** a request to remediate all failing controls and the default policy, **When** a control's fix would change organization-wide settings or repository visibility, **Then** darnit asks for approval of that change on its own (approving the batch does not approve it), shows its impact (for example the members who would lose access), and applies it only if approved.
8. **Given** the operator configured the policy for such changes as `manual`, **When** remediation runs, **Then** darnit makes no platform change and reports the exact steps for a person to take.
9. **Given** the operator configured the policy as `auto`, **When** remediation is applied, **Then** darnit makes the change without asking, and still follows every other rule in this story (read first, minimal change, never weaken, read back) and records the impact in the outcome.
10. **Given** the audited repository's own files, **When** they contain any remediation policy setting, **Then** it is ignored; only the operator's configuration sets the policy.

---

### User Story 2 - Remediation commits contain only remediation's own changes (Priority: P1)

A maintainer with uncommitted work in progress asks darnit to apply fixes on a branch, commit, and open a pull request. The commit contains only the files remediation wrote. The maintainer's other changes, untracked files, and stashes are exactly as they were before.

**Why this priority**: Committing and pushing unrelated files (including secrets) is irreversible once pushed, and losing a stash destroys work that exists nowhere else.

**Independent Test**: In a repository with a modified tracked file, an untracked `.env`, and an existing stash, run remediation with branch creation, commit, and pull request; confirm the commit lists only remediation-written files, the modified file and `.env` remain uncommitted and unchanged, and the stash list is unchanged.

**Acceptance Scenarios**:

1. **Given** unrelated modified or untracked files, **When** remediation commits, **Then** only files remediation created or modified in this run are staged and committed.
2. **Given** a file remediation wants to write already has uncommitted changes by the user, **When** remediation runs, **Then** it does not write that file and reports the conflict.
3. **Given** switching to the remediation branch would require moving the user's uncommitted changes, **When** remediation runs, **Then** it stops before changing anything and tells the person why, rather than stashing on their behalf.
4. **Given** any failure during branch, commit, or pull request steps, **When** darnit reports it, **Then** no user stash has been dropped and no user change has been discarded.
5. **Given** a commit is created, **When** it is reported, **Then** the report lists every committed file.

---

### User Story 3 - Remediation never rewrites unrelated project references (Priority: P2)

After remediation creates a file, darnit may record where that file lives in the project's data. It records it only under the field that describes that file, and never replaces a reference the project already set.

**Why this priority**: A wrong reference silently changes what later audits and readers treat as the project's security policy or other key documents.

**Independent Test**: In a repository whose `.project/` already names a security policy, remediate a control whose fix creates a bug report template; confirm the security policy reference is unchanged and no reference is recorded under an unrelated field.

**Acceptance Scenarios**:

1. **Given** a field that already holds a different reference, **When** remediation creates a file that maps to that field, **Then** the existing reference is unchanged and the report says the new file was not recorded and why.
2. **Given** a remediation that creates a file, **When** a reference is recorded, **Then** the field describes that file's kind (a security policy is recorded only as the security policy, a bug report template never is).
3. **Given** a remediation that changes no file (for example a platform setting), **When** it completes, **Then** no file reference is recorded.

---

### User Story 4 - Outcomes say what actually happened (Priority: P2)

After remediation, each control's outcome states what darnit changed, and whether the control now passes. "Fixed" is reported only when something changed and a re-check of the control afterwards shows it passing.

**Why this priority**: An inflated remediation summary leads people to stop looking at controls that still fail, which is a false compliance signal produced by the tool itself.

**Independent Test**: Remediate a set of controls where one target file already exists, one fix succeeds, one handler cannot run, and one control still fails after a successful change; confirm each outcome is distinct and correct and that only the genuinely fixed control is reported as fixed.

**Acceptance Scenarios**:

1. **Given** a file the remediation would create already exists, **When** remediation runs, **Then** the outcome is "nothing changed" (with the reason) and the control's status is whatever a re-check finds, never "fixed" by itself.
2. **Given** a remediation changed something, **When** the control is re-checked and still does not pass, **Then** the outcome is "changed, control still not passing", with the re-check result.
3. **Given** a handler returns anything other than a definite success (inconclusive, error, not run), **When** outcomes are computed, **Then** the remediation is not counted as successful.
4. **Given** the summary of a remediation run, **When** it is reported, **Then** its counts are derived from the per-control outcomes and never from matching symbols or words in output text.
5. **Given** the check for unconfirmed project context cannot complete, **When** remediation is requested, **Then** remediation does not run and the reason is reported.

---

### User Story 5 - The preview is what the apply will do (Priority: P2)

A maintainer previews remediation before applying it. The preview lists every file that would be created or changed (with content), every platform setting that would change (before and after), and every command that would run, computed against the current state by the same logic the apply uses. Anything darnit cannot preview exactly is labelled as such and is not applied without explicit approval.

**Why this priority**: People and agents decide to apply based on the preview; a preview that differs from the apply makes approval meaningless.

**Independent Test**: For every remediation defined in the shipped framework configurations, run a preview and then an apply on the same fixture repository; confirm the apply's changes equal the preview's listed changes, and that the preview modified nothing.

**Acceptance Scenarios**:

1. **Given** a preview, **When** it completes, **Then** no file in the repository and no platform setting has changed.
2. **Given** a preview followed immediately by an apply with no intervening change, **When** both complete, **Then** the set of changes applied equals the set previewed.
3. **Given** a remediation step whose effect cannot be computed in advance (for example an external fixing tool), **When** previewed, **Then** it is labelled "cannot be previewed exactly" with the command and the files it may touch, and it is excluded from a batch apply unless the person approves it individually.
4. **Given** a remediation marked as unsafe or as requiring confirmation in the framework configuration, **When** a batch apply runs, **Then** it is not applied unless the person approved that remediation individually.
5. **Given** a framework configuration that declares a remediation property controlling safety or preview behavior, **When** remediation runs, **Then** that property is enforced; declared-but-ignored properties are not permitted.

### Edge Cases

- The default branch is not `main`: darnit uses the repository's actual default branch from the platform, and errors if it cannot determine it.
- Branch protection is enforced through repository or organization rulesets rather than classic protection: darnit reads both, treats a requirement satisfied by either as satisfied, and does not write classic protection that would duplicate or conflict with an active ruleset without saying so in the preview.
- The token can read but not write settings: the preview works; the apply errors with nothing changed.
- Two protection fixes (for example deletion protection and review requirement) target the same branch: they produce one combined minimal change, not two full replacements where the second undoes the first.
- A platform write partly succeeds (one field accepted, another rejected): the outcome reports exactly which fields changed, from the read-back, and the control is not reported fixed.
- The repository is on a hosting platform darnit does not support for platform remediation: platform fixes are reported as manual with instructions; nothing is attempted.
- The user is in a detached HEAD state, in the middle of a merge or rebase, or the remediation branch already exists with unrelated commits: darnit stops before changing anything and explains.
- A file remediation would create is ignored by the repository's ignore rules: it is not force-added to the commit; the outcome says so.
- Remediation is run by a coding agent that passes "apply" without showing the person a preview: under the `prompt` policy the approval requirement still applies (US1 scenario 5, US5 scenario 3-4); passing an apply flag alone does not approve a platform change or an unsafe remediation.
- Policy `auto` for high-impact changes in an unattended run (for example CI): darnit applies the change and the report states the policy, the change, and its impact; no prompt is attempted.
- Policy `prompt` in a run with no way to ask a person (non-interactive, no agent): the change is not made, and the outcome is "needs approval" with the previewed change.
- Re-check of a control after remediation needs a platform lookup that fails: the outcome is "changed, not verified" with the error, not "fixed".
- Atomic rollback across several handlers of one remediation is out of scope (#420); a partial failure is reported per step as above.

## Requirements *(mandatory)*

### Functional Requirements

**Platform changes**

- **FR-001**: Every tool and remediation that changes platform settings MUST default to preview; it MUST change nothing unless the caller explicitly requests an apply.
- **FR-002**: Before any platform change, darnit MUST read the current settings of the target. If they cannot be read, it MUST NOT write and MUST report an error with its cause.
- **FR-003**: A platform change MUST be the minimal change that satisfies the control: it MUST leave unchanged every existing setting that is equal to or stricter than what the control requires, and MUST NOT remove, loosen, or reset any setting the control does not require changing.
- **FR-004**: If the current settings already satisfy the control, darnit MUST NOT write.
- **FR-005**: A platform change MUST be applied only after approval of that specific change (the target, and each field's before and after value). If the target's current settings differ from those the preview was computed from, darnit MUST NOT write and MUST require a new preview.
- **FR-006**: After a platform write, darnit MUST read the settings back and derive the outcome from the comparison with the requirement; it MUST NOT derive success from response text.
- **FR-007**: The target branch for branch-level settings MUST be the repository's actual default branch as reported by the platform, unless the person names a branch.
- **FR-008**: Changes to organization-wide settings and to repository visibility are high-impact. Under the `prompt` policy each MUST be approved on its own; an approval of a batch or of other changes MUST NOT cover it. Its preview MUST show its impact as far as the platform reveals it (for example which members would lose access, or that private contents would become public).
- **FR-026**: The operator configuration MUST set a remediation policy for platform changes, separately for high-impact changes (FR-008) and for other platform changes, each one of: `prompt` (default; darnit asks, and on approval makes the change itself), `manual` (darnit makes no platform change and reports the exact steps), or `auto` (darnit applies without asking). The policy MUST come only from operator configuration (feature 040), never from the audited repository, and the policy in effect MUST be recorded in the remediation report. Every mode MUST still follow FR-002 to FR-007; `auto` only removes the approval step of FR-005 and FR-008. It does not approve repository steps that require individual approval under FR-023 or FR-024; those still need a person's approval in every mode.
- **FR-009**: Fixes declared in the framework configuration and fixes offered as standalone tools for the same setting MUST follow the same rules (FR-001 to FR-008); there MUST be no second path that bypasses them.

**Working tree and version control**

- **FR-010**: Remediation MUST stage and commit only files it created or modified in the current run.
- **FR-011**: Remediation MUST NOT write a file that has uncommitted user changes; it MUST report the conflict instead.
- **FR-012**: Remediation MUST NOT stash, discard, overwrite, or drop the user's uncommitted changes or existing stashes. If a branch operation cannot proceed without doing so, darnit MUST stop before changing anything and explain.
- **FR-013**: Remediation MUST stop before changing anything when the repository is in a detached HEAD state, mid-merge, mid-rebase, or when the named remediation branch already contains commits not made by this remediation flow.
- **FR-014**: Remediation MUST NOT add files excluded by the repository's ignore rules.

**Project references**

- **FR-015**: Remediation MUST record a file reference in project data only under the field that describes that file's kind, and only when that field is empty or already holds the same reference.
- **FR-016**: The mapping from a remediation to the project field it records MUST be declared with the remediation in the framework configuration and validated against what the remediation creates; a remediation that creates no file MUST record no reference.

**Outcomes**

- **FR-017**: Each control's remediation outcome MUST be exactly one of: fixed (something changed and a re-check passes), changed but still not passing, changed but not verified (re-check could not run), nothing changed (with reason, including "already present" and "already satisfied"), needs approval (with the previewed change), needs confirmation, manual, or error. A handler result that is not a definite success MUST NOT count as success.
- **FR-018**: After an applied remediation changes something, darnit MUST re-check the affected controls and report the re-check result with the outcome.
- **FR-019**: Remediation summaries and any downstream decision (such as whether to commit or open a pull request) MUST be derived from structured per-control outcomes, never from matching symbols or words in output text.
- **FR-020**: If darnit cannot determine whether project context is still unconfirmed, remediation MUST NOT run.

**Preview fidelity**

- **FR-021**: A preview MUST be computed by the same logic as the apply, against the current state, and MUST list every file to be created or changed (with the resulting content or a diff), every platform field to be changed (before and after), and every command to be run.
- **FR-022**: A preview MUST NOT change any file or platform setting; every remediation handler MUST honor preview mode.
- **FR-023**: A step whose effect cannot be computed in advance MUST be labelled as such in the preview, with the command and the files or settings it may affect, and MUST NOT run in a batch apply unless the person approved it individually.
- **FR-024**: Remediations marked unsafe or requiring confirmation in the framework configuration MUST NOT be applied in a batch unless the person approved each individually.
- **FR-025**: Every remediation property in the framework schema that concerns safety, confirmation, or preview MUST be enforced; a property that is not enforced MUST be removed from the schema and configurations rather than left declared.

### Key Entities

- **Platform target**: The organization, repository, or branch whose settings a remediation changes, with its current settings as read from the platform.
- **Change set**: The minimal set of field changes (before and after) that would satisfy a control from the current state; also the list of files to write and commands to run for repository remediations. A preview produces it; an approval names it; an apply executes exactly it.
- **Remediation policy**: The operator's setting (`prompt`, `manual`, or `auto`) for high-impact platform changes and for other platform changes; decides whether darnit asks, only instructs, or applies.
- **Approval**: A person's acceptance of a specific change set for a specific target state; invalid if the target state has changed since the preview.
- **Remediation outcome**: The per-control result of a remediation run (FR-017), with what changed, the re-check result, and any error.
- **Remediation-written file**: A file remediation created or modified in the current run; the only kind of file remediation may commit.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a repository whose branch protection is stricter than every darnit requirement, running every shipped protection remediation and tool, previewed and applied, changes 0 existing settings.
- **SC-002**: Across all shipped remediations and tools, 0 platform writes occur without an explicit apply request and either an approval of the specific change or an operator policy of `auto`; 0 occur under `manual`; 0 occur when current settings could not be read.
- **SC-003**: In the reproduction for #474 (modified tracked file, untracked `.env`, existing stash), the remediation commit contains 0 files not written by remediation, and the stash list and the user's files are byte-identical before and after.
- **SC-004**: In a run where some controls are genuinely fixed and others are not, 100% of controls reported as fixed pass a fresh audit, and 0 controls with an unchanged target are reported as fixed.
- **SC-005**: For every remediation in the shipped framework configurations, the changes made by an apply equal the changes listed by an immediately preceding preview, and the preview itself changes 0 files and 0 settings.
- **SC-006**: 0 existing `.project/` references are changed by remediation of a control whose file maps to a different field (reproduction for #482).
- **SC-007**: Every safety, confirmation, or preview property in the remediation schema is either enforced by a test or absent from the schema.

## Assumptions

- Features 040 (operator configuration, trust), 041 (result contract, ERROR), and 042 (only usable context values reach remediation) are in place; this feature does not change their rules.
- Organization two-factor enforcement cannot be set through GitHub's API (web UI only), so its remediation is manual under every policy; the policy governs only changes the platform allows darnit to make.
- GitHub is the only hosting platform with platform remediation today; other platforms get manual instructions. Rulesets and classic branch protection are both in scope for reading.
- "Approval" follows the confirmation model used in 041 and 042: a person decides, directly or through an agent acting on the person's explicit instruction, and the decision is bound to the exact change shown.
- Atomic, idempotent rollback across multiple handlers of one remediation is out of scope (#420); this feature requires accurate per-step reporting instead.
- Fixing what individual controls measure (#508, #511, #513, the catalog refresh) is out of scope; this feature changes how remediations act and report, not which controls they target. Where a shipped remediation would turn on an unrelated setting (for example enabling forking for OSPS-AC-02.01, #513), it is disabled or turned into manual guidance by this feature rather than fixed.
- ASCII-only text; no reference to unpublished security advisories.
