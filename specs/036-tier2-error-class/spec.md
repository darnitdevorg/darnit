# Feature Specification: Distinguishable Side-Effect Failures via `error_class`

**Feature Branch**: `036-tier2-error-class`

**Created**: 2026-09-06

**Status**: Draft

**Input**: User description: "Implement issue #419 -- Determinism Tier 2: network / side-effect failures must be distinguishable from real verdicts. Add a structured `error_class` field to `HandlerResult` evidence so operators can tell 'we couldn't verify (network/auth/timeout failed)' apart from 'we verified and it concluded FAIL/WARN'. Bump the log level on those failures from DEBUG to WARN. Surface `error_class` distinctly in markdown/JSON/SARIF report output. Attestation predicate should also carry `error_class` when present."

## Clarifications

### Session 2026-09-06

- Q: How is `error_class` propagated from pass attempts to the higher-level CheckResult? -> A: From the RESOLVING pass's HandlerResult only. Earlier failed passes' `error_class` values are dropped, matching "first conclusive result wins" pipeline semantics.
- Q: How is the `error_class` enum represented and extended in future releases? -> A: Strict `Literal` type at the code layer with the six named values in v0. Expanding the enum requires a code change and new release; runtime rejects unknowns. Matches feature 025's `authority` pattern.
- Q: What is the scope of the DEBUG-to-WARN log-level bump? -> A: Bump exactly the four named sites (MCP handler per FR-006, exec timeout per FR-007, orchestrator crash per FR-007, context auto-detect git failures per FR-008). Sweeping other DEBUG-level exception handlers is deferred as follow-ups triggered by real-audit evidence.
- Q: What is the scope of rate-limit / auth detection heuristics in the exec handler? -> A: GitHub-only patterns for v0 (`gh` CLI stderr shape). Unclassified subprocess failure falls back to `error_class = network` for stderr-matched patterns and `crashed` for unexpected exceptions. Follow-ups add per-target pattern packs (git, curl, others) when real audits surface the need.

## Context

Darnit currently produces a single verdict envelope per control -- `PASS` / `FAIL` / `WARN` / `INCONCLUSIVE` / `ERROR` -- with no structured indicator of WHY a non-PASS verdict landed. Concretely: an audit run against a repo behind a corporate proxy that blocks `api.github.com` gets a stream of `gh api` timeouts, each recorded as `ERROR` (or worse, silently as `FAIL` after CEL evaluates against empty evidence), indistinguishable in the report from a control that actually ran cleanly against a live network and concluded the repo does not satisfy the check.

For a compliance tool, the operator's mental model needs to distinguish:

- **Verified failure**: the check ran; the repo does not comply.
- **Could-not-verify**: the check could not run to completion (network unreachable, auth token expired, rate limit hit, subprocess crashed).

Constitution Principle II (Conservative-by-Default) requires WARN to be treated as FAIL for compliance calculations, so both cases still gate the audit correctly -- but they need different operator responses. A verified failure is a repo problem the operator should fix. A could-not-verify is an environment problem the operator should fix by, e.g., unblocking network egress or refreshing an auth token.

This feature adds an `error_class` field to the result envelope that carries a small enum of environmental failure causes, surfaces it in the report layer, and stops swallowing these signals at DEBUG log level.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Operator sees "network failed" separately from "check failed" in report output (Priority: P1)

An operator runs `darnit audit` against a repo. Their auth token is expired; `gh api /repos/.../license` returns non-zero exit with a 401 body. Before this feature: the control reports `ERROR - Command failed` or `FAIL - CEL expr evaluated false against empty evidence`, and the operator's first instinct is to look at the repo. After this feature: the control's report entry includes `error_class: auth`, making it obvious the fix is to refresh `GH_TOKEN`, not to change the repo.

**Why this priority**: This is the primary user-visible outcome. Without it the operator can't triage the audit correctly.

**Independent Test**: Force `gh api` to return a 401 (or run without `GH_TOKEN` set) against a control that shells out to `gh`. Inspect the markdown report and confirm the affected control shows an environmental error class alongside its verdict, not just a bare failure message.

