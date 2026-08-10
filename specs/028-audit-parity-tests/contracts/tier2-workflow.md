# Contract: Tier 2 Workflow Configuration + Governance

**Feature**: 028-audit-parity-tests | **Consumers**: maintainers configuring the GitHub Actions Environment, reviewers approving Tier 2 dispatches, auditors verifying access-control compliance.

Tier 2 is a manual-dispatch-only GitHub Actions workflow that invokes the `/darnit-audit` coding-agent skill via the Claude Agent SDK, diffs against the raw MCP tool output, and captures the drift. The workflow's security posture is the load-bearing property.

## 1. Trigger + Environment

- **T2-1**: The workflow is triggered EXCLUSIVELY by `workflow_dispatch`. No `push`, no `pull_request`, no `schedule` trigger.
- **T2-2**: The workflow's job MUST declare `environment: parity-tier2` (name is the exact string; case-sensitive).
- **T2-3**: The GitHub Environment `parity-tier2` MUST be configured (via GitHub UI, not via YAML in the repo) with:
  - A required-reviewers list of authorized maintainers.
  - The `ANTHROPIC_API_KEY` secret stored AT THE ENVIRONMENT LEVEL, not at the repository level.
- **T2-4**: No other workflow file in `.github/workflows/` references `secrets.ANTHROPIC_API_KEY`. Verifiable via `grep -r 'ANTHROPIC_API_KEY' .github/workflows/ | grep -v parity-tier2.yml` returning zero lines. This is SC-005a's assertion.

## 2. Permissions

- **T2-5**: The workflow job MUST declare `permissions: contents: read` at the job level. No `write` scope is granted to any resource.
- **T2-6**: The workflow MUST NOT use any Action that requires a token with elevated scope (e.g., no `peter-evans/create-pull-request`).

## 3. Preflight audit

- **T2-7**: Before the SDK invocation step, the workflow MUST log to `GITHUB_STEP_SUMMARY`:
  - The actor (`github.actor`) who triggered the dispatch.
  - The commit SHA.
  - The exact `fixture_glob` input value.
  - The current wall-clock timestamp.
- **T2-8**: The preflight step MUST be BEFORE the step that consumes `ANTHROPIC_API_KEY`, so a post-hoc audit can attribute cost even if the API call itself fails.

## 4. Input parameters

- **T2-9**: The workflow accepts exactly one input, `fixture_glob`, defaulting to `"*"`. It filters which fixtures under `tests/darnit/parity/fixtures/` are exercised.
- **T2-10**: The workflow MUST NOT accept an API key as an input parameter (per FR-007b). Adding one is a governance regression.

## 5. Artifact upload

- **T2-11**: On any exit code (0 or non-zero), the workflow MUST upload the contents of `parity-artifacts/` via `actions/upload-artifact`. Failure to upload is itself a workflow failure.
- **T2-12**: Artifact retention MUST NOT exceed 90 days by default (Anthropic API calls have IP addresses / timestamps in their transcripts; long retention increases surface).

## 6. Exit codes + reporting

- **T2-13**: The runner Python script (`tests/darnit/parity/tier2/run.py`) exits with:
  - `0` iff every fixture's skill output agrees with the raw tool output on per-control status.
  - `1` if any fixture has a skill-vs-tool disagreement.
  - `2` if any fixture's skill output was unparseable (distinct from disagreement).
  - `3` for setup errors (missing key, missing fixtures, SDK import failure).
  - `4` for rate-limit exhaustion (partial results captured, artifacts uploaded, workflow fails).
- **T2-14**: A summary of the failure classes is written to `GITHUB_STEP_SUMMARY` even on success, so the auditor sees "N fixtures checked, 0 drifts" as evidence.

## 7. Rate limit + retry

- **T2-15**: The runner MUST NOT retry API calls automatically. A rate-limit hit is a documented failure (`exit 4`) with instructions in the summary to re-dispatch manually.
- **T2-16**: Each fixture MUST be exercised at most once per workflow invocation. Multiple invocations to work around a rate limit are the maintainer's manual choice.

## 8. What Tier 2 does NOT do

- **T2-17**: Does not automatically remediate any drift. Diagnostic only (FR-016).
- **T2-18**: Does not modify the `/darnit-audit` skill under any circumstance.
- **T2-19**: Does not modify any darnit product package.
- **T2-20**: Does not attempt to run without `ANTHROPIC_API_KEY`; silent skip is forbidden (FR-010).

## 9. Test coverage of the workflow itself

- **T2-21**: A test at `tests/darnit/parity/tier2/test_workflow_config.py` (Tier 1 -- offline) parses `.github/workflows/parity-tier2.yml` as YAML and asserts:
  - Only trigger is `workflow_dispatch`.
  - Job declares `environment: parity-tier2`.
  - Job declares `permissions: contents: read`.
  - `ANTHROPIC_API_KEY` is only referenced under an `env:` block in the SDK-invocation step.
- **T2-22**: A test in the same file greps `.github/workflows/` for `ANTHROPIC_API_KEY` references outside `parity-tier2.yml` and asserts the count is zero.

## 10. Governance escalation

- **T2-23**: If the workflow YAML is modified in a way that removes any of T2-1 through T2-6 (trigger, environment, permissions, secret scope), that PR MUST be reviewed by TWO maintainers (a two-person integrity rule for security-critical config). This is enforced via CODEOWNERS or branch protection rather than YAML.
- **T2-24**: A modification to `.github/workflows/parity-tier2.yml` in the same PR as an unrelated feature is a code smell and SHOULD be split into a dedicated PR for review clarity.
