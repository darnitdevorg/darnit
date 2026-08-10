# Phase 0 Research: Two-Tier Audit Parity Tests

**Feature**: 028-audit-parity-tests | **Date**: 2026-08-09

The five load-bearing decisions were resolved in `/speckit-clarify` (recorded in `spec.md`'s Clarifications block). This file covers the residual technical decisions Phase 1 needs to sit on.

## R1. Fixture layout + auto-discovery mechanism

**Decision**: A fixture is any directory directly under `tests/darnit/parity/fixtures/` that contains a `.baseline.toml`. Auto-discovery uses pytest parametrization via a `conftest.py` in `tests/darnit/parity/tier1/`:

```python
# conftest.py sketch
def pytest_generate_tests(metafunc):
    if "fixture_dir" in metafunc.fixturenames:
        root = Path(__file__).parent.parent / "fixtures"
        fixtures = [d for d in sorted(root.iterdir())
                    if d.is_dir() and (d / ".baseline.toml").exists()]
        metafunc.parametrize("fixture_dir", fixtures, ids=[f.name for f in fixtures])
```

`test_mcp_vs_harness.py` accepts `fixture_dir: Path` and gets one test invocation per fixture, with the fixture's directory name in the test id. Adding a new fixture is a pure directory addition; no test file change.

**Rationale**: pytest's `pytest_generate_tests` is the standard mechanism for this shape. Test IDs match directory names, so a failure in `test_mcp_vs_harness[mixed_repo]` is self-documenting.

**Alternatives considered**:

- Static test-function-per-fixture (one `def test_mixed_repo():`): rejected -- adding a fixture requires editing test code, violating FR-012.
- Runtime discovery via `pytest.mark.parametrize` with a module-level list computed at import time: works but harder to override during adversarial tests (see R5).

## R2. Sole allowed drift = PENDING_LLM to any non-PENDING_LLM

**Decision**: The comparator (`tier1/comparator.py`) implements this rule as a table:

```
Direct-MCP status | Harness status | Verdict
PASS              | PASS           | ok
FAIL              | FAIL           | ok
WARN              | WARN           | ok
N/A               | N/A            | ok
ERROR             | ERROR          | ok
PENDING_LLM       | *              | allowed_drift
*                 | PENDING_LLM    | FAIL (harness must resolve; not the other way)
X                 | Y (X != Y)     | FAIL (any other mismatch)
```

A separate helper on `DriftEntry` (`is_allowed_drift`) implements this table. The failure message includes both an "unallowed drifts" table (the hard failures) AND an "allowed drifts" note (for evidence, does not cause failure). This mirrors feature 026's habit of surfacing evidence even on green runs.

**Rationale**: Explicit rule table beats scattered conditionals. Easy to add rows later if a new class of drift becomes legitimate.

**Alternatives considered**:

- Symmetric wildcard (`PENDING_LLM <-> *` both ways): rejected -- if the harness produced PENDING_LLM while the MCP tool resolved it, that's a real bug (the harness has an LLM continuation loop; the MCP tool doesn't).
- Configurable per-fixture drift allowances via `parity.toml`: rejected as scope creep. If a specific fixture legitimately needs a different drift class, that's a spec change that adds a new allowed row to the table.

## R3. Harness invocation without live API

**Decision**: Tier 1 invokes the harness via direct instantiation:

```python
from darnit.core.llm_step import MockLLMStep, LLMJudgment
from darnit.harness.driver import HarnessRun

async def run_harness_on_fixture(fixture_dir: Path) -> HarnessReport:
    mock = MockLLMStep(LLMJudgment(
        outcome="inconclusive",  # never let the LLM "resolve" beyond WARN
        confidence=0.0,
        reasoning="Tier 1 mock -- no LLM decision",
    ))
    run = HarnessRun(
        local_path=str(fixture_dir),
        level=3,
        llm_step=mock,
        per_call_timeout_s=5,
        total_run_timeout_s=30,
    )
    return await run.run()
```

