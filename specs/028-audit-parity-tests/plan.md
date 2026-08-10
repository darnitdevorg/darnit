# Implementation Plan: Two-Tier Audit Parity Tests

**Branch**: `028-audit-parity-tests` | **Date**: 2026-08-09 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/028-audit-parity-tests/spec.md` (with 5 clarifications from `/speckit-clarify` on 2026-08-09: Claude Agent SDK for Tier 2 invocation; skill's final assistant message as the parsed artifact; manual-dispatch only with Environment-gated key + reviewer approval; direct Python function call for Tier 1; `parity.toml` per fixture).

## Summary

Adds a two-tier diagnostic test suite that verifies the darnit audit's per-control output is consistent across the three consumers users care about:

- **Direct MCP tool** call (`darnit_baseline.tools.audit_openssf_baseline`)
- **`darnit harness`** end-to-end
- **`/darnit-audit` coding-agent skill** (Tier 2 only)

**Tier 1** (`tests/darnit/parity/tier1/`) is a pytest suite that runs on every PR. For each fixture in `tests/darnit/parity/fixtures/`, it invokes the MCP tool directly AND runs the harness in-process (both with `MockLLMStep` -- no live API), then diffs their per-control status. The sole allowed drift is: the MCP tool leaves a control PENDING_LLM; the harness resolves it to any non-PENDING_LLM status via its LLM continuation loop. Anything else is a hard failure with a human-readable diff table.

**Tier 2** (`tests/darnit/parity/tier2/`) is a manual-dispatch-only GitHub Actions workflow. For each fixture, it captures the raw MCP tool JSON and invokes the `/darnit-audit` coding-agent skill via the Claude Agent SDK on the same fixture, then diffs the skill's final assistant message against the raw tool output. Any per-control status difference is a hard failure regardless of authority level. Access control (Environment-gated `ANTHROPIC_API_KEY` + required-reviewer approval) prevents unauthorized dispatches from spending API budget.

**Fixture corpus** starts with the existing `minimal_llm_repo` (reused from feature 026's fixture tree) plus new synthetic fixtures for the all-PASS, all-FAIL, mixed, and PENDING_LLM shapes. Each fixture optionally carries a `parity.toml` declaring its expected shape (TOML-parsed via stdlib `tomllib`); corpus-inventory checks (SC-008) use this file.

Closes #366. Diagnostic only -- any drift Tier 2 discovers becomes a separate feature to fix. Follow-up issues #368 (OpenAI SDK + other-provider parity) and #369 (scheduled cadence + governance-appropriate key sourcing) capture explicitly out-of-scope work.

## Technical Context

**Language/Version**: Python 3.11 / 3.12 (workspace targets, unchanged).

**Primary Dependencies (new -- test-side only, no product impact)**:

- `claude-agent-sdk` (Anthropic's Python SDK for scripted agent invocations). Added to a new `tests/darnit/parity/pyproject.toml` as a dev-group dep, NOT to any product package's `pyproject.toml`. SC-006 hard requirement.
- Nothing else new; `tomllib` is stdlib.

**Primary Dependencies (in use)**: `pydantic >= 2.0` (existing), `pytest` (existing), feature 026's `HarnessRun` + `MockLLMStep`, feature 025's `LLMStep` Protocol, `darnit_baseline.tools.audit_openssf_baseline`.

**Storage**: Filesystem only. Fixture directories under `tests/darnit/parity/fixtures/`. Tier 2 output artifacts (skill Markdown + tool JSON on failure) written to `parity-artifacts/` at CI job root, uploaded as workflow artifacts. No new persistent state.

**Testing**: pytest for Tier 1. Tier 2's runner is a Python script (`tests/darnit/parity/tier2/run.py`) invoked from GitHub Actions; not pytest because it hits a live API and needs artifact-write semantics that don't fit the pytest lifecycle cleanly.

**Target Platform**: Any host that runs darnit tests (Linux, macOS) for Tier 1. Tier 2 runs on GitHub-hosted `ubuntu-latest` in the workflow-dispatch job.

**Project Type**: Test suite + one GitHub Actions workflow. No product code changes.

**Performance Goals**: Tier 1 -- full corpus in under 60s (SC-002). Individual fixture in under 10s. Tier 2 -- one skill invocation per fixture; the workflow's total wall time depends on Anthropic API latency (typically 30s-120s per skill run for a small repo).

**Constraints**:

- **SC-006 hard rule**: no new runtime deps on `packages/darnit/pyproject.toml` or `packages/darnit-baseline/pyproject.toml`. All new deps live under a test-only dev group.
- **FR-014**: no product code changes. If a Tier-1 test needs a helper that doesn't exist on the harness or MCP tool, we flag it as follow-up work, we do not silently add product code.
- **FR-007a governance**: `ANTHROPIC_API_KEY` MUST live in a GitHub Environment (not a repository secret) and be reachable ONLY from the gated Tier 2 workflow. SC-005a is grep-verifiable.
- **FR-003**: Tier 1 offline. `MockLLMStep` for the harness; never a live API call.

**Scale/Scope**: MVP corpus is 4-6 fixtures. Small test suite (~600-800 lines total: ~300 Tier 1 test + comparator + auto-discovery machinery, ~200 Tier 2 runner + SDK invocation, ~100 skill Markdown parser, ~200 test fixtures). No new modules in `packages/`.

## Constitution Check

Constitution v1.3.0. Five Core Principles evaluated as gates.

| Principle | Applicable? | Verdict | Rationale |
|-----------|-------------|---------|-----------|
| I. Plugin Separation | Yes | PASS | The parity tests are consumers, not part of `darnit-core` or `darnit-baseline`. They import both packages' public surfaces (MCP tool function; harness `HarnessRun`) but add no code TO either package. Tier 2's Claude Agent SDK dep is test-only per FR-006 + SC-006. |
| II. Conservative-by-Default | Yes | PASS + REINFORCED | This feature exists to protect conservatism: the whole point of Tier 2 is catching the skill silently reclassifying a WARN as PASS. If the skill layer erodes the "WARN counts as FAIL" property from Principle II, Tier 2 makes the erosion visible. Tier 1 catches equivalent regressions in the harness before they merge. |
| III. TOML-First Architecture | Yes | PASS | Fixture metadata uses TOML (`parity.toml`), matching the framework's control-config format. No control changes; no new schema fields on framework TOMLs. Just fixture-side test metadata. |
| IV. Never Guess User Values | Yes | PASS + REINFORCED | Fixtures do NOT auto-generate context values. Any value a fixture needs is written explicitly in its `.project/project.yaml` at fixture-authoring time; the parity tests read whatever's there. No heuristic value inference. Related to Principle IV: Tier 2 exists precisely because a downstream layer (the coding-agent skill) was silently applying a heuristic interpretation of the tool's output; this feature makes those heuristics visible so the constitution's guarantee is externally observable. |
| V. Sieve Pipeline Integrity | Yes | PASS (N/A in substance) | This feature is downstream of the sieve; it does not modify the 4-phase pipeline. It exercises the same `run_sieve_audit` seam through two consumers to verify they produce identical output. |

**No violations.** No Complexity Tracking entries required.

Governance observations (not constitution violations, but worth calling out):

- FR-007 through FR-007b + SC-005a locks down a real risk: an unauthorized community member spending money out of a company-owned API key. This is enforced at the GitHub Actions Environment layer (not in code), so the security depends on correct workflow configuration. The plan's contract MUST include a workflow-config review step before merge.
- Feature 026's "no re-audit after collect" MVP policy is untouched. Neither Tier 1 nor Tier 2 exercises interactive answer collection (that's feature 027 territory); the resolver chain stays empty.

## Project Structure

### Documentation (this feature)

```text
specs/028-audit-parity-tests/
+-- spec.md                                  # /speckit-specify + /speckit-clarify output
+-- plan.md                                  # this file
+-- research.md                              # Phase 0: architectural decisions
+-- data-model.md                            # Phase 1: Fixture, AuditResult, DriftEntry, SkillReport, ParityReport
+-- quickstart.md                            # Phase 1: how to run Tier 1 locally + Tier 2 via workflow_dispatch
+-- contracts/
|   +-- tier1-parity-invariant.md            # What Tier 1 asserts + allowed-drift table
|   +-- tier2-workflow.md                    # workflow_dispatch shape + Environment/reviewer/secret config
|   +-- parity-toml-schema.md                # `parity.toml` schema fixtures may declare
+-- checklists/
|   +-- requirements.md                      # spec-quality checklist (exists)
+-- tasks.md                                 # /speckit-tasks output (later)
```

### Source Code (repository root)

**Zero changes to `packages/darnit/` or `packages/darnit-baseline/`.** Everything ships under `tests/` and `.github/workflows/`.

```text
tests/darnit/parity/
+-- __init__.py                              # empty
+-- fixtures/                                # NEW: the corpus lives here
|   +-- all_pass_repo/
|   |   +-- .baseline.toml                   # fixture config
|   |   +-- .project/project.yaml            # explicit context values
|   |   +-- parity.toml                      # {[expected] category="all_pass", counts={...}}
|   |   +-- <repo files>                     # LICENSE, README, etc as needed
|   +-- all_fail_repo/
|   |   +-- .baseline.toml
|   |   +-- parity.toml                      # {[expected] category="all_fail", ...}
|   |   +-- <minimal or empty repo files>
|   +-- mixed_repo/
|   |   +-- ...                              # some pass, some fail, some warn
|   |   +-- parity.toml                      # {[expected] category="mixed", ...}
|   +-- pending_llm_repo/                    # can reuse minimal_llm_repo from feature 026
|       +-- ...
|       +-- parity.toml                      # {[expected] category="pending_llm", has_pending_llm=true}
+-- tier1/
|   +-- __init__.py
|   +-- conftest.py                          # fixture auto-discovery pytest plugin
|   +-- comparator.py                        # AuditResult diff logic + DriftEntry construction + table formatting
|   +-- fixture_meta.py                      # parity.toml parser + schema validation
|   +-- test_mcp_vs_harness.py               # parametrized-per-fixture parity assertions
|   +-- test_corpus_inventory.py             # SC-008: assert at least one fixture per category
|   +-- test_comparator_adversarial.py       # SC-001/003: seeds divergences, asserts they're caught
+-- tier2/
    +-- __init__.py
    +-- run.py                               # entrypoint; invoked from workflow_dispatch
    +-- skill_markdown_parser.py             # best-effort parser for skill's final assistant message
    +-- claude_agent_sdk_client.py           # thin wrapper around the SDK; deterministic invocation
    +-- artifact_writer.py                   # writes tool JSON + skill Markdown to parity-artifacts/
    +-- diff.py                              # per-control status comparison, produces failure report

.github/workflows/
+-- parity-tier2.yml                         # NEW: workflow_dispatch-triggered; Environment-gated
```

**Structure Decision**: Test-suite-only. No `packages/` changes anywhere. The Claude Agent SDK dep is declared in a new dependency group in the workspace-level `pyproject.toml` (dev group) so `uv sync --dev` installs it for maintainers but no downstream user of darnit-core / darnit-baseline gets it as a transitive dep.

## Complexity Tracking

No violations. Section intentionally empty.
