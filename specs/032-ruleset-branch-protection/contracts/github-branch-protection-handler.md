# Contract: `github_branch_protection` sieve handler

**Owner**: `packages/darnit-baseline/` (registered under short name `github_branch_protection` by `darnit_baseline.implementation.register_handlers`)

**Purpose**: Encapsulate the "protection may live in either classic branch-protection OR a repository ruleset" decision so the four OSPS branch-protection controls (`OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`) can consult both surfaces uniformly.

**Stability**: Handler name and TOML surface are stable within v0. Additive changes (new `requirement` enum members, new evidence fields) are non-breaking; removals or renames require a coordinated spec + TOML update.

## TOML pass surface

The handler is invoked declaratively via a TOML pass entry with `handler = "github_branch_protection"`:

```toml
[[controls."OSPS-AC-03.01".passes]]
handler = "github_branch_protection"
requirement = "require_pull_request"
timeout = 30
```

### Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `handler` | string | yes | `"github_branch_protection"` | Set by the TOML `handler = "..."` key. Fixed value for this handler. |
| `requirement` | string | yes | (none) | One of `require_pull_request`, `prevent_deletion`, `require_status_checks`, `require_approvals`. Selects which protection the handler tests for. |
| `owner` | string | no | `$OWNER` | Repository owner. Substituted by the sieve's variable-substitution pass before dispatch. |
| `repo` | string | no | `$REPO` | Repository name. Substituted before dispatch. |
| `branch` | string | no | `$BRANCH` | Branch being audited. Substituted before dispatch; typically resolves to the repository's default branch. |
| `required_approvals_minimum` | integer | no | `1` | Only meaningful when `requirement == "require_approvals"`; ignored otherwise. Range 1..10 inclusive. |
| `timeout` | integer | no | `30` | Total time budget in seconds for both surfaces (including pagination). Applied by wrapping each `gh api` invocation with `--jq . | ` (implicit) and honoured by the handler's overall run loop. |

### Rejected TOML shapes

- `handler = "gh_branch_protection"` — the abbreviation contradicts other product-name-spelled handlers in darnit. Use `github_` prefix.
- Placing `requirement` inside a nested `parameters` object — flat is the darnit-handler convention (`file_exists` uses top-level `files`, not `parameters.files`).
- Using CEL `expr` alongside the handler — the handler decides PASS/FAIL/INCONCLUSIVE itself; CEL post-step is a no-op here and MUST NOT be added.

## Verdict semantics

| Situation | Control status | Evidence `source` |
|-----------|----------------|-------------------|
| Classic surface 200 AND carries the required signal | PASS | `classic` |
| Classic 404 AND rulesets list 200 AND at least one active ruleset targets branch AND satisfies requirement | PASS | `ruleset` |
| Classic 200 without required signal AND rulesets list 200 AND at least one active ruleset targets branch AND satisfies requirement | PASS | `ruleset` |
| Classic 404 AND rulesets list 200 empty | FAIL | `neither-surface-provided-protection` |
| Classic 404 AND rulesets list 200 non-empty AND no active ruleset targets branch | FAIL | `neither-surface-provided-protection` |
| Classic 200 without required signal AND rulesets list 200 AND no active ruleset satisfies requirement | FAIL | `neither-surface-provided-protection` |
| Classic 401/403 | INCONCLUSIVE (WARN) | `insufficient-access` |
| Rulesets list 401/403 (classic was 404 or lacking-signal) | INCONCLUSIVE (WARN) | `insufficient-access` |
| Classic 429/5xx/network-error | INCONCLUSIVE (WARN) | `insufficient-access` |
| Rulesets list 429/5xx/network-error (classic was 404 or lacking-signal) | INCONCLUSIVE (WARN) | `insufficient-access` |
| Rulesets list 200 but a per-ruleset detail call (or later page) fails | INCONCLUSIVE (WARN) | `partial-fetch` |
| Rulesets list 200 non-empty AND every targeting ruleset is in `enforcement = "evaluate"` or `"disabled"` | FAIL | `neither-surface-provided-protection` (evaluate/disabled rulesets do NOT satisfy, per FR-012) |
| Classic 200 without required signal (e.g., ruleset-only protection has both surfaces) AND classic status is unknown | falls under whichever pattern above applies | (n/a) |

An INCONCLUSIVE from this handler falls through to the trailing manual-pass in the affected control's pass list, which resolves the control to WARN with human-verification steps. This matches feature 019's semantic and is the reason no CEL post-step is used.

## Evidence record shape

The handler writes the following into `HandlerResult.evidence`. Downstream consumers (Markdown formatter, JSON output, SARIF exporter) treat unknown keys as opaque, matching feature 019's evidence-additive posture.

