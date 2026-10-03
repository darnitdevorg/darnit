# Contract: Remediation Interfaces

**Feature**: 043-remediation-safety | **Date**: 2026-10-02

Observable surfaces another component (agent, skill, CI, plugin, operator) can rely on. Models are in [data-model.md](../data-model.md).

## 1. Operator configuration

```toml
[remediation]
platform = "prompt"     # prompt | manual | auto
high_impact = "prompt"  # prompt | manual | auto
```

- Unknown keys or values stop the run (feature 040 rule).
- Absent section = both `prompt`.
- `darnit config show` prints the resolved section.

## 2. Framework TOML

### 2.1 `platform_setting` remediation handler (new)

```toml
[[controls."<ID>".remediation.handlers]]
handler = "platform_setting"
target = "branch_protection"          # branch_protection | repository | vulnerability_reporting
require = { require_approvals = 1 }   # keys per target, data-model "Requirement"
branch = "release"                    # optional; default = repository default branch
```

### 2.2 `file_create`

Adds optional `project_reference = "<section.field>"` (R9).

### 2.3 `exec` remediation

Adds:

- `effects = "working_tree"`: required for the step to be previewable.
- `offline = true`: required for scratch-copy preview.

A shipped exec remediation whose command is `gh`, `curl`, `wget`, or `git push` fails `validate_sync`.

### 2.4 Removed

The following fail schema validation with a message naming the replacement:

- the `api_call` handler;
- `requires_confirmation`;
- `dry_run_supported`;
- `dry_run_command`.

### 2.5 `safe`

`safe = false` means the step requires individual approval in a batch apply.

## 3. MCP tools

### 3.1 `remediate_audit_findings`

| Parameter | Change |
|---|---|
| `dry_run: bool = True` | unchanged default |
| `approve: list[str] \| None = None` | new: change-set and plan-item digests the person approved |
| `branch_name`, `auto_commit`, `create_pr` | unchanged names; git rules per section 3.3 |

Response shape: the Markdown report, followed by a fenced JSON block holding the `RemediationRun`:

- **preview:** `plan`, with every digest, `previewable` and `requires_individual_approval`;
- **apply:** `outcomes` and `summary`.

Behavior:

- When the pending-context check cannot complete, the call returns an error and nothing runs.
- Under `prompt`, an apply without the needed digests yields `needs_approval` outcomes; nothing is written for those items.

### 3.2 `enable_branch_protection`

| Parameter | Change |
|---|---|
| `dry_run: bool = True` | was False |
| `branch: str \| None = None` | was `"main"`; None = default branch |
| `required_approvals`, `require_pull_request` | become requirements (`require_approvals`, `require_pull_request`); never lower existing values |
| `enforce_admins`, `require_status_checks`, `status_checks` | become requirements that only tighten; never remove existing checks |
| `approve: str \| None` | new: change-set digest |

The response follows the 3.1 shape, for a single target.

### 3.3 Git tools

**Shared rule:** all three tools take `run_id: str | None = None`, meaning the latest run for the repository.

**`create_remediation_branch`**
- Never stashes.
- A new branch keeps the user's uncommitted changes untouched in the working tree.
- An existing branch requires a clean tree, and every commit beyond the base must carry the `Darnit-Remediation-Run` trailer.
- It refuses on a detached HEAD, a merge in progress, or a rebase in progress.

**`commit_remediation_changes`**
- Stages only the run manifest's files, and only those whose digest is unchanged since remediation wrote them.
- Never stages ignored files.
- Adds the trailer `Darnit-Remediation-Run: <run_id>` to the commit message.
- The response lists every committed file.
- `add_all` is removed.

**`create_remediation_pr`**
- Pushes only the remediation branch.

### 3.4 `remediate_community_spec` (darnit-csl)

- Adds `dry_run: bool = True`.
- Its README edit is a `FileChange` and appears in the manifest.

### 3.5 `confirm_*` tools

Unchanged. Approvals are not confirmations, and are not stored in the confirmation store.

## 4. CLI

`darnit run`:

- Previews remediation by default; `--apply` is required to write files or change platform settings (FR-027).
- Platform changes follow `[remediation]`.
- Under `prompt` with a TTY, it shows each change set and asks on `/dev/tty`.
- Without a TTY, the outcome is `needs_approval` and the exit code is unchanged from today's "remediation incomplete" path.
- Items that need individual approval (`safe = false`, not previewable, high-impact) are asked for on `/dev/tty` by their digest when interactive, and otherwise end as `needs_approval`.

## 5. Report fields (Markdown and JSON)

**Per control:**
- outcome `kind`;
- files changed;
- platform fields `before -> after`;
- re-check status;
- reason and error.

**Per run:**
- policy;
- operator config digest;
- approvals (digest, by, at);
- run id;
- summary counts.

**For high-impact changes:** the preview lists the impact notes.

## 6. Plugin handler contract

**Remediation handlers:**
- They receive `HandlerContext.mode` (`plan` or `apply`).
- They return planned `FileChange`s and `ChangeSet`s in their evidence, and must not write in `plan` mode.

A handler that does not declare `supports_plan = True` at registration is treated as not previewable.

## 7. Attestation and audit

- No change to audit results or the attestation predicate.
- A re-check is an audit subset run that does not write the audit cache.
