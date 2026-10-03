# Data Model: Remediation Safety

**Feature**: 043-remediation-safety | **Date**: 2026-10-02

All models are pydantic v2 with `extra="forbid"` unless stated. "Digest" means `"sha256:" + hex(sha256(canonical_json(x)))`, with `canonical_json` = `json.dumps(x, sort_keys=True, separators=(",", ":"))`.

## RemediationPolicy (operator configuration)

Section `[remediation]` of the feature 040 operator configuration.

| Field | Type | Default | Notes |
|---|---|---|---|
| `platform` | `Literal["prompt", "manual", "auto"]` | `"prompt"` | Platform changes not classed high-impact. |
| `high_impact` | `Literal["prompt", "manual", "auto"]` | `"prompt"` | Organization-wide settings, repository visibility. |

Read only from operator configuration. The resolved policy and the operator-config digest are copied into every `RemediationRun`.

## PlatformTarget

| Field | Type | Notes |
|---|---|---|
| `kind` | `Literal["branch_protection", "repository", "vulnerability_reporting"]` | |
| `impact` | `Literal["platform", "high_impact"]` | Fixed per kind (`repository` visibility and organization-scoped kinds are high-impact). |
| `owner`, `repo` | `str` | Canonical repository identity (feature 040). |
| `branch` | `str \| None` | `branch_protection` only; resolved default branch unless named. |

## Requirement

What a control needs from a target; declared in TOML on a `platform_setting` handler.

| Kind | Requirement keys |
|---|---|
| `branch_protection` | `require_pull_request: true`, `require_approvals: int >= 1`, `prevent_deletion: true`, `prevent_force_push: true`, `enforce_admins: true`, `require_status_checks: list[str]` (contexts that must be required; existing ones are kept) |
| `repository` | `visibility: "public"` |
| `vulnerability_reporting` | `enabled: true` |

Validation: unknown keys rejected at load; each key has a "stricter" direction used by the comparator (booleans toward the required value, counts as minimums, status-check contexts as a superset of the current set).

## ObservedState