**Acceptance Scenarios**:

1. **Given** a control whose exec handler shells out to `gh api /repos/OWNER/REPO/license` and `GH_TOKEN` is invalid, **When** the audit runs, **Then** the control's report entry includes `error_class = auth` and the operator can distinguish it from a control that returned FAIL via a clean CEL evaluation.
2. **Given** a control whose exec handler times out (`gh` process exceeds handler timeout), **When** the audit runs, **Then** the control's report entry includes `error_class = timeout`.
3. **Given** a control whose exec handler exits non-zero with rate-limit-shaped stderr (`API rate limit exceeded`), **When** the audit runs, **Then** the control's report entry includes `error_class = rate_limit`.
4. **Given** a control whose exec handler runs cleanly and the CEL expression concludes false, **When** the audit runs, **Then** the control's report entry has NO `error_class` (verdict is a real failure).

---

### User Story 2 - Environmental failures land in default log output at WARN (Priority: P1)

Today an operator running `darnit audit` sees INFO-level progress but no indication that half the sieve passes are silently timing out under the hood -- those log at DEBUG. After this feature, environmental failures log at WARN so the default log level surfaces the problem without requiring the operator to know to bump verbosity.

**Why this priority**: Without loud logging, operators don't realize their audit was degraded. They see the report, treat WARN counts as real, and act on wrong information.

**Independent Test**: Run an audit with default log level; force some subset of side-effect handlers to error (e.g., unset `GH_TOKEN` so `gh api` fails). Confirm the stderr contains WARN-level log lines identifying which control and which `error_class` triggered.

**Acceptance Scenarios**:

1. **Given** default log level (INFO for stderr), **When** an exec handler times out, **Then** a WARN log line names the control ID, the handler, and `error_class = timeout`.
2. **Given** default log level, **When** an MCP handler hits a network exception, **Then** a WARN log line names the MCP tool and `error_class = network` (or `handshake_failed`).
3. **Given** default log level, **When** the context auto-detect chain has a git subprocess failure, **Then** a WARN log line names the context key and `error_class`.
4. **Given** an audit that successfully runs to completion with zero environmental failures, **When** the audit runs, **Then** there are NO new WARN log lines from this feature (the change is silent in the happy path).

---

### User Story 3 - JSON and SARIF outputs machine-consume `error_class` (Priority: P2)

An operator or downstream tool consumes the JSON or SARIF report programmatically. After this feature, when a control has an `error_class`, it appears as a distinct top-level field on the result object (not buried in `details`), so downstream tools (dashboards, ticketing integrations, CI job classifiers) can branch on it.

**Why this priority**: This is a machine-consumer story; humans have Story 1. Slower payoff but foundational for the fleet-operator persona.

**Independent Test**: Run an audit that produces at least one environmental failure. Parse the JSON output; confirm the affected control has `error_class` at the same nesting depth as `status`.

**Acceptance Scenarios**:

1. **Given** JSON output format, **When** a control has environmental error, **Then** the control's JSON object has an `error_class` field at the same level as `status` and `id`.
2. **Given** SARIF output format, **When** a control has environmental error, **Then** the SARIF result has an `error_class` property in the `properties` bag.
3. **Given** neither JSON nor SARIF, **When** a control has no environmental error, **Then** the `error_class` field is absent (not `null`; not present).

---

### User Story 4 - Attestation predicate carries `error_class` when present (Priority: P2)

A control whose audit was gated by an environmental failure MUST have that fact recorded in the in-toto attestation predicate, so a later verifier looking at the signed evidence can see the audit was produced under degraded conditions.

**Why this priority**: Attestations are the durable audit artifact. A bare PASS/FAIL in a signed attestation, when the underlying audit was actually an environmental failure, is exactly the kind of misleading claim compliance tooling must not produce.

**Independent Test**: Generate an attestation for an audit run that had at least one environmental failure. Parse the attestation predicate; confirm the affected control's result entry carries `error_class`.

