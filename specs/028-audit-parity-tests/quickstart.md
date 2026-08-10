# Quickstart: Two-Tier Audit Parity Tests

**Feature**: 028-audit-parity-tests | **For**: maintainers running Tier 1 locally on a PR, or authorized reviewers dispatching Tier 2 to check for coding-agent skill drift.

## Tier 1: run locally on every PR

```bash
# Full suite (fast; no live API)
uv run pytest tests/darnit/parity/tier1/ -q

# Single fixture
uv run pytest tests/darnit/parity/tier1/test_mcp_vs_harness.py -q -k "mixed_repo"

# See the per-fixture summary lines even on green
uv run pytest tests/darnit/parity/tier1/ -v -s
```

Expected on a green run:

```
tests/darnit/parity/tier1/test_mcp_vs_harness.py::test_parity[all_pass_repo] PASSED
tests/darnit/parity/tier1/test_mcp_vs_harness.py::test_parity[all_fail_repo] PASSED
tests/darnit/parity/tier1/test_mcp_vs_harness.py::test_parity[mixed_repo] PASSED
tests/darnit/parity/tier1/test_mcp_vs_harness.py::test_parity[pending_llm_repo] PASSED

[tier1] all_pass_repo:      8 controls compared, 8 agreed, 0 diverged, 0 allowed-drift
[tier1] all_fail_repo:     12 controls compared, 12 agreed, 0 diverged, 0 allowed-drift
[tier1] mixed_repo:        14 controls compared, 14 agreed, 0 diverged, 0 allowed-drift
[tier1] pending_llm_repo:  15 controls compared, 14 agreed, 0 diverged, 1 allowed-drift (PENDING_LLM->WARN)
```

Expected on a failure (harness silently disagreeing with the tool on OSPS-GV-01.01):

```
FAILED tests/darnit/parity/tier1/test_mcp_vs_harness.py::test_parity[mixed_repo]

Assertion: harness disagrees with MCP tool beyond documented allowed drift.

| control_id     | mcp_status | harness_status |
|----------------|------------|----------------|
| OSPS-GV-01.01  | PASS       | FAIL           |
```

## Adding a new fixture

```bash
# 1. Create the fixture directory + files
mkdir -p tests/darnit/parity/fixtures/my_new_fixture
cd tests/darnit/parity/fixtures/my_new_fixture
touch .baseline.toml
# ... populate with the file set your controls exercise

# 2. Run the audit to capture expected counts
uv run python -c "
from darnit_baseline.tools import audit_openssf_baseline
import json
result = json.loads(audit_openssf_baseline(local_path='.', level=1, output_format='json'))
counts = {}
for c in result['results']:
    counts[c['status'].lower()] = counts.get(c['status'].lower(), 0) + 1
print(counts)
"

# 3. Write parity.toml with the captured counts
cat > parity.toml <<'EOF'
[expected]
category = "mixed"

[expected.counts]
pass = 4
fail = 2
warn = 1
error = 0
n_a = 3
pending_llm = 0
EOF

# 4. Verify the new fixture is picked up
uv run pytest tests/darnit/parity/tier1/ -q -k "my_new_fixture"
```

No test file changes needed -- the fixture is auto-discovered by `conftest.py`.

## Tier 2: dispatch via GitHub Actions (authorized reviewers only)

Tier 2 is **NOT** run automatically. It is triggered manually by an authorized maintainer.

```bash
# From gh CLI (requires push access to the repo)
gh workflow run parity-tier2.yml --repo darnitdevorg/darnit -f fixture_glob="*"

# Or from the GitHub UI:
# Actions -> "Parity Tier 2" -> Run workflow -> approve when prompted
```

Because the workflow uses a required-reviewer Environment, the run will PAUSE at the approval gate until an authorized reviewer clicks "Approve." Only then does the `ANTHROPIC_API_KEY` become available to the job.

### On success (workflow exits 0)

- Green check on the workflow run.
- `parity-artifacts/` uploaded as a workflow artifact for every fixture.
- Summary in the job's `GITHUB_STEP_SUMMARY`:

  ```
  Tier 2 parity check: 4 fixtures checked, 0 drifts, 0 unparseable, 0 rate-limited
  ```

### On failure

Exit codes tell you the failure class:

- `exit 1`: skill and tool disagree on per-control status. `parity-artifacts/<fixture>/diff_report.md` shows which control(s).
- `exit 2`: skill output couldn't be parsed. Inspect `parity-artifacts/<fixture>/skill_final_message.md` to see what the skill produced.
- `exit 3`: setup error (missing key, missing fixture, SDK import failure). Check the workflow logs.
- `exit 4`: rate limit exhausted mid-run. Partial results in artifacts; re-dispatch later.

### Reviewing artifacts locally

```bash
gh run download --repo darnitdevorg/darnit <run-id>
cd parity-artifacts/mixed_repo/
cat mcp_tool_result.json | jq '.results[] | select(.id == "OSPS-GV-01.01")'
cat skill_final_message.md
cat diff_report.md
```

## What Tier 1 catches vs. what Tier 2 catches

| Regression | Tier 1 catches? | Tier 2 catches? |
|---|---|---|
| Harness silently disagrees with MCP tool on a control | YES (every PR) | YES (nightly if scheduled) |
| MCP tool changes its output format | YES (harness would break too) | YES |
| Coding-agent skill silently reclassifies WARN as PASS | NO | YES |
| Coding-agent skill's summary counts drift from tool's raw counts | NO | YES |
| An update to Claude Sonnet changes how the skill summarizes | NO | YES (over time) |
| Harness's LLM continuation loop produces different verdicts than before | YES (deterministic under MockLLMStep) | (partially -- if the change also affects live-LLM behavior) |

Tier 1 catches product-code regressions in the harness or MCP tool.
Tier 2 catches presentation-layer regressions (or model updates) in the coding-agent skill.

## Environment configuration (one-time, for maintainers)

Not part of the code; done in GitHub UI. Required before Tier 2 works:

1. Go to Settings -> Environments in the darnit repo.
2. Create Environment `parity-tier2`.
3. Add required reviewers (list of maintainers authorized to approve Tier 2 dispatches).
4. Add secret `ANTHROPIC_API_KEY` at the ENVIRONMENT level (not repo level).
5. Confirm: `Settings -> Secrets and variables -> Actions` does NOT contain `ANTHROPIC_API_KEY` at the repo level. If it does, it was misconfigured; delete the repo-level secret to enforce Environment-only scope (FR-007a).

## Running Tier 1 in CI

Tier 1 is included in the standard test workflow:

```yaml
# .github/workflows/test.yml (existing)
- name: Run tests
  run: uv run pytest tests/ -q
```

No new workflow needed for Tier 1; it's part of the default pytest run.

## Related follow-up work

- **Issue #368**: OpenAI SDK + other-provider parity checks (Tier 2 style, different provider).
- **Issue #369**: Scheduled Tier 2 cadence + governance-appropriate key sourcing (requires this feature to merge first).