| Field | Type | Notes |
|---|---|---|
| `target` | `PlatformTarget` | |
| `exists` | `bool` | For `branch_protection`: branch protected or not. |
| `fields` | `dict[str, Any]` | Normalized current settings (GET shape translated to the engine's field names). |
| `rules` | `list[dict]` | Active ruleset rules for the branch (all levels). |
| `digest` | `str` | Digest of `fields` + `rules` + `exists`. |
| `read_error` | `ErrorInfo \| None` | Set when any read failed; then nothing may be planned (FR-002). |

## ChangeOperation

| Field | Type | Notes |
|---|---|---|
| `method` | `Literal["PUT", "PATCH", "POST"]` | |
| `endpoint` | `str` | Fully substituted. |
| `body` | `dict \| None` | Exact JSON sent. |
| `changes` | `list[FieldChange]` | `{field, before, after}` for every field this operation changes; fields it re-sends unchanged are not listed. |

## ChangeSet

| Field | Type | Notes |
|---|---|---|
| `target` | `PlatformTarget` | |
| `requirements` | `list[Requirement]` | All requirements for this target in the run, merged. |
| `observed_digest` | `str` | `ObservedState.digest` the plan was computed from. |
| `operations` | `list[ChangeOperation]` | Empty when already satisfied. |
| `satisfied_by` | `Literal["already", "ruleset"] \| None` | Why no operation is needed. |
| `impact_notes` | `list[str]` | High-impact consequences shown in the preview. |
| `digest` | `str` | Digest of `{target, observed_digest, operations}`. |

Invariants: every `FieldChange.after` is equal to or stricter than `before` (FR-003); a `ChangeSet` with a `read_error` cannot exist.

## FileChange

| Field | Type | Notes |
|---|---|---|
| `path` | `str` | Repository-relative. |
| `action` | `Literal["create", "modify", "none"]` | `none` with `reason` (`already_exists`, `user_changes_present`, `when_not_met`). |
| `ignored` | `bool` | The path matches the repository's ignore rules: it is written but never staged or committed (FR-014). |
| `content` | `str \| None` | Resulting content for `create`/`modify`. |
| `before_digest`, `after_digest` | `str \| None` | |
| `project_reference` | `str \| None` | Field to record after a successful create (R9). |

## PlanItem

One entry per remediation step in a preview.

| Field | Type | Notes |
|---|---|---|
| `control_id` | `str` | |
| `step` | `str` | Handler name and index. |
| `file_changes` | `list[FileChange]` | |
| `change_sets` | `list[ChangeSet]` | |
| `commands` | `list[list[str]]` | Exec commands that will run. |
| `previewable` | `bool` | False -> "cannot be previewed exactly" (FR-023). |
| `requires_individual_approval` | `bool` | `safe = false`, not previewable, or high-impact under `prompt`. |
| `digest` | `str` | Digest of the item (used to approve non-platform items individually). |

## Approval

Passed in the apply call; not persisted outside the run record.

| Field | Type | Notes |
|---|---|---|
| `digest` | `str` | A `ChangeSet.digest` or `PlanItem.digest` from the preview. |
| `approved_by` | `str` | Operator identity (feature 040). |
| `approved_at` | `datetime` | |

Rule: a high-impact `ChangeSet` or an individually-approved `PlanItem` is applied only if its own digest is listed.

## RemediationOutcome

| Field | Type | Notes |
|---|---|---|
| `control_id` | `str` | |
| `kind` | `Literal["fixed", "changed_not_passing", "changed_not_verified", "unchanged", "needs_approval", "needs_confirmation", "manual", "error"]` | FR-017 |
| `file_changes` | `list[FileChange]` | Applied (or, for `unchanged`, the reasons). |
| `change_sets` | `list[ChangeSet]` | Applied, with read-back result. |
| `recheck` | `ControlResult \| None` | Status after re-check (feature 041 result). |
| `reason` | `str \| None` | |
| `error` | `ErrorInfo \| None` | Feature 041 error class and cause. |

Transitions (apply mode):

```text
plan -> [confirmation missing]            -> needs_confirmation
     -> [manual only / policy manual]     -> manual
     -> [needs approval, none given]      -> needs_approval
     -> [stale digest]                    -> unchanged (reason: stale_preview)
     -> [no operations, no file changes]  -> unchanged (reason from FileChange/ChangeSet)
     -> apply -> [any step error]         -> error (partial changes listed)
              -> recheck -> PASS          -> fixed
                         -> not PASS      -> changed_not_passing
                         -> could not run -> changed_not_verified
```

## RemediationRun

| Field | Type | Notes |
|---|---|---|
| `run_id` | `str` | ULID. |
| `repository` | `str` | Canonical identity. |
| `mode` | `Literal["preview", "apply"]` | |
| `policy` | `RemediationPolicy` | |
| `operator_config_digest` | `str` | |
| `approvals` | `list[Approval]` | |
| `plan` | `list[PlanItem]` | |
| `outcomes` | `list[RemediationOutcome]` | Apply only. |
| `summary` | `dict[str, int]` | Counts per outcome kind, derived from `outcomes`. |

## RunManifest (operator-side)

File `user_data_root()/remediation/<repository-identity>/<run_id>.json`, mode 0600, refused inside the checkout. Written in apply mode only; a preview writes no manifest.

| Field | Type | Notes |
|---|---|---|
| `run_id`, `repository`, `created_at` | | |
| `files` | `list[{path, after_digest}]` | Every file the executor wrote, less any a failed exec step changed afterwards. |
| `change_sets` | `list[str]` | Applied change-set digests. |
| `branch` | `str \| None` | Remediation branch, if created. |
| `base`, `base_commit` | `str \| None` | The ref a pull request from `branch` targets, and its commit, recorded with the branch (replaced, or cleared when unresolved, when the run moves to another branch); the PR tool targets `base` and uses `base_commit` only when the `base` ref cannot be resolved. |
| `commit` | `str \| None` | Set by the commit tool. |

The commit tool stages exactly `files` whose current digest equals `after_digest`.
