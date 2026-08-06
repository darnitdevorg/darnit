# Implementation Plan: RFC-0001 Stage 1 -- Authority, ActionPlan Protocol, and MCP Loop

**Branch**: `025-rfc0001-stage1` | **Date**: 2026-08-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/025-rfc0001-stage1/spec.md` (with three clarifications from `/speckit-clarify` on 2026-08-05: client-owned MCP state, additive attestation field within v1 predicate, Pydantic AI required runtime dependency)

## Summary

Stage 1 of RFC-0001. Adds evidence `authority` to every step and result, replaces the fixed-enum Check-phase escalation with a per-phase execution rule keyed on authority, extracts `route()` from `cmd_run` into a public typed **ActionPlan protocol** in `darnit-core`, and exposes that protocol over MCP so a coding agent can drive the same loop `darnit run` does. SECURITY.md is the reference control that integrates all four properties end-to-end.

No functionality is removed. `cmd_run`, today's `sieve/orchestrator.py` per-phase pass loop, existing attestation output, and current MCP tool names all survive; each is re-seated behind explicit contracts. Feature 024's `test_cmd_run_e2e.py` suite is the mechanical guarantee that the refactor preserves observable behavior.

Because Stage 1 is a spec/PR series (per the RFC's staged plan), this plan identifies four mergeable slices that can land as separate PRs while sharing the same acceptance gate.

## Technical Context

**Language/Version**: Python 3.11 / 3.12 (workspace targets, unchanged).

**Primary Dependencies (new)**:
- `pydantic-ai-slim[anthropic]` -- required runtime dep of `darnit-core`, providing the default `LLMStep` implementation (Q3 clarification). Adds transitive `anthropic` SDK.
- No new dev dependencies.

**Primary Dependencies (unchanged, in use)**: `pydantic >= 2.0`, `fastmcp`, `cel-python`, `pyyaml`, existing sigstore/in-toto stack.

**Storage**: Filesystem only (unchanged). `.project/` for confirmation persistence (feature 018), attestation output as DSSE-in-envelope JSON. Stage 1 introduces no new persistence surface.

**Testing**: pytest, `unittest.mock` for stubs, `fastmcp.Client` for in-process MCP round-trip tests. Feature 024's `tests/darnit/cli/test_cmd_run_e2e.py` continues to run and MUST stay green (SC-005).

**Target Platform**: Any host that runs the darnit dev workspace (Linux, macOS). No new platform requirements.

**Project Type**: Multi-package Python workspace (unchanged). Stage 1 touches `packages/darnit/` (core), `packages/darnit-baseline/` (reference control), and the corresponding test trees.

**Performance Goals**: No new performance targets. The strategy-list runner's per-step overhead MUST NOT exceed the current per-phase pass loop's overhead by more than 15% on the feature-024 fixture (measured by wall-clock of the golden-path test); a regression beyond that is a plan-time flag.

**Constraints**: Client-owned `HarnessState` (Q1) implies the state MUST be JSON-serializable through Pydantic (`model_dump()` / `model_validate()`) so both the MCP wire format and the future durable-execution driver can round-trip it losslessly. No mutable references (open file handles, subprocess handles, live LLM sessions) may live on the state.

**Scale/Scope**: Stage 1 lands as ~4 PRs, ~3000-5000 lines net (production + tests + fixtures + reference control). The class of change is architectural: no user-visible feature ships, but every subsequent stage depends on the substrate.

## Constitution Check

Constitution version 1.3.0. Five Core Principles evaluated as gates.

| Principle | Applicable? | Verdict | Rationale |
|-----------|-------------|---------|-----------|
| I. Plugin Separation | Yes | PASS | The ActionPlan protocol and `LLMStep` Protocol live in `darnit-core`. `darnit-baseline` continues to import from `darnit-core`, not the other way. The reference SECURITY.md control ships in `darnit-baseline` (or adapts an existing baseline control per A6). The core code MUST NOT import `darnit_baseline` at any point. |
| II. Conservative-by-Default | Yes | PASS + STRENGTHENED | This stage codifies the principle. The whole point of the `authority` field and the per-phase Check rule is to enforce "only dispositive or asserted may conclude." SC-001 and SC-008 are mechanical tests of this property. |
| III. TOML-First Architecture | Yes | PASS | Strategy lists remain TOML-authored (`steps = [...]`). Handler names remain short strings resolved through the handler registry. No control metadata migrates to Python code. The compatibility layer (FR-015) is a loader-side translation of legacy phase-keyed tables into strategy lists, not a data-model bifurcation. |
| IV. Never Guess User Values | Yes | PASS | `authority = "asserted"` is defined as human-only (FR-002 domain check + spec edge case: "a step declares `authority = asserted` but ships without a recorded human confirmation... is a schema violation caught at load time"). No handler can claim `asserted` from code alone. Feature 018's confirmation persistence remains the only writer. |
| V. Sieve Pipeline Integrity | Yes | PASS + EXTENDED | Today's 4-phase pipeline (`file_must_exist` -> `exec/regex` -> `llm_eval` -> `manual`) is preserved as a compatibility shape (FR-015: legacy TOML translates into the new strategy list). The new runner adds authority-keyed termination on top of it, not instead of it. Existing handlers keep working; their default authority is inferred from the phase they lived in during translation (dispositive for deterministic/pattern; suggestive for llm_eval; asserted N/A here because no handler emits asserted). |

**No violations.** No Complexity Tracking entries required.

Two positive observations worth calling out (not gates):
- The stage's Q3 clarification (Pydantic AI required, not optional) closes a slippery-slope I had toward inventing a "no-LLM install tier." Recorded as durable feedback so it does not recur.
- The MCP client-owned state decision (Q1) means the MCP surface is stateless per-run, which simplifies the server implementation and defers session-management concerns to whenever/if a durable-execution driver arrives.

## Project Structure

### Documentation (this feature)

```text
specs/025-rfc0001-stage1/
+-- spec.md                                    # /speckit-specify + /speckit-clarify output
+-- plan.md                                    # this file
+-- research.md                                # Phase 0: architectural decisions
+-- data-model.md                              # Phase 1: authority, HarnessState, ActionPlan, errors
+-- quickstart.md                              # Phase 1: how to run + verify the four slices
+-- contracts/
|   +-- action-plan-protocol.md                # public typed contract on darnit-core
|   +-- mcp-tools.md                           # `run_next_action` / `submit_action_result` MCP shape
|   +-- attestation-authority-field.md         # additive field within v1 predicate
+-- checklists/
|   +-- requirements.md                        # spec-quality checklist (exists)
+-- tasks.md                                   # /speckit-tasks output (later)
```

### Source Code (repository root)

Multi-package workspace. Stage 1 touches:

```text
packages/darnit/                              # core (framework)
+-- src/darnit/
|   +-- core/
|   |   +-- action_plan.py                    # NEW: ActionPlan, HarnessState, next_action, submit_result
|   |   +-- errors.py                         # NEW or extended: OutOfOrderSubmission, ResultSchemaMismatch
|   |   +-- llm_step.py                       # NEW: LLMStep Protocol + PydanticAILLMStep default
|   |   +-- authority.py                      # NEW: Authority Literal, helpers, load-time schema validation
|   +-- sieve/
|   |   +-- models.py                         # MODIFIED: CheckResult + HandlerResult add `authority` field
|   |   +-- handler_registry.py               # MODIFIED: HandlerResult.authority; registration checks
|   |   +-- orchestrator.py                   # MODIFIED: strategy-list runner (from per-phase pass loop);
|   |                                         #           authority-keyed termination rule
|   +-- agent/
|   |   +-- graph.py                          # MODIFIED: route() becomes a thin adapter around next_action
|   |   +-- state.py                          # MODIFIED: AuditState -> HarnessState (name + shape evolution)
|   +-- cli.py                                # MODIFIED: cmd_run consumes ActionPlan protocol internally
|   +-- server/
|   |   +-- tools/
|   |       +-- harness_loop.py               # NEW: run_next_action / submit_action_result MCP tools
|   +-- config/
|       +-- control_loader.py                 # MODIFIED: legacy phase-keyed TOML -> strategy list (FR-015)
+-- pyproject.toml                            # MODIFIED: pydantic-ai-slim[anthropic] added as runtime dep