**Acceptance Scenarios**:

1. **Given** an audit run that produced a control with `error_class = network`, **When** an attestation is generated, **Then** the attestation predicate's per-control entry for that control includes `error_class = "network"`.
2. **Given** an audit run with no environmental failures, **When** an attestation is generated, **Then** no result entry carries an `error_class` field (attestation shape is unchanged in the happy path).

---

### Edge Cases

- **Handler returns non-zero exit AND CEL expression evaluates false**: the exec-then-CEL layer currently transitions PASS + CEL-false to INCONCLUSIVE and FAIL + CEL-false to FAIL (per `_apply_cel_expr` in the orchestrator). Neither transition should silently strip a pre-existing `error_class` set by the handler. If the handler set `error_class = timeout` and CEL evaluated against empty evidence, the final result should still carry `error_class = timeout`.
- **Multiple handlers in a pass chain each set different error_class values**: only the RESOLVING pass's `error_class` propagates to the CheckResult (per clarify Q1 / FR-009a). A later pass that resolves the control on its own evidence supersedes an earlier pass's environmental error; the earlier `error_class` is discarded rather than aggregated.
- **Handler doesn't classify its own failure**: exec-handler catches a bare `OSError` it wasn't expecting. `error_class` defaults to `crashed`, not to no-error-class-at-all, so the operator still sees "something environmental went wrong" rather than a silent misclassification as FAIL.
- **Rate-limit detection is heuristic (stderr text-match)**: GitHub's rate-limit response is a 403 with specific header shape. Our exec handler only sees stdout/stderr/exit-code, so classification relies on stderr matching known patterns (`API rate limit exceeded`, `secondary rate limit`, `abuse detection`). Misclassification lands in `auth` or generic `network`; not fatal, just less precise.
- **`error_class` conflicts with the existing top-level `status`**: an `error_class = crashed` alongside `status = PASS` is a bug (a crashed handler can't produce a real PASS). The feature MUST make this shape unrepresentable in code (assertion or type constraint), not just document it.
- **Legacy consumers reading result envelopes**: any external consumer of the JSON envelope must ignore unknown fields; the `error_class` field is additive and OPTIONAL. Existing tests that assert exact-shape equality on result envelopes will need to be updated to allow the new field, but any that check specific known keys will pass unchanged.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The result envelope produced by every handler (`HandlerResult`) MUST support an optional `error_class` field that carries a small enumerated string.
- **FR-002**: The `error_class` enumeration is a strict `Literal` type at the code layer (per clarify Q2), with v0 values exactly: `network`, `auth`, `timeout`, `rate_limit`, `not_found`, `crashed`. Expanding the enum in a future release requires a code change (adding a value to the Literal) plus a new darnit release.
- **FR-002a**: Because `typing.Literal` is a static-analysis construct with no runtime effect, the six-value set MUST also exist as a runtime-checkable `frozenset` alongside the Literal, and `HandlerResult.__post_init__` MUST raise `ValueError` when `error_class` is set to a value outside that set. Rationale: a compliance tool that silently accepts a malformed `error_class` would emit an attestation carrying an uninterpretable failure cause. Note that feature 025's `authority` field pairs its Literal with a frozenset for a *fail-safe* (`is_terminal_authority()` returns False for unknowns) rather than a rejection; this feature chooses rejection because an unknown `error_class` has no safe default -- it is neither "the check failed" nor "the check could not run".
- **FR-003**: When the `exec` handler catches `subprocess.TimeoutExpired`, the result MUST carry `error_class = timeout`.
- **FR-004**: When the `exec` handler observes a non-zero exit and stderr matches known GitHub API rate-limit patterns (per clarify Q4: `gh` CLI stderr shape only for v0), the result MUST carry `error_class = rate_limit`. Non-GitHub targets fall through to FR-005a's generic `network` fallback.
- **FR-005**: When the `exec` handler observes a non-zero exit and stderr matches known GitHub auth-failure patterns (HTTP 401 / 403 without rate-limit signal / expired token, per clarify Q4 GitHub-only v0 scope), the result MUST carry `error_class = auth`. Non-GitHub targets fall through to FR-005a's generic `network` fallback.
- **FR-005a**: When the `exec` handler observes a non-zero exit that does NOT match a known GitHub pattern from FR-004 or FR-005, the result MUST carry `error_class = network` (per clarify Q4 fallback rule). Unexpected exceptions from the handler itself land in `crashed` via FR-007.
- **FR-006**: When the `mcp` handler catches `McpToolTimeout`, the result MUST carry `error_class = timeout`. When it catches `McpServerHandshakeFailed`, MUST carry `error_class = network`. When it catches `McpServerBinaryMissing`, MUST carry `error_class = not_found`. Every other `McpPoolError` subclass MUST also be classified, per the complete mapping table in `contracts/error-class.md` section 2.2 -- leaving any catchable MCP exception unclassified would reintroduce the exact ambiguity this feature removes.
- **FR-007**: When the orchestrator's outer try/except catches an unexpected handler exception (line 410-422 area), the result MUST carry `error_class = crashed` and the log MUST fire at WARN (not DEBUG).
- **FR-008**: When the context auto-detect chain fails a git subprocess call (`detect_platform` and similar), the failure MUST be logged at WARN (not DEBUG) with the context key name and appropriate `error_class`.
- **FR-008a**: The DEBUG-to-WARN bump scope is exactly the four sites named in FR-006, FR-007 (both clauses), and FR-008 (per clarify Q3). Other DEBUG-level exception handlers in the codebase are NOT swept in v0; they are follow-up candidates when real audits surface the need.
- **FR-009**: The `_apply_cel_expr` post-step MUST preserve any `error_class` set by the pre-CEL handler result, even when the CEL evaluation transitions the status.
- **FR-009a**: The higher-level `CheckResult` MUST carry `error_class` from the RESOLVING pass's `HandlerResult` only (per clarify Q1). Earlier non-resolving passes' `error_class` values are dropped, matching "first conclusive result wins" pipeline semantics. This preserves the CheckResult's scalar shape and lets downstream classifiers branch on a single value.
- **FR-010**: The markdown formatter MUST surface `error_class` as an inline annotation on the affected control (e.g., "OSPS-XX-01.01: ERROR [network] - <message>"). The exact rendering may be refined during implementation; the requirement is that `error_class` is visually distinguishable from the verdict.
- **FR-011**: The JSON formatter MUST include `error_class` as a top-level field on each result object when present, at the same nesting depth as `status`. When absent, the field MUST NOT be emitted (not `null`, not empty string).
- **FR-012**: The SARIF formatter MUST include `error_class` in each result's `properties` bag when present.
- **FR-013**: The attestation predicate (darnit-baseline in-toto attestation) MUST carry `error_class` per-control when present.
- **FR-014**: An audit that produces zero environmental failures MUST produce identical output (markdown, JSON, SARIF, attestation) to the pre-feature output in those formats -- the feature is silent in the happy path.
- **FR-015**: The feature MUST NOT introduce any new runtime dependency.

### Key Entities

- **`HandlerResult`**: existing sieve-level result object. Extended additively with an optional `error_class` field.
- **`error_class` enumeration**: strict `Literal["network", "auth", "timeout", "rate_limit", "not_found", "crashed"]` at the code layer (per clarify Q2). Expansion is a code change + release.
- **CheckResult**: the higher-level per-control result the audit driver emits. Also extended additively with `error_class`, populated from the resolving pass's `HandlerResult`.
- **Attestation predicate result entry**: existing per-control entry in the in-toto predicate (`darnit-baseline/attestation/predicate.py`). Extended additively with `error_class` when present.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator running an audit with an expired auth token can identify from the markdown report alone (no debug flags) which specific controls failed due to auth vs which failed against a working environment. Verified by driver-level integration test that mocks a subset of `gh api` calls to return 401 and asserts the report distinguishes.
- **SC-002**: An audit run with zero environmental failures produces byte-for-byte identical markdown / JSON / SARIF output as the pre-feature implementation. Verified by golden-file regression test on a fixture repo with all deterministic controls.
- **SC-003**: An audit whose sieve pipeline hits any `error_class`-triggering condition emits at least one WARN log line at default log level. Verified by test that patches a handler to raise a classified environmental error and inspects captured log output.
- **SC-004**: The attestation predicate for a control that had `error_class = network` contains the `"error_class": "network"` field at the same schema depth as `status`. Verified by generating a predicate from a mocked-failure audit and asserting the JSON shape.
- **SC-005**: The `_apply_cel_expr` post-step does not strip `error_class` under any of its four status-transition cases (PASS+true, PASS+false, FAIL+true, FAIL+false). Verified by unit test parameterized over all four transitions.
- **SC-006**: Adding `error_class` to `HandlerResult` does not break any existing test. Verified by full framework + baseline test suite passing.
- **SC-007**: The feature adds no new runtime import (grep for third-party import additions is empty). Verified by explicit test that greps `pyproject.toml`'s runtime dependency set for the touched files.

## Assumptions

- The feature is implemented additively; no existing field on `HandlerResult` or `CheckResult` is renamed or removed. Legacy consumers see the new field as unknown-but-optional.
- Rate-limit and auth heuristics are GitHub-only for v0 (per clarify Q4), stderr-text-based against `gh` CLI output shape. Perfect classification is out of scope for v0; the fallback is `network` for unclassified subprocess failure and `crashed` for unexpected exceptions. Per-target pattern packs for other tools (git, curl, syft, cosign) are follow-ups triggered by real-audit evidence.
- Log-level bump (DEBUG -> WARN) applies to environmental failures only. Handler-happy-path logging (successful subprocess invocations, cache lookups) stays at DEBUG.
- The attestation predicate change is additive within the v1 predicate schema (matches the pattern feature 025 used to add `authority` per RFC-0001 Stage 1). No predicate version bump.
- The markdown/JSON/SARIF formatter changes are opt-in-by-shape (they inspect whether `error_class` is set; no config flag needed to enable rendering).
- The scope excludes fixing the `_load_merged_stores` DEBUG-only logging path in `tools/audit.py:550-600` -- the survey named it as a related gap but it's about missing-framework context loading, distinct from the sieve-handler failure classification. Treated as a follow-up.

## Dependencies

- Feature 025 / RFC-0001 Stage 1 (`authority` field on `HandlerResult` and result envelopes) -- the same additive-extension pattern is applied here.
- Feature 034 / PR #412 (local-fs and user-local backends) -- not a strict dependency, but the store-side changes from feature 035 and issue #418 (Tier 1 determinism) already ship structural improvements to the same layer this feature extends.
- Determinism companion issues #418 (Tier 1), #420 (remediation atomicity), #421 (LLM reasoning capture) -- Tier 3 (#421) will consume `error_class` in attestation; that consumer wiring lives in #421's scope, not here.

## Out of Scope

- **Retrying failed network calls**. Retry masks nondeterminism without fixing it and adds a whole design conversation about backoff, budgets, and cross-run state. Separate feature.
- **An offline-mode CLI flag**. Also separate.
- **Fixing the `value_if_fail` semantics in the detect pipeline**. PR #417 already handled that case.
- **Reworking `_load_merged_stores` logging** in `tools/audit.py`. Distinct code path; follow-up.
- **Structured error causes beyond the six-value enum**. v0 ships the six; v1+ may add finer buckets (`dns_failure`, `tls_error`, `proxy_blocked`) as real audits surface the need.
- **Non-GitHub target pattern packs** (git, curl, syft, cosign). Per clarify Q4, v0 classifies GitHub-only; other exec targets fall through to `network`. Per-target packs are follow-ups.
- **Machine-readable `error_class` in the human markdown output**. Markdown gets an inline annotation for humans; JSON / SARIF / attestation carry the structured form for machines.
