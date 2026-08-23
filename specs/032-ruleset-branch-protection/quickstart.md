# Quickstart: `github_branch_protection` sieve handler

Two worked examples. First is the control-author perspective (updating the four TOML controls to use the new handler). Second is the operator debugging perspective (interpreting a WARN in the audit output).

## Example 1: Control author updates a branch-protection control

`OSPS-AC-03.01` today has an `exec` pass that shells `gh api /repos/$OWNER/$REPO/branches/$BRANCH/protection` and a CEL post-step that checks `has(output.json.required_pull_request_reviews)`. That combination produces a false FAIL for a repo protected via a ruleset. The new pass replaces it with the handler.

### Before

```toml
[[controls."OSPS-AC-03.01".passes]]
handler = "exec"
command = ["gh", "api", "/repos/$OWNER/$REPO/branches/$BRANCH/protection"]
pass_exit_codes = [0]
fail_exit_codes = [1]
output_format = "json"
expr = 'has(output.json.required_pull_request_reviews)'
timeout = 30
```

### After

```toml
[[controls."OSPS-AC-03.01".passes]]
handler = "github_branch_protection"
requirement = "require_pull_request"
timeout = 30
```

Six lines replaced with three. The `manual` trailing pass in the control is unchanged.

Analogously for the other three controls:

- `OSPS-AC-03.02` -> `requirement = "prevent_deletion"`
- `OSPS-QA-03.01` -> `requirement = "require_status_checks"`
- `OSPS-QA-07.01` -> `requirement = "require_approvals"` (defaults to `required_approvals_minimum = 1`, which matches the existing behavior)

### What happens at audit time

1. The sieve orchestrator dispatches the handler for `OSPS-AC-03.01` on a repository.
2. Handler queries `gh api /repos/{owner}/{repo}/branches/{branch}/protection`.
3. If the response is 200 AND carries `required_pull_request_reviews`: PASS from classic. Evidence: `source = "classic"`, `classic_status = 200`.
4. Otherwise (any 404, or 200 without `required_pull_request_reviews`): handler queries `gh api --paginate /repos/{owner}/{repo}/rulesets`.
5. For each active ruleset in the list, handler fetches `/repos/{owner}/{repo}/rulesets/{id}` and checks whether the ruleset targets the audited branch (via `conditions.ref_name`) AND carries a `pull_request` rule.
6. First matching ruleset: PASS from ruleset. Evidence: `source = "ruleset"`, `matched_ruleset = {id, name}`.
7. All rulesets exhausted without a match: FAIL. Evidence: `source = "neither-surface-provided-protection"` with the list of considered rulesets and why each did not match.
8. Any 401/403/5xx/429 from either surface, or a mid-pagination failure: INCONCLUSIVE -> falls through to the manual pass -> WARN. Evidence: `source = "insufficient-access"` or `"partial-fetch"`.

## Example 2: Operator debugging a WARN in the audit report

Running `darnit audit` against a fleet, `OSPS-QA-07.01` came back WARN for one repo. The audit report includes:

```json
{
  "id": "OSPS-QA-07.01",
  "status": "WARN",
  "evidence": {
    "source": "insufficient-access",
    "requirement": "require_approvals",
    "classic_status": 403,
    "rulesets_status": 0
  }
}
```

Read the evidence:

- `classic_status: 403` — the classic branch-protection endpoint refused to answer.
- `rulesets_status: 0` — the handler never got to the rulesets endpoint because the classic call failed first (and a 403 from classic short-circuits to INCONCLUSIVE without consulting rulesets, since we cannot distinguish "no protection classic-side" from "we cannot read protection classic-side").

Fix: reauthenticate the `gh` CLI with `admin:read` scope (or the fine-grained equivalent "Read access to repository administration"). Rerun the audit.

### Alternate scenario: rate limit hit mid-pagination

```json
{
  "id": "OSPS-AC-03.01",
  "status": "WARN",
  "evidence": {
    "source": "partial-fetch",
    "requirement": "require_pull_request",
    "classic_status": 404,
    "rulesets_status": 429
  }
}
```

Read:

- `classic_status: 404` — no classic protection, so the handler needed to consult rulesets.
- `rulesets_status: 429` — GitHub rate-limited the request mid-list.
- `source: "partial-fetch"` — we did not fully enumerate the rulesets surface, so we cannot confidently FAIL.

Fix: wait out the rate-limit window (`gh api rate_limit` shows the reset time) or reduce audit parallelism, then rerun.

### Alternate scenario: FAIL with rulesets considered

```json
{
  "id": "OSPS-AC-03.01",
  "status": "FAIL",
  "evidence": {
    "source": "neither-surface-provided-protection",
    "requirement": "require_pull_request",
    "classic_status": 404,
    "rulesets_status": 200,
    "considered_rulesets": [
      {"id": 1234, "name": "Signed commits", "reason": "no matching rule type"},
      {"id": 5678, "name": "Tag protection", "reason": "targets tags not branches"}
    ],
    "considered_rulesets_truncated": 0
  }
}
```

Read:

- Classic returned 404 and rulesets exist, but neither `Signed commits` nor `Tag protection` requires pull requests on the audited branch.
- Fix: create or extend a repository ruleset on the default branch with a `pull_request` rule, or enable classic branch protection with `required_pull_request_reviews`. The control's `help_md` (unchanged from today) links to the GitHub docs.

## Manual smoke-test against a live GitHub repo

The CI test suite uses in-process fixtures (see `tests/darnit_baseline/test_branch_protection_handler.py`) and does not hit live GitHub. For a manual smoke-test:

1. Point at a repo you know is protected via classic branch protection:
   `uv run darnit audit --local-path <path> --controls OSPS-AC-03.01 OSPS-AC-03.02 OSPS-QA-03.01 OSPS-QA-07.01`
   Expect: all four PASS with `source: "classic"`.

2. Point at a repo protected via ruleset only (or use a scratch repo where you delete classic protection but add a ruleset via `gh api` PUT). Same command. Expect: all four PASS with `source: "ruleset"` and populated `matched_ruleset`.

3. Point at a repo with no protection (a fresh test repo). Expect: all four FAIL with `source: "neither-surface-provided-protection"`.

4. Deauthenticate `gh` (`gh auth logout`). Rerun. Expect: WARN across the four with `source: "insufficient-access"`.

## Non-goals reminder

This feature does NOT:

- Consult organization-level rulesets (org-level rulesets are surfaced via a different endpoint; a v0.1 follow-up).
- Treat evaluate-mode rulesets as satisfying protection (only `enforcement = "active"` counts).
- Match glob-pattern ref-name conditions (they appear in `considered_rulesets` as "unmatched glob pattern" but do not satisfy).
- Extend to non-GitHub platforms (the `when = { platform = "github" }` guard on all four controls keeps this feature invisible to non-GitHub audits).

## Where to look next

- Contract: `contracts/github-branch-protection-handler.md` -- exhaustive field, evidence, and failure-mode table.
- Data model: `data-model.md` -- the schema types this feature adds.
- Research decisions: `research.md` -- why the handler lives in baseline, why `--paginate`, why module-level test substitution.
- Follow-up for organization-level rulesets: to be filed after v0 lands.
