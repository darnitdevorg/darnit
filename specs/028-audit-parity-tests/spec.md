# Feature Specification: Two-Tier Audit Parity Tests

**Feature Branch**: `028-audit-parity-tests`

**Created**: 2026-08-09

**Status**: Draft

**Input**: User description: "Add a two-tier parity test suite that verifies the darnit audit's output is consistent across three consumers: direct MCP tool call, `darnit harness`, and the `/darnit-audit` coding-agent skill."

## Clarifications

### Session 2026-08-09

- Q: How does Tier 2 invoke the `/darnit-audit` coding-agent skill? -> A: Claude Agent SDK. Purpose-built for scripted agent invocations; provides deterministic turn/tool-call data; no interactive I/O. Added as a TEST-ONLY dependency (product packages unchanged). Follow-up issue #368 tracks equivalent OpenAI-SDK / other-provider parity checks so this feature isn't provider-locked in the long term; those are separate features scoped to their own SDKs.
- Q: What counts as "the skill's summary" for Tier 2 comparison? -> A: The skill's final assistant message. That is exactly what a human operator reads and believes; a diagnostic feature must compare user-facing output. Parsing is heuristic (Markdown scraping); a parse failure is a distinct failure class ("skill output unparseable") separate from a disagreement ("skill and tool disagree"). Structured-artifact alternatives (asking the skill to emit JSON alongside its Markdown) were rejected as intrusive -- a diagnostic feature should not modify the thing it diagnoses.
- Q: How often does Tier 2 run? -> A: Manual-only for the MVP (`workflow_dispatch`; no schedule). Rationale is governance, not cost: the darnit repo is under neutral governance, and the ANTHROPIC_API_KEY that would run this belongs to a specific company. Automated scheduled runs would charge that company's account for community activity. Manual dispatch preserves accountability -- an authorized maintainer explicitly consents to each run. Access control on the workflow / secret is a hard requirement (see FR-007a). Follow-up issue #369 captures the "add scheduled cadence once a governance-appropriate key-sourcing model exists" scope.
- Q: What Tier 1 calls as "the MCP tool" in its parity comparison. -> A: Direct Python function call: `from darnit_baseline.tools import audit_openssf_baseline; result = audit_openssf_baseline(local_path=..., level=..., output_format="json")`. The MCP protocol layer is a thin serialization wrapper around this function; the audit logic is what could regress. Direct call is faster, deterministic, and requires no server bootstrap. JSON-RPC serialization is out of scope for Tier 1; a separate narrow test can cover it if the need arises.
- Q: Fixture metadata file format. -> A: `parity.toml` at each fixture's root, TOML-parsed. Matches darnit's TOML-first convention (Constitution III). No code execution at load time (security -- rules out a Python-literal metadata file). Uses stdlib `tomllib`, no new dependency. Expected schema (fields documented in the plan phase): `[expected] counts.pass`, `counts.fail`, `counts.warn`, `counts.pending_llm`; `has_pending_llm: bool`; `category: "all_pass" | "all_fail" | "mixed" | "pending_llm"` for SC-008 corpus-inventory verification.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Maintainer catches a harness regression before merging (Priority: P1)

A maintainer opens a PR that changes the harness's `_collect_unanswered` logic. CI runs the Tier 1 parity test suite on the fixture corpus. The suite invokes the audit via both the direct MCP tool entry point AND via `darnit harness`, then diffs the per-control status. If any control differs beyond the documented allowed drift (harness resolves PENDING_LLM to WARN or an LLM-decided status), CI fails with a human-readable diff table showing exactly which control changed and how.

**Why this priority**: This is the mechanical safety net that fell out of the PR #365 review. The harness and the MCP tool share a `run_sieve_audit` code path today, but they consume the output differently (harness runs an LLM continuation loop; MCP tool leaves PENDING_LLM in place). A regression that makes the harness silently disagree with the MCP tool would undermine the whole "faithful to the audit" property; this tier catches it in seconds on every PR.

**Independent Test**: Add or modify the harness code, run `uv run pytest tests/darnit/parity/tier1/ -q`, and observe the pass/fail. The test suite requires no live API calls (uses `MockLLMStep`); it produces a diff table on failure that identifies exactly which control-level statuses differ.

**Acceptance Scenarios**:

