# Implementation Plan: Interactive Question Resolvers

**Branch**: `027-interactive-resolvers` | **Date**: 2026-08-08 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/027-interactive-resolvers/spec.md` (with 5 clarifications from `/speckit-clarify` on 2026-08-07: hybrid entry-point + direct-injection registration; `/dev/tty` for MVP prompt output with a pluggable channel seam; bookend-only progress display; symmetric empty-Answer skip; full `resolution_trail` for auditability).

## Summary

Adds `--interactive` to `darnit harness` and a new `QuestionResolver` Protocol that sits DOWNSTREAM of the existing `AnswerSource` chain from feature 026. Any question left uncovered by `.project/project.yaml` + `--answers <file>` is offered to registered resolvers in order until one returns an answer or the chain is exhausted.

Ships:
- **New Protocol**: `QuestionResolver` (async, `@runtime_checkable`), distinct from `AnswerSource`. Semantics differ -- `AnswerSource` is passive preloaded-value lookup; `QuestionResolver` is an active resolver that goes and gets an answer somehow. Serves interactive today; A2A / GitHub-issue-comment / Slack / webhook resolvers tomorrow (as separate feature-branches).
- **Reference implementation**: `InteractiveTerminalResolver` prompting on `/dev/tty` (private operator channel, isolated from stdout report stream and stderr progress stream). Empty and whitespace-only input treated as skip. Ctrl+C stops further prompts but preserves already-collected answers.
- **Registration mechanism (hybrid)**: Python entry points under `darnit.question_resolvers` (matching darnit's existing `darnit.implementations` discovery pattern) AND direct injection into `HarnessRun.question_resolvers`. Third-party packages ship a wheel with an entry-point declaration; the harness discovers them at CLI startup.
- **CLI flag**: `--interactive` on `darnit harness`, default off. Registers the terminal resolver at the head of the resolver chain. Non-TTY / no-`/dev/tty` under `--interactive` -> fail-fast `SETUP_ERROR` in under 2s.
- **Auditability**: Per-question `resolution_trail` in the report -- one entry per resolver that was offered the question, with an outcome (`answered` | `skipped` | `errored`). Answers carry `authority: "asserted"` (enforced at the `Answer` model level via `Literal["asserted"]` with a fixed default -- resolver authors physically cannot construct an `Answer` with a different authority) and an `origin` string identifying the resolver. The `PendingFeedbackEntry` also surfaces `answer_authority` alongside `answered`/`answer` so downstream consumers can filter for human-provided values without inspecting the trail.
- **Per-resolver timeout**: `HarnessRun.per_resolver_timeout_s: float | None`. Default `None` (no timeout). When set, each `resolver.resolve()` call is wrapped in `asyncio.wait_for`; a timeout becomes a `ResolutionTrailEntry(outcome="errored", ...)` and the driver moves on. Enforces FR-011.

Non-scope for this feature: re-audit after collect (feature 026's "no re-audit" MVP policy stays intact); alternative output channels beyond `/dev/tty` (FR-004a designs the seam, the specific event/log adapters are future features).

## Technical Context

**Language/Version**: Python 3.11 / 3.12 (workspace targets, unchanged).

**Primary Dependencies (new)**: None. This feature is stdlib-only on the production surface (`typing.Protocol`, `typing.runtime_checkable`, `importlib.metadata.entry_points`, direct `open("/dev/tty", ...)`, `asyncio`).

**Primary Dependencies (in use)**: `pydantic >= 2.0` (for the `Answer` and `ResolutionTrailEntry` models). Feature 026 internals: `HarnessRun`, `AnswerResolver`, `HarnessReport`, `PendingFeedbackEntry`. Feature 025 internals: `authority` Literal type. `pytest` for tests.

**Storage**: Filesystem only (unchanged). Interactive answers land in the same `HarnessReport` artifact feature 026 writes; the report gains `resolvers_used` and per-question `resolution_trail` fields. No new persistent state.

**Testing**: pytest. `InteractiveTerminalResolver` accepts injectable input/output streams so tests can pass `io.StringIO` in place of `/dev/tty`. Entry-point discovery is exercised via `importlib.metadata`'s test hooks. A `MockQuestionResolver` fixture returns preconfigured answers or raises to exercise the trail's `errored` outcome.

**Target Platform**: POSIX for MVP (`/dev/tty` availability). Windows is intentionally out of scope for the MVP -- FR-004a's pluggable-channel design accommodates it later without a Protocol change.

**Project Type**: Additive to the existing `darnit harness` subcommand. Ships in `packages/darnit/src/darnit/harness/`.

**Performance Goals**: SC-001 -- five questions answered end-to-end in under three minutes at a terminal (target ergonomics). SC-005 -- fail-fast in under two seconds when no operator channel is available.

**Constraints**: 
- **Constitution IV**: an interactive answer is a human confirmation, tagged `authority: "asserted"`. Feature 026's "no re-audit after collect" MVP policy is preserved -- the audit's PASS/FAIL doesn't silently flip based on interactive input; the assertion is captured for a later run.
- **Feature-026 stream contracts unchanged**: stdout carries the report body when `--output` is unset; stderr carries progress + exit summary. Prompts write to `/dev/tty` (a third stream, physically separate on POSIX).
- **API key redaction from feature 026 applies unchanged**: any exception message that surfaces in the `resolution_trail`'s `errored` summary passes through `_redact_secrets` before landing in the report.

**Scale/Scope**: MVP is one reference resolver + one CLI flag + report additions. Expected slice size: ~400-600 lines net production + ~400-500 lines tests.

## Constitution Check

Constitution v1.3.0. Five Core Principles evaluated as gates.

| Principle | Applicable? | Verdict | Rationale |
|-----------|-------------|---------|-----------|
| I. Plugin Separation | Yes | PASS | `QuestionResolver` Protocol lives in `darnit-core` (`packages/darnit/src/darnit/harness/question_resolvers.py`). Third-party resolvers live outside `packages/darnit/` and register via a new entry-point group `darnit.question_resolvers`, mirroring the existing `darnit.implementations` pattern. SC-002 enforces: a resolver defined outside `packages/darnit/src/darnit/harness/` is invoked without any change to files under that directory. |
| II. Conservative-by-Default | Yes | PASS + REINFORCED | Feature 026's "no re-audit after collect" MVP policy stays. Interactively supplied values are recorded in the report but do NOT silently promote a FAIL to PASS. A control that was FAIL because a value was missing at audit time stays FAIL in this report; a subsequent audit run with the value persisted to `.project/project.yaml` re-evaluates it. Nothing silently changes based on interactive input. |
| III. TOML-First Architecture | No | N/A | No control definitions. No TOML schema changes. |
| IV. Never Guess User Values | Yes | PASS + REINFORCED | This feature exists precisely to elicit human confirmation. The interactive resolver produces answers tagged `authority: "asserted"` -- a human said this, not a heuristic. Empty and whitespace-only inputs (interactive OR programmatic per FR-006a) collapse to skip so no resolver author can accidentally record an assertion of emptiness. The audit trail (`resolution_trail`) makes every resolver attempt visible so an auditor can see how each value was obtained. |
| V. Sieve Pipeline Integrity | No | N/A | This feature runs downstream of the sieve (in the collect phase). The 4-phase pipeline is unchanged. |

**No violations.** No Complexity Tracking entries required.

Two positive observations:
- The `QuestionResolver` Protocol seam extends feature 026's fleet-operator framing without a rewrite. Future adapters (A2A, GitHub issue comments, Slack, webhook) plug in as external packages registering via entry point; no darnit-core change per adapter.
- The `resolution_trail` per-question audit surface is a genuine Constitution IV artifact: "how was this value obtained" is now recoverable from the report alone. That property matters more as third-party resolvers accumulate.

## Project Structure

### Documentation (this feature)

```text
specs/027-interactive-resolvers/
+-- spec.md                              # /speckit-specify + /speckit-clarify output
+-- plan.md                              # this file
+-- research.md                          # Phase 0: architectural decisions
+-- data-model.md                        # Phase 1: QuestionResolver, Answer, ResolutionTrailEntry
+-- quickstart.md                        # Phase 1: how to run + verify locally
+-- contracts/
|   +-- question-resolver-protocol.md    # Protocol shape + registration contract
|   +-- interactive-resolver-behavior.md # /dev/tty, prompt payload, empty/EOF/Ctrl+C
|   +-- resolution-trail-schema.md       # `resolution_trail` field in HarnessReport JSON
+-- checklists/
|   +-- requirements.md                  # spec-quality checklist (exists)
+-- tasks.md                             # /speckit-tasks output (later)
```

### Source Code (repository root)

Everything ships in `darnit-core`. No new package.

```text
packages/darnit/src/darnit/harness/
+-- question_resolvers.py     # NEW: QuestionResolver Protocol, Answer, ResolutionTrailEntry
+-- interactive_resolver.py   # NEW: InteractiveTerminalResolver (POSIX /dev/tty)
+-- resolver_discovery.py     # NEW: entry-point discovery for `darnit.question_resolvers`
+-- driver.py                 # UPDATED: HarnessRun.question_resolvers field, resolver-chain
|                             #          invocation in _collect_unanswered, resolution_trail
+-- report.py                 # UPDATED: HarnessReport.resolvers_used, PendingFeedbackEntry
|                             #          gains resolution_trail; markdown/json emit trail
+-- exit_codes.py             # UNCHANGED
+-- answer_sources.py         # UNCHANGED (AnswerSource remains passive-lookup only)