The mock returns `inconclusive` so any PENDING_LLM control resolves to WARN (per the harness's `verify_with_llm_response` fallthrough). That's exactly the allowed-drift class in R2.

**Rationale**: MockLLMStep is feature 026's test seam; Tier 1 uses it exactly as feature 026's own tests do. Deterministic + fast + offline.

**Alternatives considered**:

- Configure the mock per-fixture to return specific outcomes: rejected as scope creep. Tier 1 verifies the paths agree on IDENTICAL inputs; simulating different LLM verdicts is a different test surface (Tier 2's territory).

## R4. MCP tool invocation shape

**Decision**: Tier 1 calls the MCP tool as a plain Python function:

```python
from darnit_baseline.tools import audit_openssf_baseline
import json

def run_mcp_tool_on_fixture(fixture_dir: Path) -> AuditResult:
    raw = audit_openssf_baseline(
        local_path=str(fixture_dir),
        level=3,
        output_format="json",
        auto_init_config=False,      # fixtures ship their own .project/
        attest=False,
        prefer_upstream=False,
    )
    return AuditResult.from_mcp_json(json.loads(raw))
```

`AuditResult.from_mcp_json` and `AuditResult.from_harness_report` are two small factory functions on the same dataclass -- they normalize both output shapes into a common form the comparator operates on.

**Rationale**: `audit_openssf_baseline` is the actual MCP tool implementation. The MCP protocol wrapper (`darnit.server.factory`) just JSON-serializes the return value; there's no other transformation.

**Alternatives considered**:

- Spawn a subprocess `darnit serve` and call via JSON-RPC: rejected in clarify Q4 -- too slow, no diagnostic benefit for what could regress in the audit layer.
- Call `run_sieve_audit` directly (the shared kernel of both paths): rejected -- would be a "test tests itself" tautology since both the MCP tool and the harness are wrappers around `run_sieve_audit`. We want to catch bugs in the WRAPPERS.

## R5. Adversarial test seeding (SC-001, SC-003)

**Decision**: The adversarial tests use a "fake MCP tool result" injection point, not by modifying real audit code. Concretely:

```python
def test_comparator_catches_pass_to_fail_divergence():
    """SC-001: Deliberately construct a diverging pair and assert the
    comparator reports a hard failure."""
    mcp_result = AuditResult(controls=[
        Control(id="X", status="PASS", authority="dispositive"),
    ])
    harness_result = AuditResult(controls=[
        Control(id="X", status="FAIL", authority="dispositive"),
    ])
    drifts = compare(mcp_result, harness_result)
    disallowed = [d for d in drifts if not d.is_allowed_drift]
    assert len(disallowed) == 1
    assert disallowed[0].control_id == "X"

def test_comparator_failure_message_lists_all_drifts():
    """SC-003: N seeded divergences produce N table rows."""
    ...
```

The adversarial tests exercise `comparator.compare()` and `format_drift_table()` directly with hand-constructed inputs. Feature 026 and 027 code stays untouched.

**Rationale**: Adversarial tests should test the COMPARATOR, not simulate a broken darnit. Simulating a broken darnit would require monkey-patching product code, which is more fragile and adds no signal about whether the comparator itself catches real drift.

**Alternatives considered**:

- Property-based tests (hypothesis) generating random `AuditResult` pairs: could add later as a follow-up; overkill for the MVP where the drift classes are enumerable.
- Fault-injection at the harness layer: rejected -- reaches into product internals; a fault-injection API is bigger scope than the whole feature.

## R6. Skill Markdown parsing (Tier 2)

**Decision**: `skill_markdown_parser.py` uses regex-based extraction with an explicit best-effort contract:

1. Match the summary counts pattern: `\d+/\d+ pass`, `\d+/\d+ fail`, etc. (skill's current format from PR #365 review notes).
2. Match per-control claims: heading-shaped patterns like `**OSPS-XX-01.01**: PASS` and enumerated status references.
3. If either extraction fails, return a `SkillReport` with `parseable = False` and the raw Markdown attached; Tier 2 fails with a "skill output unparseable" verdict.

The parser lives in `tests/darnit/parity/tier2/skill_markdown_parser.py`. Its tests use golden files -- captured skill outputs from earlier runs.

**Rationale**: The skill's output format is not a stable contract; we cannot depend on it. A best-effort parser with a distinguishable "unparseable" failure class is the honest approach.

**Alternatives considered**:

- LLM-based summarization of the skill's output: rejected -- introduces another API call, another model whose output we'd need to trust, and defeats the point of a diagnostic test.
- Ask the skill to emit structured JSON: rejected in clarify Q2 (spec's FR-006a) -- a diagnostic feature must not modify the thing it diagnoses.
- HTML/Markdown AST parsing (mistune, markdown-it-py): considered; adds a dep. If regex parsing turns out to be too brittle, we can swap the parser implementation later without changing the SkillReport shape.

## R7. Claude Agent SDK invocation shape

**Decision**: `claude_agent_sdk_client.py` invokes the SDK with:

- Pre-configured system prompt matching what Claude Code loads for the `/darnit-audit` skill (captured verbatim from `.claude/skills/darnit-audit/` if present, or from a snapshot committed to `tests/darnit/parity/tier2/skill_prompt_snapshot.md`).
- Tool allow-list: only the darnit MCP tools this skill invokes (`audit_openssf_baseline`, `list_available_checks`, etc.). No general-purpose tools; no filesystem write.
- Model pinned to whatever the current default is (`anthropic:claude-sonnet-5` per feature 025/026 default). Configurable via env var so we can rerun a check against a specific model in an investigation.
- Deterministic mode where the SDK offers it (temperature=0 or lowest available).
- Turn cap: bounded by an explicit `max_turns` (default 20) so a runaway skill can't burn budget.

**Rationale**: The whole point of the SDK vs subprocess is scripted, deterministic invocation. Explicit prompt + tool grants + turn cap + temperature is what makes runs reproducible.

**Alternatives considered**:

- Freshly-authored prompt (not the skill's real one): rejected -- the test would measure a hypothetical, not the actual skill users experience.
- No turn cap: rejected -- a bug in the skill's prompting could cost real money.

## R8. Tier 2 CI workflow shape (governance-critical)

**Decision**: `.github/workflows/parity-tier2.yml`:

```yaml
on:
  workflow_dispatch:
    inputs:
      fixture_glob:
        description: "Fixture directory glob (default: all)"
        default: "*"
        required: false

jobs:
  tier2:
    runs-on: ubuntu-latest
    environment: parity-tier2       # <-- gated Environment, required-reviewer list
    permissions:
      contents: read
    steps:
      - checkout, setup-python, uv sync --dev
      - preflight: log actor + SHA to job summary (FR-007a audit trail)
      - run: uv run python tests/darnit/parity/tier2/run.py --fixture-glob "${{ inputs.fixture_glob }}"
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      - upload artifacts: parity-artifacts/
```

Key config beyond the YAML:

- The `parity-tier2` Environment MUST be configured in GitHub UI with (a) required-reviewer list, (b) `ANTHROPIC_API_KEY` as an Environment secret (NOT a repo secret).
- No other workflow references `secrets.ANTHROPIC_API_KEY` (SC-005a verifiable via grep).
- `permissions: contents: read` only; no write scope so a compromised workflow can't push commits.

**Rationale**: This is exactly the GitHub-Actions Environment pattern for high-cost or high-risk jobs. Blocks unauthorized dispatch at the platform layer, not in code.

**Alternatives considered**:

- Approve every workflow_dispatch invocation via a separate approval step: same effect as Environment reviewer but adds YAML complexity.
- Move the API key to a self-hosted runner: overkill for the current threat model.

## R9. Fixture authoring cost

**Decision**: The MVP fixture corpus reuses feature 026's `minimal_llm_repo` (PENDING_LLM category) and adds three new synthetic ones:

- `all_pass_repo/`: satisfies every Level-1 control the fixture wants to include. Explicit `.project/project.yaml` with all required context values. Small file set (LICENSE, README, SECURITY.md, minimal `.github/`).
- `all_fail_repo/`: bare repo; almost nothing. `.baseline.toml` present but repo files intentionally absent. Every control at every level fails.
- `mixed_repo/`: some controls satisfied, some deliberately not. Explicit `.project/project.yaml` for the "yes" side. About 6 controls PASS, 6 FAIL, 3 WARN.

Each fixture ships with a `parity.toml` declaring its category + expected counts (from an initial run of the tool during fixture authoring).

**Rationale**: Four fixtures is enough to cover the four SC-008 categories. Smaller-is-better for CI time. Additional fixtures land in follow-up PRs when specific corner cases surface.

**Alternatives considered**:

- Copy real repositories (curl, kubernetes, etc.) as fixtures: rejected -- churn, license concerns, and audit results depend on live GitHub API responses that a fixture can't provide deterministically.
- Generate fixtures programmatically from a fixture-authoring DSL: rejected as premature abstraction; four hand-written fixtures is manageable.

## R10. Reporting on green runs (FR-013)

**Decision**: Even on Tier 1 green runs, the comparator emits a summary line per fixture:

```
[tier1] all_pass_repo:     3 controls compared, 3 agreed, 0 diverged
[tier1] pending_llm_repo:  6 controls compared, 5 agreed, 1 allowed-drift (PENDING_LLM->WARN)
```

Emitted via `pytest.warns`-like sidechannel: a per-fixture line in the pytest report. Not a warning (doesn't imply anything is wrong); an informational report that CI can grep for evidence of a green run's shape.

Tier 2's report shape is similar, written to the job summary (`GITHUB_STEP_SUMMARY`).

**Rationale**: FR-013 hard rule -- report on green runs too. This gives the maintainer a check that "the test ran and looked at N controls" rather than the tests being silently no-op.

**Alternatives considered**:

- Emit only on failure: rejected -- FR-013 rules that out, and rightly so; a test suite that says nothing on green is one that could silently disable itself.

## Summary of Phase 0 outcome

- Every technical unknown for Phase 1 design has a concrete decision above.
- No new production dependencies. The Claude Agent SDK is test-only, added to a workspace dev group.
- SC-006 hard constraint mechanically holds: no `packages/darnit/pyproject.toml` or `packages/darnit-baseline/pyproject.toml` change is planned.
- Governance property (FR-007a + SC-005a) is enforced at the GitHub Environment layer; the plan-phase workflow YAML has the right shape.
- Adversarial-test strategy exercises the comparator directly with hand-built inputs; no product-code fault injection required.
- Skill Markdown parser is best-effort with an "unparseable" failure class distinct from "disagreement."