1. **Given** the harness and MCP tool agree on every control's status for a fixture, **When** the Tier 1 test runs, **Then** it passes.
2. **Given** a change to the harness makes it report FAIL for a control the MCP tool reports PASS, **When** the Tier 1 test runs, **Then** it fails with an assertion message that names the control and both statuses.
3. **Given** the MCP tool leaves a control PENDING_LLM and the harness resolves it to WARN via the LLM continuation loop, **When** the Tier 1 test runs, **Then** it PASSES (this is the sole documented allowed drift).
4. **Given** a fixture is added to the corpus but no test task is added, **When** the Tier 1 test runs, **Then** the new fixture is automatically covered (the test suite iterates the fixture directory).

---

### User Story 2 - Maintainer discovers coding-agent skill drift (Priority: P2)

A nightly (or weekly) CI job runs the Tier 2 parity check. For each fixture in the corpus, it captures the raw MCP tool JSON output, then invokes the `/darnit-audit` coding-agent skill on the same fixture via the Claude Agent SDK. It parses the skill's Markdown summary for PASS/FAIL/WARN counts and per-control claims, and diffs them against the raw tool output. If the skill's summary reclassifies any control's status differently than the raw output, CI captures both artifacts (the skill's Markdown + the tool's JSON) for human inspection.

**Why this priority**: The reason issue #366 exists. The `/darnit-audit` skill was observed reclassifying WARN -> PASS in its summary; a maintainer would like to know when this happens without discovering it during manual testing. Priority 2 rather than 1 because the check requires a live API call (rate limits, cost), so it can't run on every PR.

**Independent Test**: Manually trigger the Tier 2 job (or wait for the scheduled run). Verify (a) it exits 0 when the skill's summary agrees with the raw tool output on every control's status, (b) it exits non-zero when they disagree, and (c) the failure artifact contains both the skill Markdown and the tool JSON side-by-side.

**Acceptance Scenarios**:

1. **Given** the skill's summary reports the same PASS/FAIL/WARN counts as the raw MCP tool for every fixture, **When** the Tier 2 job runs, **Then** it exits successfully.
2. **Given** the skill silently reclassifies a WARN control as PASS in its summary, **When** the Tier 2 job runs, **Then** it fails with a per-control diff and the raw artifacts attached.
3. **Given** a control's Check step had `dispositive` authority evidence and the skill's summary matches the tool's status for it, **When** the Tier 2 job runs, **Then** that control passes the check.
4. **Given** a control's Check step had `suggestive` authority evidence and the skill's summary changed its status, **When** the Tier 2 job runs, **Then** the check STILL fails -- the skill has no license to reinterpret verdicts regardless of authority level. Any status change from the skill layer relative to the raw tool output is a hard failure.

---

### User Story 3 - Fixture author adds coverage for a new audit corner (Priority: P3)

A maintainer notices that no fixture exercises the case where every control PASSes cleanly. They add a new fixture repo under `tests/darnit/parity/fixtures/`, populate it with the file structure that satisfies all Level-1 controls, and run the parity tests. Both tiers automatically discover the new fixture and run against it. No test-task edit is required.

**Why this priority**: Auto-discovery of fixtures is convenience, not a load-bearing property. The parity suite works with a single fixture; more fixtures produce broader coverage. Priority 3 because the discovery mechanism is nice-to-have, not required.

**Independent Test**: Add a directory `tests/darnit/parity/fixtures/all_pass_repo/` containing the requisite files; run `uv run pytest tests/darnit/parity/ -q` (Tier 1); verify the new fixture's tests are collected and pass.

**Acceptance Scenarios**:

1. **Given** the fixtures directory contains N fixtures, **When** the Tier 1 suite runs, **Then** each fixture is exercised at least once (verified by test collection count).
2. **Given** a new fixture is added by placing a directory under the fixtures root, **When** pytest is next invoked, **Then** the new fixture is automatically included without any test file changes.

---

### Edge Cases

