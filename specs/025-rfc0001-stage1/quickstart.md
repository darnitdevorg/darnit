# Quickstart: RFC-0001 Stage 1

**Feature**: 025-rfc0001-stage1
**Audience**: maintainers implementing or reviewing Stage 1

Stage 1 is a spec/PR series (4 slices). This quickstart covers running and verifying each slice + the whole gate.

---

## Prereqs

- `uv sync --dev` succeeds against the workspace (includes new dep `pydantic-ai-slim[anthropic]`).
- Feature 024's `tests/darnit/cli/test_cmd_run_e2e.py` passes on `main`. Stage 1 uses this suite as its regression baseline.

## Run Slice A tests (authority + Check-phase rule)

```bash
uv run pytest tests/darnit/core/test_authority.py tests/darnit/sieve/test_strategy_runner.py tests/darnit/sieve/test_authority_terminates.py -v
```

Expected: all pass. SC-001 test `test_llm_only_control_never_passes` asserts that a strategy list with only a suggestive LLM step returns inconclusive, not PASS. SC-008 test `test_prompt_injection_repo_does_not_produce_false_pass` asserts the same property against the adversarial-input fixture.

## Run Slice B tests (ActionPlan protocol)

```bash
uv run pytest tests/darnit/core/test_action_plan.py -v
uv run pytest tests/darnit/cli/test_cmd_run_e2e.py -v  # feature 024 baseline; MUST stay green
```

Expected: all pass. SC-002 test `test_action_plan_equals_cmd_run` asserts direct-Python protocol driving produces the same final state as `darnit run` on the same fixture.

## Run Slice C tests (MCP surface)

```bash
uv run pytest tests/darnit/server/test_harness_loop_mcp.py -v
```

Expected: all pass. SC-003 test `test_mcp_equals_direct_equals_cli` asserts three-way equality on the same fixture: direct-Python protocol driving == MCP driving == `darnit run`.

## Run Slice D tests (SECURITY.md reference control + acceptance gate)

```bash
uv run pytest tests/darnit_baseline/controls/test_security_md_reference.py tests/darnit_baseline/attestation/test_authority_field.py -v
```

Expected: all pass. SC-004 asserts the full Check -> Collect -> Remediate -> re-Check flow via both CLI and MCP; SC-007 asserts every attestation result carries `authority`.

## Full stage validation

```bash
uv run pytest tests/ -v --deselect tests/darnit/context/test_dot_project_upstream.py::TestUpstreamSpecSync::test_upstream_spec_unchanged
uv run ruff check .
uv run python scripts/validate_sync.py --verbose
```

Expected: all pass; the deselected upstream-hash test is a pre-existing drift unrelated to Stage 1.

---

## Verify the safety property actually pins (US1 / SC-001 perturbation)

Deliberate perturbation:

```bash
# 1. Perturb: make the runner treat suggestive as conclusive
python3 -c "
import pathlib
p = pathlib.Path('packages/darnit/src/darnit/sieve/orchestrator.py')
s = p.read_text()
# Locate and comment out the authority check that blocks suggestive from concluding
new = s.replace('if authority == \"suggestive\":', 'if False:  # authority == \"suggestive\":')
assert new != s
p.write_text(new)
"

# 2. Run SC-001 test; expect failure naming authority
uv run pytest tests/darnit/sieve/test_authority_terminates.py -v -k llm_only

# 3. Revert
git checkout -- packages/darnit/src/darnit/sieve/orchestrator.py

# 4. Retest; expect green
uv run pytest tests/darnit/sieve/test_authority_terminates.py -v -k llm_only
```

If step 2 does NOT fail with a message naming authority, the SC-001 pin is not actually pinning; fix the test before merging.

## Verify the MCP wire format round-trips

```bash
uv run python -c "
from darnit.core.action_plan import HarnessState
s = HarnessState(local_path='/tmp')
dumped = s.model_dump_json()
restored = HarnessState.model_validate_json(dumped)
assert s == restored, 'HarnessState round-trip broken'
print('OK')
"
```

Expected: `OK`. If the assertion fires, add the offending field to the compat suite.

---

## Contract-change procedure

Both `action-plan-protocol.md` and `mcp-tools.md` pin external contracts. Any change to those APIs during Stage 1 (or later) MUST:

1. Update the contract file in the same PR.
2. Update the corresponding test.
3. Note `Contract change:` in the PR description.

Feature 024's `contracts/cmd_run-output.md` uses the same procedure; reviewers reject PRs whose test edits are not accompanied by matching contract edits.

---

## Troubleshooting

**`ImportError: pydantic_ai`** — you didn't `uv sync --dev` after this stage lands. Pydantic AI is a REQUIRED runtime dep now; installing darnit installs it.

**Feature 024 tests fail** — a Slice B change broke the observable output. Either revert the change or update the contract per feature 024's procedure. Do NOT ignore.

**MCP round-trip test fails on state equality** — likely a field on `HarnessState` that isn't JSON-serializable (e.g., a `Path` slipped in). Convert to string at the model boundary.

**`AuthorityViolation` at control load** — a TOML strategy step declared an impossible authority (usually a python handler claiming `asserted`). Fix the TOML or fix the handler's authority.

**SC-008 test flake** — should never flake; the LLM invocation is stubbed. If it does, check whether the mock is being applied correctly (should be via a pytest fixture that patches `LLMStep`).