packages/darnit-baseline/                     # implementation
+-- src/darnit_baseline/
|   +-- openssf-baseline.toml                 # MODIFIED: SECURITY.md control gets a strategy list with
|                                             #           dispositive file_exists + suggestive llm_extract
|                                             #           + collect + remediate steps

tests/darnit/                                 # framework tests
+-- core/
|   +-- test_action_plan.py                   # NEW: US2 direct-Python protocol tests
|   +-- test_llm_step.py                      # NEW: LLMStep Protocol conformance + PydanticAI adapter
|   +-- test_authority.py                     # NEW: authority field, schema validation, US1 property
+-- sieve/
|   +-- test_strategy_runner.py               # NEW: per-phase Check execution rule (SC-001)
|   +-- test_authority_terminates.py          # NEW: only dispositive/asserted may conclude (SC-001, SC-008)
+-- cli/
|   +-- test_cmd_run_e2e.py                   # UNCHANGED expectation (feature 024 baseline);
|                                             # tests MUST continue to pass through the refactor
+-- server/
|   +-- test_harness_loop_mcp.py              # NEW: US3 MCP round-trip tests (in-process fastmcp.Client)
+-- config/
|   +-- test_legacy_phase_translation.py      # NEW: SC-006 round-trip lossless translation

tests/darnit_baseline/                        # implementation tests
+-- controls/
|   +-- test_security_md_reference.py         # NEW: SC-004 end-to-end SECURITY.md via CLI + MCP
+-- attestation/
|   +-- test_authority_field.py               # NEW: SC-007 authority present + compat with older readers
+-- fixtures/
|   +-- prompt_injection_repo/                # NEW: SC-008 adversarial input; README carries an injection payload
```

**Structure Decision**: Reuse the existing multi-package workspace layout. No new package. The rationale for putting `action_plan.py` and `llm_step.py` in `darnit/core/` (rather than a new subpackage) is that both are load-bearing framework primitives on the same level as `plugin.py` and `discovery.py` -- creating a new subpackage would add navigation cost without earning organisational clarity.

**Slice boundaries** (for the tasks phase; not enforced by this plan directly):

1. **Slice A -- Authority + Check-phase rule.** Adds the `authority` field, per-phase execution rule, and the SC-001/SC-008 tests. Does NOT touch `cmd_run`, MCP, or reference control. Ships US1 in isolation; every existing test in `tests/darnit/` and `tests/darnit_baseline/` continues to pass. Smallest useful slice; the safety property is real value on its own.

2. **Slice B -- ActionPlan protocol extraction.** Adds `darnit.core.action_plan`, refactors `cmd_run` to consume it, adds SC-002 tests, keeps `route()` as a thin adapter. Depends on Slice A landing so `HarnessState` can carry authority through the loop.

3. **Slice C -- MCP surface.** Adds `run_next_action` / `submit_action_result` tools, SC-003 tests, and the equivalence tests between direct-Python and MCP paths. Depends on Slice B.

4. **Slice D -- SECURITY.md reference control + acceptance gate.** Adds the reference control (or adapts existing baseline), the SC-004 end-to-end tests via CLI + MCP, SC-007 attestation-authority tests, and SC-008 adversarial-input fixture. Depends on Slices A-C.

Each slice is a PR. Slice A is the smallest and highest-value-per-line; if the wider stage slips, Slice A alone is a meaningful safety improvement worth shipping.

## Complexity Tracking

Not applicable. Constitution Check passed with no violations.