- **Fixture with no controls loaded** (empty `.baseline.toml`): Tier 1 should not silently pass; the harness reports SETUP_ERROR (exit 2) for this case, and the MCP tool reports zero controls. The suite treats "both reported zero controls" as a valid parity outcome for a fixture explicitly labeled empty, and a mismatch (one path errors, the other returns zero) as a failure.
- **Fixture that produces PENDING_LLM in the MCP tool path**: Tier 1 records the PENDING_LLM verdict from the MCP tool and the resolved verdict (WARN or a specific LLM-decided status) from the harness. This ONE class of drift is explicitly allowed and documented; no other drift is.
- **Skill returns no Markdown summary** (e.g., skill invocation times out): Tier 2 reports a distinct failure class ("skill did not produce a summary") separate from "skill and tool disagree." The failure artifact still captures whatever the skill produced (if anything).
- **Skill's Markdown parseable but ambiguous** (skill reports "56/66 pass" but doesn't enumerate per-control): Tier 2 falls back to a summary-count comparison ("skill's PASS count vs tool's PASS count"). If those differ, fail; if they match, warn that per-control comparison was not possible for this run.
- **ANTHROPIC_API_KEY absent for Tier 2**: fail with a clear setup error ("Tier 2 requires ANTHROPIC_API_KEY; skipping or failing per configuration"). Never silently pass.
- **New allowed drift discovered**: any change to the "PENDING_LLM -> resolved" allowance must be a deliberate spec change. Adding a second allowed drift class requires updating this spec and the test's allowed-drift table.
- **Fixture removal**: if a fixture is deleted, the auto-discovery mechanism produces fewer tests but no failure. A test collection count check catches accidental fixture deletion during unrelated refactors (informational only).
- **Tier 2 rate limit hit mid-run**: capture the partial results; fail with a clear "rate limited" message; do NOT retry automatically. A subsequent manual dispatch picks up from a clean state.
- **Unauthorized dispatch attempt**: a GitHub user without the reviewer role tries to trigger the Tier 2 workflow. GitHub Actions' Environment gate blocks the run; the workflow never executes; no API budget is consumed. This is by design (FR-007a); no additional darnit-side logic is required beyond configuring the Environment correctly.
- **Missing reviewer approval**: a dispatched run waits at the approval gate indefinitely. Approval timeout is a GitHub configuration setting (spec does not fix it; a plan-phase choice).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a Tier 1 automated test that, for every fixture in the corpus, invokes the audit via BOTH the direct MCP tool entry point (Python function call: `audit_openssf_baseline(local_path=..., level=..., output_format="json")`) AND `darnit harness` in-process (no CLI subprocess, no MCP server bootstrap), and compares the per-control status output of both paths.
- **FR-002**: Tier 1 MUST treat exactly one class of drift as allowed: a control that the direct MCP tool reports as PENDING_LLM is allowed to be reported as any non-PENDING_LLM status by the harness (WARN, PASS, FAIL, N/A, or ERROR, depending on what the LLM continuation loop resolved it to). Every other per-control status difference is a hard failure.
- **FR-003**: Tier 1 MUST NOT require a live LLM API call. The harness's LLM step MUST be pluggable and the test MUST inject a `MockLLMStep` or equivalent so the whole Tier 1 suite runs offline.
- **FR-004**: On Tier 1 failure, the assertion message MUST include a human-readable table listing every diverging control with columns for control_id, MCP tool status, and harness status. The table MUST be readable in a terminal (fixed-width, no ANSI escapes required).
- **FR-005**: Tier 1 MUST run in under 60 seconds for the full fixture corpus (defined below). Individual fixture tests SHOULD complete in under 10 seconds each.
- **FR-006**: The system MUST provide a Tier 2 automated check that, for every fixture in the corpus, (a) invokes the direct MCP tool and captures its JSON output, (b) invokes the `/darnit-audit` coding-agent skill via the Claude Agent SDK on the same fixture and captures the SKILL'S FINAL ASSISTANT MESSAGE (the artifact a human user actually reads), (c) diffs the skill's per-control claims and PASS/FAIL/WARN counts against the tool's raw output. The Claude Agent SDK is a TEST-ONLY dependency; product packages MUST NOT gain a runtime dep. Parallel parity-check features for other provider SDKs (OpenAI, etc.) are out of scope and tracked as separate follow-up issues.
- **FR-006a**: Tier 2 MUST NOT modify the `/darnit-audit` skill (its prompt, its tool grants, its output format) as a precondition of the test. The skill is what it is; the parity check parses whatever the skill produces. If the skill's final-message format changes such that the parser can no longer extract per-control claims, Tier 2's failure surfaces as "skill output unparseable" -- a distinct failure class from "skill and tool disagree" -- so a maintainer can distinguish a broken parser from a real drift.
- **FR-007**: Tier 2 MUST run only under manual dispatch (`workflow_dispatch` in GitHub Actions) for the MVP. No `schedule:` trigger. Rationale is governance: the darnit repo is under neutral governance, and the ANTHROPIC_API_KEY that runs this belongs to a specific company that MUST NOT be charged for unattended community-triggered activity. A follow-up issue captures the "add scheduled cadence" scope once a governance-appropriate key-sourcing model exists (options include: dedicated community-owned API key with usage cap, per-maintainer BYO-key model, GitHub-Environment-approval-gated runs with a shared key).
- **FR-007a**: Access control on Tier 2 workflow invocation MUST prevent an unauthorized party from triggering a run that charges the API-key-owner's account. Concretely: (a) the workflow lives in a GitHub Actions Environment configured with a required-reviewer list (only listed reviewers can approve a dispatch); (b) the `ANTHROPIC_API_KEY` secret lives in that Environment, not at the repository level, so it is not exposed to any workflow outside the gated environment; (c) the workflow definition includes a preflight check that logs the actor and the SHA before spending any API budget, so a post-hoc audit can attribute cost. A misconfigured deployment where the API key is exposed to workflows outside the reviewer gate is treated as a severity-1 governance bug.
- **FR-007b**: Tier 2 MUST NOT accept an operator-provided API key as a workflow input for the MVP. Reason: an input-key model bypasses the Environment/reviewer gate and re-opens the "arbitrary community member spends someone else's money" hole in a subtler form. A future BYO-key model may reintroduce this; the follow-up issue tracks that decision.
- **FR-008**: Tier 2 MUST fail on any per-control status difference between the skill's summary and the raw tool output, regardless of the control's authority level. The skill has no license to reinterpret verdicts.
- **FR-009**: On Tier 2 failure, the CI job MUST attach both the skill's raw Markdown output AND the raw MCP tool JSON for the failing fixture as an inspectable artifact, so a maintainer can review the drift without re-running the check.
- **FR-010**: When ANTHROPIC_API_KEY is absent, Tier 2 MUST fail fast with a clear setup error. Silent-skip is forbidden -- an operator MUST know Tier 2 did not run.
- **FR-011**: The fixture corpus MUST include at least four fixtures covering distinct audit-output shapes: (a) all-PASS, (b) all-FAIL, (c) mixed PASS/FAIL/WARN, (d) at least one control that produces PENDING_LLM under the MCP tool path. The existing `minimal_llm_repo` fixture from feature 026 counts toward (d).
- **FR-012**: Fixtures MUST be auto-discovered: any directory under a documented fixtures root is treated as a fixture without requiring a corresponding test file edit. Adding or removing a fixture only requires changing files in that directory.
- **FR-012a**: Each fixture MAY carry a `parity.toml` file at its root declaring the expected shape of its output. TOML-parsed via stdlib `tomllib`; no code execution. Schema (documented in plan phase) at minimum includes `[expected] counts.pass`, `counts.fail`, `counts.warn`, `counts.pending_llm`, and `category` (one of `"all_pass"`, `"all_fail"`, `"mixed"`, `"pending_llm"`). Fixtures without a `parity.toml` are treated as "shape unspecified" -- parity across paths is still asserted, but corpus-inventory (SC-008) checks skip them.
- **FR-013**: Both tiers MUST produce a report that includes the number of controls checked, the number that agreed across paths, and the number that diverged (with drift classification for Tier 1). The report is emitted regardless of pass/fail so counting evidence is captured even on green runs.
- **FR-014**: The parity test suite MUST NOT modify the darnit product code as a side effect. The tests are pure consumers of the existing MCP tool, harness, and skill surfaces. Any test-side helper that requires a product change (e.g., an injection seam that doesn't exist) is spec-scope creep and MUST be flagged as a follow-up rather than silently added.
- **FR-015**: Tier 1 test failures MUST be reproducible from a git commit hash + fixture directory alone. No hidden global state, no time-of-day sensitivity, no ordering dependency across fixtures. Deterministic execution is a hard requirement.
- **FR-016**: The parity test suite MUST close issue #366 when merged. Its purpose is diagnosis (finding drift) not remediation (fixing the skill). Any drift Tier 2 discovers is filed as a separate issue.

### Key Entities

- **Fixture**: A directory containing everything needed to run an audit -- a `.baseline.toml`, a `.project/project.yaml` (optional), and whatever repo files the controls reference. Each fixture has a stable identifier (its directory name) and an optional `parity.toml` metadata file at its root declaring the expected shape of its output (TOML-parsed; schema per FR-012a). Fixtures without `parity.toml` still participate in inter-path parity assertions but are skipped for corpus-inventory checks.
- **AuditResult**: The unified representation of one audit's output. Contains the list of controls with their statuses, authority levels, and any pending-LLM markers. Both the MCP tool path and the harness path produce this shape; the parity test compares them.
- **DriftEntry**: One row of the diff table produced on Tier 1 failure. Fields: fixture identifier, control_id, path-A status, path-B status, whether the drift is in the documented allowed set.
- **SkillReport**: The Tier 2-parsed view of the coding-agent skill's Markdown output. Contains the counts (PASS/FAIL/WARN) the skill reported and per-control claims (extracted from the Markdown structure). Not part of the darnit product; a test-only intermediate.
- **ParityReport**: The end-of-run summary emitted by either tier. Contains per-fixture pass/fail, drift counts, and (for Tier 2 failure) the raw artifact paths.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Tier 1 catches 100% of harness-vs-tool per-control divergences in the fixture corpus other than the documented PENDING_LLM-resolution drift. Verified by an adversarial test that deliberately introduces a divergence and asserts Tier 1 fails.
- **SC-002**: The full Tier 1 suite runs in under 60 seconds on a standard developer laptop. Verified by a timing assertion in CI.
- **SC-003**: Every diverging control in a Tier 1 failure has a corresponding row in the failure message. Verified by an adversarial test that seeds N divergences and asserts the failure message contains N rows.
- **SC-004**: Tier 2 catches 100% of skill-vs-tool per-control status divergences in the fixture corpus, regardless of authority level. Verified by an adversarial fixture where the skill (via a mocked SDK response) reclassifies a WARN control as PASS; Tier 2 fails.
- **SC-005**: Tier 2 artifacts on failure include BOTH the skill's raw Markdown AND the tool's JSON for every failing fixture. Verified by inspecting a scripted failure run's artifact directory.
- **SC-005a**: The `ANTHROPIC_API_KEY` secret used by Tier 2 MUST NOT be reachable by any GitHub Actions workflow other than the gated Tier 2 workflow. Verified by grepping `.github/workflows/` for other `secrets.ANTHROPIC_API_KEY` references (result MUST be empty except in the Tier 2 workflow) AND by confirming the secret's storage location is a GitHub Environment (not a repo-level secret) whose only entry point is the reviewer-gated deployment.
- **SC-006**: The parity test suite does not add ANY runtime dependencies to the darnit product packages. Verified by comparing the pre- and post-feature `pyproject.toml` dependency lists in `packages/darnit/` and `packages/darnit-baseline/`.
- **SC-007**: A new fixture added by creating a directory under the fixtures root is exercised by BOTH tiers on the next run, with no test file changes. Verified by adding a fixture in the test suite itself and asserting collection count increases by one.
- **SC-008**: The fixture corpus produces at least one control in each of the four categories: PASS-only, FAIL-only, mixed, and PENDING_LLM. Verified by a corpus-inventory test that counts the categories represented.
- **SC-009**: An issue #366 status check (via `gh issue view 366`) MUST show "Closed" within one working day of this feature's PR merging. Manual verification.

## Assumptions

- The parity tests live under `tests/darnit/parity/` as a new pytest package. Tier 1 tests live in `tests/darnit/parity/tier1/`; Tier 2 tests + scaffolding live in `tests/darnit/parity/tier2/`. Fixture directories live under `tests/darnit/parity/fixtures/`.
- The Tier 2 job is a GitHub Actions workflow with a `schedule:` trigger and appropriate secret injection for `ANTHROPIC_API_KEY`. The exact YAML shape is a plan-phase concern.
- The `/darnit-audit` skill invocation from Tier 2 goes through the Claude Agent SDK (as opposed to Claude Code CLI). The SDK provides deterministic invocation: no interactive turns, no user prompting, prompts and tool grants pre-configured. The SDK is a runtime dependency of the TEST suite only, never the product.
- Parsing the skill's Markdown summary is a lossy operation; the skill's output format is not a stable contract. The test suite's Markdown parser lives in `tests/darnit/parity/tier2/skill_markdown_parser.py` and produces a best-effort extraction. If the skill changes its output format such that the parser breaks, Tier 2's failure mode is "could not parse skill output" -- distinct from "skill and tool disagree."
- Feature 026 (`darnit harness`) is a hard dependency; the harness code must exist before Tier 1 can be written. Feature 027 (interactive resolvers) is NOT a dependency -- the parity tests do not exercise interactive answer collection.
- The Claude Agent SDK's dependency, install path, and version pinning are plan-phase decisions. The spec assumes a reputable, published SDK exists; if it does not, Tier 2's implementation approach may change (e.g., invoke `claude` CLI as a subprocess).
- Fixture repos are lightweight; they contain only the files necessary for the controls they exercise. No large binary blobs. Fixtures should git-clone in under 5 seconds and audit in under 10 seconds each.
- Tier 1's "under 60 seconds" budget accommodates a fixture corpus of 4-6 fixtures. If the corpus grows past 20 fixtures, the budget may need revisiting; that is a spec change.
- The `/darnit-audit` skill's own version is captured in Tier 2 artifacts (from the SDK's provenance response, if available; otherwise from the invocation config) so a maintainer can correlate a drift with a specific skill version.
- The tests are diagnostic. They do NOT propose fixes for any drift they discover. A Tier 2 failure filed as an issue triggers a separate feature to decide the fix.