packages/darnit/src/darnit/cli.py  # UPDATED: cmd_harness gains --interactive flag; wires
                                   #          discovery + terminal resolver into HarnessRun

packages/darnit/pyproject.toml     # UPDATED: entry-point group declaration for
                                   #          `darnit.question_resolvers`; a
                                   #          darnit-core-supplied "interactive_terminal"
                                   #          entry-point registration for MVP

tests/darnit/harness/
+-- test_question_resolvers.py      # NEW: Protocol conformance, Answer validation
+-- test_interactive_resolver.py    # NEW: prompt format, empty/EOF/Ctrl+C, streams injectable
+-- test_resolver_discovery.py      # NEW: entry-point discovery via importlib.metadata
+-- test_resolution_trail.py        # NEW: trail population, outcome enum, ordering
+-- test_driver.py                  # UPDATED: resolver chain invocation + no-reaudit invariant
+-- test_cli.py                     # UPDATED: --interactive flag; fail-fast on non-TTY
+-- test_report.py                  # UPDATED: resolution_trail in JSON + Markdown output
+-- fixtures/
    +-- mock_resolver_pkg/          # NEW: external-to-harness package that registers a
                                    #      QuestionResolver via entry point; used by
                                    #      test_resolver_discovery + test_driver to
                                    #      enforce SC-002 (no edits under harness/)
```

**Structure Decision**: Additive-only. Three new modules in `packages/darnit/src/darnit/harness/`. Two of those (`question_resolvers.py`, `resolver_discovery.py`) are the reusable substrate; the third (`interactive_resolver.py`) is the reference implementation of the Protocol. `driver.py`, `report.py`, `cli.py` receive small, well-scoped extensions. The fixture package `tests/darnit/harness/fixtures/mock_resolver_pkg/` exists specifically to make SC-002 mechanically enforceable -- a resolver defined outside the harness tree that the CI test suite proves is discoverable.

## Complexity Tracking

No violations. This section left intentionally empty.
