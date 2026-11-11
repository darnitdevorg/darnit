# Implementation Plan: Judge and Confirm After Remediation

**Branch**: `045-remediation-judge-confirm` | **Date**: 2026-10-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/045-remediation-judge-confirm/spec.md`

## Summary

Complete the feature 041 path in the agent flows. A remediation outcome whose re-check is PENDING says what it awaits (`pending_kind` on `changed_not_passing`), and the apply result lists those controls and the next step. A new read-only tool, `get_pass_candidates`, returns the PASS candidates that match the current evidence with their reasoning and cited passages, marks documents remediation wrote, and returns a confirmation procedure. `/darnit-comply` judges after improving the generated files and then runs that confirmation step before the final audit and pull request; `/darnit-audit` ends with the same step. The #666 replay gains recorded judgments and confirmations and reports PASS after judge-and-confirm. No new route to PASS.

## Technical Context

**Language/Version**: Python 3.11/3.12 (workspace targets)

**Primary Dependencies**: existing only: `pydantic >= 2` (`extra="forbid"` models), FastMCP via `mcp`, `tomllib`. No new runtime dependencies.

**Storage**: unchanged. Candidates and confirmations in the feature 040/041 operator-side store; run manifests operator-side (15.6). Recorded judgments in `scripts/comply_replay.toml` (test-only).

**Testing**: pytest (`tests/darnit/remediation/`, `tests/darnit/server/`, `tests/darnit_baseline/`), plus the #666 replay and the `darnit-e2e` agent phases.

**Target Platform**: MCP server (`darnit serve`) used by coding agents; skills shipped in `packages/darnit/src/darnit/skills/`.

**Project Type**: library + MCP server + agent skills (uv workspace).

**Performance Goals**: `get_pass_candidates` pages under 40,000 bytes, like `get_judgment_requests`. The apply result grows only by control ids.

**Constraints**: Principles II and IV: nothing becomes PASS without the operator's explicit confirmation; procedures never carry candidate values. ASCII-only text.

**Scale/Scope**: openssf-baseline has under 10 document-content controls a remediation can write; one confirmation step per run.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
|---|---|---|
| I. Plugin Separation | `get_pass_candidates` and the procedures are framework-neutral in `packages/darnit`; reading control title/description goes through the loaded framework config, not an implementation import. The outcome field is set in the baseline orchestrator (implementation importing framework). | Pass |
| II. Conservative-by-Default | `pending_kind` is informational; outcomes with it stay non-compliant and never `fixed` (validator, SC-005). No step concludes PASS; confirmation is the operator's. | Pass |
| III. TOML-First | No control changes. Title and description are read from TOML. | Pass |
| IV. Never Guess User Values | Confirmation only for candidates the person names; no defaults or confirm-all; candidates labelled with origin (model, source, written-by-remediation); procedures hold placeholders only. | Pass |
| V. Sieve Pipeline Integrity | Sieve unchanged; the re-check stays a cache-neutral subset audit (15.5). | Pass |
| Development workflow | Spec first: framework-design 5.4 (`get_pass_candidates`), 15.4 (`pending_kind`, `awaiting`), new 15.9 (judge and confirm after remediation), 15.8 skills row; then `validate_sync.py`. | Planned |

Post-design re-check: unchanged, Pass. No complexity exceptions.

## Project Structure

### Documentation (this feature)

```text
specs/045-remediation-judge-confirm/
|-- plan.md
|-- research.md
|-- data-model.md
|-- quickstart.md
|-- contracts/
|   |-- get-pass-candidates.md
|   |-- remediation-outcome.md
|   |-- procedures.md
|   `-- replay-recorded-judgments.md
`-- tasks.md            # /speckit-tasks
```

### Source Code (repository root)

```text
docs/architecture/framework-design.md                     # 5.4, 15.4, 15.8, new 15.9
packages/darnit/src/darnit/remediation/plan.py            # RemediationOutcome.pending_kind, RemediationRun.awaiting
packages/darnit/src/darnit/server/procedures.py           # confirmation_procedure, remediation_next_steps
packages/darnit/src/darnit/server/tools/judgments.py      # get_pass_candidates (+ registration)
packages/darnit/src/darnit/skills/darnit-comply/SKILL.md  # judge after improving, confirmation step, order
packages/darnit/src/darnit/skills/darnit-audit/SKILL.md   # confirmation step
packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py  # set pending_kind; Awaiting line; Next steps
scripts/comply_replay.py, scripts/comply_replay.toml, scripts/comply_replay_expected.json  # after #666
tests/darnit/remediation/test_outcomes_pending_kind.py
tests/darnit/server/test_pass_candidates.py
tests/darnit/server/test_procedures_confirmation.py
tests/darnit_baseline/remediation/test_remediation_awaiting.py
tests/darnit/server/test_procedures_next_steps.py
tests/darnit_baseline/test_comply_replay_recorded.py      # after #666, next to whatever tests #666 adds
```

**Structure Decision**: Existing workspace layout. Framework pieces in `packages/darnit`, the outcome wiring in `packages/darnit-baseline`, measurement in `scripts/` with #666.

## Delivery

1. Spec text (framework-design) and the outcome model (`pending_kind`, `awaiting`), with tests. User Story 3.
2. `get_pass_candidates`, the two procedures, and the skills. User Stories 1 and 2.
3. Replay recorded judgments and confirmations, after #666 merges. User Story 4.
4. e2e per quickstart: replay, headless comply, interactive Layer 3, recorded in the PR.

Delivery steps 1-2 can merge before #666; step 3 is a separate PR.

## Complexity Tracking

None.