```json
{
    "source": "classic|ruleset|neither-surface-provided-protection|insufficient-access|partial-fetch",
    "requirement": "require_pull_request|prevent_deletion|require_status_checks|require_approvals",
    "classic_status": 200,
    "rulesets_status": 200,
    "matched_ruleset": {"id": 12345, "name": "Protect main"},
    "considered_rulesets": [
        {"id": 67890, "name": "Signed commits only", "reason": "no matching rule type"}
    ],
    "considered_rulesets_truncated": 0
}
```

Population rules (locked by data-model.md):

- `source`, `requirement`, `classic_status` always present.
- `rulesets_status` present iff the handler reached the rulesets endpoint (any source except `classic`).
- `matched_ruleset` present iff `source == "ruleset"`.
- `considered_rulesets` present iff `source == "neither-surface-provided-protection"` AND at least one active ruleset targeted the branch. Capped at 20 entries; `considered_rulesets_truncated` records the count of elided entries.

## Failure-mode table

Every distinguishable failure and the resulting control status:

| Failure | Control status | Evidence `source` | Message shape |
|---------|----------------|-------------------|---------------|
| Classic 404, no rulesets targeting branch | FAIL | `neither-surface-provided-protection` | `no branch protection found via classic API or repository rulesets` |
| Classic 200, missing signal; rulesets do not carry it either | FAIL | `neither-surface-provided-protection` | `neither classic branch protection nor any active ruleset requires <requirement>` |
| Classic 401/403 | WARN | `insufficient-access` | `insufficient permissions to read classic branch protection (HTTP 403)` |
| Rulesets 401/403 (classic was inconclusive) | WARN | `insufficient-access` | `insufficient permissions to read repository rulesets (HTTP 403)` |
| Classic 5xx / rate limit | WARN | `insufficient-access` | `classic branch-protection endpoint returned HTTP <code>` |
| Rulesets 5xx / rate limit | WARN | `insufficient-access` | `rulesets endpoint returned HTTP <code>` |
| Rulesets list 200 but a detail call fails | WARN | `partial-fetch` | `failed to fetch ruleset <id> detail: HTTP <code>` |
| Rulesets list 200 mid-pagination page fails | WARN | `partial-fetch` | `failed to fetch rulesets page: HTTP <code>` |
| `gh` CLI missing entirely | WARN | `insufficient-access` | `GitHub CLI (gh) not found. Install it from https://cli.github.com/` |
| Handler config missing `requirement` | ERROR (not INCONCLUSIVE) | (evidence source omitted; this is a control-author bug) | `handler github_branch_protection requires 'requirement' field` |
| Handler config has unknown `requirement` value | ERROR | (as above) | `unknown requirement '<value>'` |
| Handler config has `required_approvals_minimum` outside 1..10 | ERROR | (as above) | `required_approvals_minimum must be 1..10` |

## Non-goals for v0

The following are DELIBERATELY NOT COVERED in v0 and MUST NOT be relied upon:

- **Organization-level rulesets.** GitHub allows an organization to define rulesets at `/orgs/{org}/rulesets` that repositories inherit. v0 checks only `/repos/{owner}/{repo}/rulesets`; org-level rulesets appear at the repo level ONLY as `source_type: "Organization"` list entries but the detail fetch still goes through the repo endpoint. The rare case of an org-only ruleset applying without being surfaced on the repo endpoint is a v0.1 follow-up (issue to be filed at task time).
- **Evaluate-mode rulesets.** A ruleset in `enforcement = "evaluate"` is a dry-run: GitHub reports what would be blocked but does not block. v0 treats evaluate-mode as "does not protect." Documented in FR-012.
- **Glob-pattern ref-name matching.** Ref-name include lists containing `*`, `?`, or `[` metacharacters are treated as "does not match" and surfaced in `considered_rulesets`. See research decision R-003.
- **Generalization beyond the four OSPS controls.** The handler is a general primitive (any control can call it), but the OSPS TOML changes touch only the four named controls. Adopting the handler for other controls is a future PR.
- **Non-GitHub platforms.** GitLab, Bitbucket, and Gitea protection surfaces are entirely different and are not addressed here. The four controls carry `when = { platform = "github" }`, which excludes them from non-GitHub audits.

## Contract stability guarantees

- The TOML `handler = "github_branch_protection"` name is stable within v0.
- The `requirement` enum values (`require_pull_request`, `prevent_deletion`, `require_status_checks`, `require_approvals`) are stable within v0. New members are additive.
- The `VerdictSource` values (`classic`, `ruleset`, `neither-surface-provided-protection`, `insufficient-access`, `partial-fetch`) are stable within v0. New members are additive.
- The evidence-record fields listed above are stable within v0. Additional fields may be added; existing fields will not be removed or renamed without a major-version bump.
