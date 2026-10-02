# Quickstart: Validating Remediation Safety

**Feature**: 043-remediation-safety | **Date**: 2026-10-02

Run from the repository root.

## Prerequisites

- `uv sync`
- Tests use recorded platform responses (`RecordedGhApi`, extended for writes per research R12); no network or token is needed.
- Isolated operator config and data root come from the existing autouse fixtures.

Optional live check (V1 live) needs a disposable GitHub repository you administer and `gh auth status` OK.

## V1. Branch protection never weakens settings (US1, SC-001)

```bash
uv run pytest tests/darnit/remediation/platform/ -k "stricter or unprotected or ruleset or unknown_field or read_failure" -v
```

**Fixture: stricter existing protection** (two approvals, required checks, push restrictions, code-owner review, linear history).

- Preview of AC-03.01, AC-03.02 and QA-07.01 lists at most `allow_deletions: true -> false`.
- Apply sends one PUT whose body preserves every other field.
- Read-back shows the original values.

**Other fixtures:**

| Fixture | Expected |
|---|---|
| Already satisfied | No write; outcome `unchanged` (`satisfied_by: already`) |
| Ruleset-only | No classic protection write; outcome `unchanged` (`satisfied_by: ruleset`) |
| GET contains an unknown field | ERROR "cannot preserve unknown protection setting"; no write |
| Read failure | ERROR with cause; no write |

**V1 live (optional, disposable repository):**

1. Configure stricter protection in the UI.
2. Run `enable_branch_protection` with no arguments. It previews only.
3. Pass the printed digest as `approve`.
4. Check that the settings page still shows every original setting.

## V2. Approval binding and policy (US1, FR-005, FR-026)

```bash
uv run pytest tests/darnit/remediation/platform/test_policy.py tests/darnit/remediation/platform/test_approval.py -v
```

**Policy `prompt`:**

| Apply request | Expected |
|---|---|
| No digest | `needs_approval`; 0 writes |
| Correct digest | 1 write |
| Digest, but the recorded state changed between preview and apply | `unchanged` (`stale_preview`); 0 writes |
| Batch apply with only non-high-impact digests | Visibility change not applied |

**Other policies:**

- `manual`: 0 writes; the outcome carries the steps.
- `auto`: writes without a digest; the report shows `policy.platform = auto`.
- A `[remediation]` block placed in the audited repository's `.baseline.toml` or `.project/` is ignored.

## V3. Commits contain only remediation's files (US2, SC-003)

```bash
uv run pytest tests/darnit/server/test_git_operations_safety.py -v
```

**Scratch repository:** a modified tracked file, an untracked `.env`, and one stash.

**Run:** apply remediation with `branch_name`, `auto_commit` and `create_pr`, against a stubbed remote.

**Expected:**

- The commit's files equal the manifest's files.
- The modified file and `.env` remain uncommitted and byte-identical.
- `git stash list` is unchanged.
- The commit message has the `Darnit-Remediation-Run` trailer.

**Refusal cases:** detached HEAD, a merge in progress, and an existing branch with foreign commits are each refused with 0 changes.

## V4. Project references (US3, SC-006)

```bash
uv run pytest tests/darnit_baseline/test_project_reference.py -v
```

- `.project/project.yaml` already names `security.policy: SECURITY.md`. Remediating DO-02.01 leaves it unchanged.
- Every `project_reference` declared in the Baseline TOML matches the field's known file locations.

## V5. Truthful outcomes and re-check (US4, SC-004)

```bash
uv run pytest tests/darnit_baseline/remediation/test_outcomes.py -v
```

**Mixed fixture:**

| Control | Expected outcome |
|---|---|
| SECURITY.md already exists | `unchanged` (`already_exists`) |
| CONTRIBUTING.md created | `fixed` (re-check PASS) |
| A control still failing after a change | `changed_not_passing` |
| A handler error | `error` |

**Also verify:**

- The summary counts equal the outcome counts.
- Every `fixed` control passes a fresh audit.
- The full-audit cache is unchanged by the re-check.

## V6. Preview equals apply (US5, SC-005, SC-007)

```bash
uv run pytest tests/darnit/remediation/test_plan_contract.py -v
uv run python scripts/validate_sync.py --verbose
```

**For every remediation in every shipped framework TOML:**

- Plan mode on a fixture produces 0 filesystem changes and 0 recorded writes.
- Apply's changes equal the plan's.
- Non-previewable steps are flagged, and are excluded from batch apply without an individual digest.

`validate_sync` rejects each of the following in shipped TOML:

- `api_call`;
- `dry_run_supported`, `dry_run_command`, `requires_confirmation`;
- an exec remediation calling `gh`, `curl`, `wget` or `git push`.

## V7. Regression

```bash
uv run ruff check .
uv run pytest tests/ -q
uv run python scripts/validate_sync.py --verbose
```
