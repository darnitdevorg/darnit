# Feature Specification: RFC-0001 Stage 1 -- Authority, ActionPlan Protocol, and MCP Loop

**Feature Branch**: `025-rfc0001-stage1`

**Created**: 2026-08-05

**Status**: Draft

**Input**: [RFC-0001 Stage 1](../../docs/rfcs/0001-core-rearchitecture.md#staged-plan). Stage 1 gate verbatim: "Add `authority` to results and handlers; implement the per-phase execution rule; extract `route()` from `cmd_run` into the public ActionPlan protocol; expose the pipeline loop over MCP. Acceptance gate: One reference control (SECURITY.md) runs the full Check/Collect/Remediate loop through the same protocol from both `darnit run` and a coding agent over MCP, with an LLM step demonstrably unable to produce a PASS."

## Clarifications

### Session 2026-08-05

- Q: Where does `HarnessState` live between MCP calls? -> A: Client-owned; every MCP call takes the full `HarnessState` as input and returns the new state. The server is stateless with respect to run state.
- Q: How is `authority` added to attestation output? -> A: Additive field inside the existing `https://openssf.org/baseline/assessment/v1` predicate. Older policy engines ignore the unknown field and continue to load and verify the PASS/FAIL/inconclusive shape unchanged; newer engines inspect authority to reject assertion-backed passes for high-assurance use. No new predicate version is emitted in Stage 1.
- Q: Is the default `LLMStep` implementation (Pydantic AI) a required or optional runtime dependency of `darnit-core`? -> A: Required. LLM-assisted checks are core product functionality; there is no shipping "no-LLM" install tier. `pydantic-ai-slim[anthropic]` (or the equivalent finalized at plan time) installs unconditionally with `darnit-core`. The `LLMStep` Protocol still makes the SDK swappable at code time (single-file replacement), but that swap is a source change, not a user-facing install flag.

## Context

The current pipeline entangles two properties on a single axis (the `VerificationPhase` enum): how expensive a step is and how much authority its output carries. That conflation means the code cannot express "deterministic but unauthoritative" (a repeatable guess), which is precisely the case a compliance tool must not get wrong. In addition, the Check -> Collect -> re-Check -> Remediate loop lives only inline in `cmd_run` (`packages/darnit/src/darnit/cli.py:631-728`); the MCP surface has no access to it, so a coding agent driving Darnit must improvise the loop from one-shot tool calls rather than walking a shared protocol.

Stage 1 lands the safety and structural foundations for both problems:

- **Safety foundation**: every step's output carries an explicit `authority` (`dispositive` | `suggestive` | `asserted`), and the Check-phase execution rule keys on authority rather than on the cost-and-repeatability enum. Only dispositive or asserted steps may conclude a control. An LLM step (necessarily `suggestive`) can attach evidence but can never produce a PASS on its own. This closes a class of false-positive verdicts the current model permits.
- **Structural foundation**: the `route(state)` dispatch that today lives inside `cmd_run` is extracted into a public typed **ActionPlan protocol** whose `next_action` / `submit_result` shape is walkable one step at a time by both the CLI and an external coding agent over MCP. Enforcement is mechanical: the core validates that the result submitted for step N matches step N's declared schema and refuses out-of-order submission.

Stage 1 does not remove functionality. Existing TOML control definitions, CEL evaluation, per-run attestation, the shared-handler cache, the `darnit run` pipeline loop, and the current MCP tool surface all survive; each is re-seated behind explicit contracts. The reference control (SECURITY.md) is the integration proof that these contracts hold end-to-end.

## User Scenarios & Testing *(mandatory)*

### User Story 1 -- Authority prevents LLM-only PASS (Priority: P1)

A maintainer configures a control whose only escalation option is an LLM step (for example: "does the security policy meaningfully cover disclosure?"). The LLM step returns a well-formed "yes, it does" judgment with high self-reported confidence. Darnit records the LLM output as evidence and reports the control as **inconclusive**, not PASS. The maintainer sees an inconclusive result with the LLM's reasoning attached and a call to action ("assert this manually, or escalate to a dispositive step"). No downstream consumer -- attestation, formatter, exit code -- sees a PASS.

**Why this priority**: This is the load-bearing safety property Stage 1 exists to establish. Without it, the LLM step is a lever an adversarial input can pull to manufacture a false compliance claim, and every downstream layer inherits that hazard. The story is priority P1 because no other Stage 1 work is defensible without this property in place.

**Independent Test**: Author a fixture control whose strategy list has one entry -- an LLM step that returns a high-confidence "yes" -- and confirm Darnit reports the control as inconclusive with the LLM output attached as `suggestive` evidence. A regression that reclassifies LLM output as dispositive, or that lets a suggestive result terminate the strategy list, causes this test to fail with a message naming the offending step and its authority.

**Acceptance Scenarios**:

1. **Given** a control with a single LLM-only pass, **When** the audit runs, **Then** the result status is inconclusive (not PASS), the LLM output is present in the evidence with `authority = "suggestive"`, and no attestation is generated for this control as a PASS.
2. **Given** a control whose strategy list is `[LLM_extract (suggestive), file_exists (dispositive)]`, **When** the audit runs and `file_exists` observes the file, **Then** the LLM's earlier suggestive attachment is preserved as evidence AND the control concludes PASS from the dispositive step.
3. **Given** a control whose strategy list ends with only suggestive results, **When** the audit runs, **Then** the result is inconclusive, evidence carries the best candidate, and the reporter surfaces the candidate to a human for confirmation.
4. **Given** a control that produces an ERROR from a dispositive step, **When** the audit runs, **Then** the result status is ERROR (not inconclusive), the strategy list is not consulted for further steps, and the operator sees the failure as a broken measurement rather than an absence of knowledge.

---

### User Story 2 -- ActionPlan protocol replaces inline route() (Priority: P1)

A developer working on the harness driver imports `darnit.core.action_plan` and drives the same Check/Collect/Remediate loop that `darnit run` uses today, one step at a time, from a Python script. The developer sees a typed `ActionPlan` object per step, submits a result under the step's declared schema, and receives the next `ActionPlan` from the same core call. The behavior observed matches what `darnit run` produces on the same repository.

**Why this priority**: The current loop is CLI-private. Until it exists as a public typed contract, every non-CLI consumer (MCP tool, fleet harness, future durable-execution driver) must improvise the loop from scratch, and any two consumers can diverge silently. The extraction is a structural refactor whose scope is bounded: today's `route(state)` becomes tomorrow's `next_action(state)` and today's inline "apply the returned action and re-audit" becomes tomorrow's `submit_result(state, step_id, result)`. Priority P1 because US3 (MCP surface) and US4 (reference-control integration) both depend on this contract existing.

**Independent Test**: Write a Python script that constructs an initial `HarnessState` for the same fixture used by feature 024's `minimal_repo`, calls `next_action` in a loop until it returns None, submits each result via `submit_result`, and asserts the final observable state (exit-code equivalent, printed count breakdown) matches what `darnit run` produces on the same fixture. Divergence between the two paths surfaces as an assertion diff naming the field that drifted.

**Acceptance Scenarios**:

1. **Given** an initial `HarnessState` for a fixture repository, **When** a caller drives `next_action` / `submit_result` in a loop, **Then** the final state's `audit_results`, feedback questions, and context values match those `darnit run` produces on the same fixture within a documented equality contract (results compared by control id and status; feedback questions by set-equality on `(control_id, context_key)`).
2. **Given** a call sequence that submits a result for step N+1 before step N, **When** `submit_result` is invoked, **Then** the call raises a typed `OutOfOrderSubmission` error naming both step ids, and no state transition is applied.
3. **Given** a result whose payload does not match the step's declared result schema, **When** `submit_result` is invoked, **Then** the call raises a typed `ResultSchemaMismatch` error naming the schema field(s) that failed validation, and no state transition is applied.
4. **Given** `darnit run` invoked against the same fixture, **When** the ActionPlan-based script drives the same fixture through the extracted protocol, **Then** the fixture's `test_cmd_run_e2e.py` golden-path assertions still pass against `darnit run` (feature 024 regression baseline is not broken by the extraction).

---

### User Story 3 -- Coding agent walks the loop over MCP (Priority: P1)

A user configures Claude Code (or any MCP-capable coding agent) to talk to a Darnit MCP server. The user asks the agent to audit a project. The agent invokes an MCP tool that returns one `ActionPlan` step, executes the step (or asks the user for confirmation), submits the result via a second MCP tool, and repeats until the loop terminates. The audit produces the same results as `darnit run` would produce locally.

**Why this priority**: This is the "One core, two drivers" premise from the RFC. Without the MCP surface, the "coding agent driver" is a claim without an implementation; the "custom harness driver" (later stages) has no reference for what the agent driver should look like. Priority P1 because the RFC's Stage 1 acceptance gate explicitly requires the loop to run "from both `darnit run` and a coding agent over MCP".

**Independent Test**: An in-process test uses the FastMCP client to invoke the new `run_next_action` / `submit_action_result` tools against the same fixture used by US2. The captured tool sequence produces a final state whose `audit_results` and exit-code equivalent match `darnit run` on the same fixture. The test does not require a real coding agent; the MCP tool surface itself is the contract under test.

**Acceptance Scenarios**:

1. **Given** an MCP client connected to the Darnit MCP server, **When** the client invokes `run_next_action` and receives a step, executes it locally or via a mock, and invokes `submit_action_result` with the result, **Then** subsequent `run_next_action` calls advance the loop and eventually return a terminal-plan marker.
2. **Given** an MCP client that submits an out-of-order or schema-invalid result, **When** the server dispatches, **Then** the tool returns a structured error with the same shape as the direct-call `OutOfOrderSubmission` / `ResultSchemaMismatch`, and no state transition is applied.
3. **Given** an MCP-driven audit and a CLI-driven audit against the same fixture with the same starting context, **When** both complete, **Then** their `audit_results` sets are equal by control id and status; feedback question sets are equal by `(control_id, context_key)`.

---

### User Story 4 -- SECURITY.md reference control integrates all three (Priority: P1)

A user runs Darnit against a repository that lacks a security policy. The audit reports the SECURITY.md control as inconclusive (dispositive `file_exists` observed absence; suggestive `llm_extract` scanned READMEs and proposed pulling contact language from README into a SECURITY.md draft; no assertion recorded). The user invokes the Collect phase (via CLI or via a coding agent over MCP) and confirms a security contact. The Remediate phase generates a SECURITY.md draft with the confirmed contact and opens a PR. The user re-runs the audit; the control now reports PASS from the dispositive `file_exists`, with the earlier LLM suggestion preserved as historical evidence in the attestation but never counted as authority.

**Why this priority**: This is the RFC's stated acceptance gate. Every US1/US2/US3 property must hold true simultaneously against a single realistic control -- otherwise the individual pieces might be correct in isolation but combine into an unsafe or non-composable whole. SECURITY.md is chosen because it exercises all three phases (file check, human input, remediation) at modest cost. Priority P1 because Stage 1 does not close without this integration proof.

**Independent Test**: A fixture repository without SECURITY.md runs Darnit under both the CLI path and the MCP path. Both paths report the control as inconclusive on the first run, both paths correctly attach the LLM suggestion as suggestive evidence without concluding, and both paths, after the same Collect confirmation and Remediate execution, cause the second run to report PASS with the confirmation and PR-diff recorded in evidence. The two paths' `audit_results` are compared by the equality contract from US2 acceptance #1.

**Acceptance Scenarios**:

1. **Given** a fixture repository without SECURITY.md, **When** an audit runs, **Then** the SECURITY.md control reports inconclusive with an `authority = "dispositive"` FAIL from `file_exists` (no such file) OR inconclusive-suggestive candidate from the LLM step (proposed contact) attached but not treated as authority.
2. **Given** the inconclusive result from #1, **When** the user confirms a security contact via Collect, **Then** the confirmation persists to `.project/` with `authority = "asserted"`, and a subsequent Remediate step generates a SECURITY.md with that contact.
3. **Given** the SECURITY.md landed by Remediate, **When** the audit is re-run, **Then** the control reports PASS from the dispositive `file_exists` observation of the created file, and the Evidence set retains the earlier suggestive LLM contribution as historical context but not as authority for the PASS.
4. **Given** the same fixture and same Collect/Remediate inputs, **When** the flow is driven via `darnit run` versus via an MCP client, **Then** the two runs produce equal `audit_results` sets (by control id + status) AND equal Evidence authority breakdowns (each result's `authority` matches across both paths).

---

### Edge Cases

- A control's strategy list contains only an ERROR-producing dispositive step. The result is `ERROR`, not `inconclusive`; execution stops and does not escalate to any suggestive step. Feature 022's six-status typing already accommodates this.
- An LLM step returns a well-formed JSON judgment but the confidence is very low. Because Check does not consider confidence at all, the outcome is unchanged from a high-confidence LLM output: `suggestive` evidence attached, does not conclude. Confidence at Check phase is not a decision input.
- A caller submits a valid result for step N+1, then a valid result for step N, then a valid result for step N+2. The N+1 submission fails first (out-of-order); the N submission succeeds; the N+2 submission succeeds. State transitions are per-step and independent -- one failed submission does not corrupt others.
- The same fixture is driven through both CLI and MCP within the same process (unusual but possible in tests). Each path constructs its own `HarnessState`; there is no shared mutable state between the two, and the equality contract compares final states, not intermediate ones.
- A step declares `authority = "asserted"` but ships without a recorded human confirmation. This is a schema violation caught at load time (not run time), because "asserted" is by definition a human action; a Python function cannot claim it.
- The extracted ActionPlan protocol lands but `cmd_run` still exists. The two must produce identical observable behavior on the feature-024 fixtures; deviations are US2 failures, not "cmd_run bugs".

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `CheckResult` (defined in `packages/darnit/src/darnit/sieve/models.py`) MUST carry an `authority` field of type `Literal["dispositive", "suggestive", "asserted"]`. The TypedDict field is `NotRequired` for back-compat with pre-Stage-1 serialized results, but the runner MUST NOT treat a result whose `authority` is absent as authority for a control's conclusion: any authority-less result is treated as `suggestive` and rejected from `CONCLUDE_PASS`/`CONCLUDE_FAIL` dispositions. In effect the safety property ("no PASS without explicit authority") is enforced by the runner check, not by the TypedDict declaration. A test MUST assert that a synthetic `CheckResult` lacking `authority` cannot cause `CONCLUDE_PASS` or `CONCLUDE_FAIL` regardless of `status`.
- **FR-002**: `HandlerResult` MUST carry the same `authority` field with the same domain. Handlers MUST return a result whose authority is one of the three declared values or the loader/registration rejects the handler.
- **FR-003**: The strategy-list runner (evolved from today's per-phase pass loop in `sieve/orchestrator.py`) MUST implement the per-phase Check execution rule: (a) a `dispositive` PASS/FAIL is terminal; (b) a `suggestive` result attaches evidence and does NOT terminate the list; (c) an `ERROR` from any step is terminal AND does not escalate to a next step; (d) if the list is exhausted with only `suggestive` results, the control status is `inconclusive` with the best candidate attached; (e) a step of kind `manual` is terminal.
- **FR-004**: The runner MUST NOT allow a `suggestive` result to conclude a control PASS or FAIL. A test asserting this must fail if a future edit collapses the authority check.
- **FR-005**: Attestation output MUST include the `authority` for each result and MUST distinguish PASS-from-dispositive from PASS-from-asserted at read time. The field is added as an additive optional field inside the existing `https://openssf.org/baseline/assessment/v1` predicate; the predicate type string does NOT change in Stage 1. A test MUST assert that an attestation produced pre-Stage-1 (or by a downstream reader that ignores unknown fields) continues to load and verify unchanged. A separate test MUST assert that a Stage-1-aware reader can extract the `authority` value and reject a PASS whose authority is not in an accept-list (e.g., a policy engine configured to accept only `dispositive` passes rejects an `asserted` pass).
- **FR-006**: A new module `darnit.core.action_plan` (or equivalent path chosen at plan time) MUST expose an `ActionPlan` type describing a single step (id, integration name, params schema, declared result schema) and functions `next_action(state) -> ActionPlan | None` and `submit_result(state, step_id, result) -> HarnessState`.
- **FR-007**: `next_action` and `submit_result` MUST be pure functions with respect to the `HarnessState` argument (return a new state; do not mutate the input in place). The state type MUST be serializable so that a future durable-execution driver can persist it without additional adapter work.
- **FR-008**: `submit_result` MUST raise a typed `OutOfOrderSubmission` when the caller submits for a step that is not the currently expected one. The error MUST name both the expected step id and the submitted step id.
- **FR-009**: `submit_result` MUST validate the submitted result against the step's declared result schema and raise a typed `ResultSchemaMismatch` naming the offending field(s) on validation failure. No state transition may occur on validation failure.
- **FR-010**: `cmd_run` MUST be refactored to consume the new ActionPlan protocol internally. The observable output pinned by feature 024's `test_cmd_run_e2e.py` MUST continue to pass without modification during and after the refactor. If any assertion needs to change, that is a contract change and MUST be handled per feature 024's contract-update procedure.
- **FR-011**: The MCP server MUST expose tools `run_next_action(state) -> ActionPlan | None` and `submit_action_result(state, step_id, result) -> HarnessState` (names finalizable at plan time; MUST be discoverable via `list_tools` and follow existing MCP tool-registration conventions). Both tools MUST take the full `HarnessState` as an input parameter and return the new state on `submit_action_result`; the server MUST NOT retain per-run state between calls. Consequences: two agents driving two separate audits do not share server state; a single agent driving the same audit MUST round-trip the state on every call.
- **FR-012**: The MCP surface's error responses for out-of-order submission and schema mismatch MUST carry the same information as the direct-call typed errors -- either as structured error payloads or as MCP protocol errors that clients can inspect. A test asserting the equivalence must exist.
- **FR-013**: A reference control for SECURITY.md MUST land in `darnit-baseline` (or a comparable framework the tests use) with a strategy list that includes at minimum: a `dispositive` `file_exists` step, a `suggestive` `llm_extract` step, and a Collect step that persists a confirmed security contact to `.project/`. The Remediate step MUST generate a SECURITY.md draft that includes the confirmed contact.
- **FR-014**: The SECURITY.md control MUST be exercised end-to-end from BOTH `darnit run` and the MCP tool surface, with test coverage asserting the two paths produce equal `audit_results` (by control id + status) and equal per-result authority breakdowns.
- **FR-015**: The existing legacy phase-keyed TOML tables (`deterministic = [...]`, `llm = [...]`, etc.) MUST continue to load through a compatibility path that translates them into the new strategy-list shape. A round-trip test MUST verify the translation is lossless (parse -> translate -> re-serialize -> re-parse produces identical semantics).
- **FR-016**: All new production code paths and MCP tool paths MUST be exercised by tests in the existing pytest suites (`tests/darnit/`, `tests/darnit_baseline/`) under the same discovery configuration; no new CI job or workflow file MUST be added by this feature.
- **FR-017**: New source files MUST be ASCII-only, matching the project convention (feature 024 FR-012 established this).
- **FR-018**: The change MUST NOT delete `cmd_run` or `route()`. Both continue to exist during and after this stage, per the RFC's "no stage deletes functionality" commitment. `route()` becomes a thin adapter that delegates to `next_action`.

### Key Entities

- **Authority**: A `Literal["dispositive", "suggestive", "asserted"]` classification attached to every step definition, every handler return value, and every result carried through the pipeline. `dispositive` results settle a control; `suggestive` results attach as evidence and never conclude; `asserted` results come from human confirmation only.
- **ActionPlan**: A serializable object naming one step of the pipeline, its integration, its parameters, its declared result schema, and its position in the strategy list. Emitted by `next_action`; the shape a caller receives to decide "should I execute this step, ask a human, or stop."
- **HarnessState**: An evolution of today's `AuditState` (see feature 022) with the fields required to walk the loop step-by-step: current step position, pending steps, submitted results, accumulated evidence with authority breakdown, feedback questions and their status. Client-owned in the MCP shape: every tool call takes the state as input and returns the new state; the server retains no per-run state. Must be serializable (implication: the MCP wire format is the durable form; a future durable-execution driver reuses the same shape for persistence).
- **OutOfOrderSubmission / ResultSchemaMismatch**: Typed errors raised by `submit_result` on protocol violations. They exist to make agent misuse mechanically detectable rather than silently accepted.
- **SECURITY.md reference control**: A concrete control definition in the baseline framework whose strategy list includes at least one `dispositive` step, one `suggestive` step, one Collect step, and one Remediate step. It is the vehicle for the Stage 1 acceptance gate.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A test asserting that an LLM-only strategy list cannot produce a PASS exists and passes. If a future edit lets `suggestive` results conclude a control, this test fails with a message naming the offending step and its authority. (Load-bearing safety property; must be verifiable in CI without any special environment.)
- **SC-002**: A test drives the ActionPlan protocol directly from Python and asserts the final observable state equals `darnit run`'s output on the same fixture, per the equality contract in US2 acceptance #1. Divergence surfaces as a named assertion failure identifying the drifted field.
- **SC-003**: A test drives the loop through the MCP tool surface and asserts the final observable state equals both `darnit run`'s output and the direct-ActionPlan output on the same fixture. Three-way equality is checked.
- **SC-004**: The SECURITY.md control's full Check -> Collect -> Remediate -> re-Check flow completes end-to-end from BOTH `darnit run` and the MCP tool surface, and both paths produce the same second-run PASS with the same Evidence authority breakdown.
- **SC-005**: The feature-024 `tests/darnit/cli/test_cmd_run_e2e.py` suite continues to pass without modification during and after the `cmd_run` refactor. Any needed contract change is handled through the documented contract-update procedure (spec 024 quickstart) and noted in the PR description.
- **SC-006**: Legacy phase-keyed TOML (`deterministic = [...]`, `llm = [...]`) continues to load and produce identical audit results to the pre-Stage-1 codebase. A round-trip lossless-translation test exists and passes.
- **SC-007**: The `authority` field is present in every attestation entry a Stage 1 audit produces. A test reads a generated attestation and confirms every result has an authority value in the declared domain.
- **SC-008**: An adversarial-input fixture -- a repository whose README contains an obvious prompt-injection payload asking the LLM to conclude a control PASS -- runs through the audit and the affected control's status is `inconclusive`, not PASS. The LLM's output IS captured as suggestive evidence for review, but never treated as authority. (This is the safety property from RFC "Adversarial inputs" section; verified pre-fleet-mode as insurance against later regression.)

## Assumptions

- **A1**: RFC-0001 constitution amendment 1.3.0 is in effect (Stage 0 satisfied). Steps may propose values for user-judgment keys but may never conclude them without human confirmation.
- **A2**: Feature 022's typed `CheckResult` (`list[CheckResult]` for `audit_results`, six-status `Literal`) is in place. Stage 1 extends `CheckResult` with the `authority` field; the extension is a schema evolution, not a rewrite.
- **A3**: Feature 024's E2E baseline for `cmd_run` is in place and passes on `main`. The Stage 1 refactor must not break these tests; if any test needs updating, that is a deliberate contract change subject to review.
- **A4**: The MCP server infrastructure (FastMCP) is functional and supports the new tools; no new MCP framework is introduced by this feature.
- **A5**: Pydantic AI is the default `LLMStep` implementation and is a REQUIRED runtime dependency of `darnit-core`. LLM-assisted checks are core product functionality; there is no "no-LLM" install shape. The `LLMStep` Protocol still makes the SDK swappable at code time (replacing Pydantic AI with LangChain or the raw SDK is a single-file source change), but the strategy-list runner code MUST NOT import a specific LLM SDK directly -- the coupling belongs behind the `LLMStep` seam so the swap remains one file.
- **A6**: The reference SECURITY.md control lives in `darnit-baseline`. If the existing baseline SECURITY-related controls are already close to the RFC's strategy-list shape, the change may adapt them rather than adding a parallel control; that is a plan-time decision.
- **A7**: The Collect phase persistence mechanism (writes to `.project/`) already exists (feature 018 shipped it as `save_context_values`). Stage 1 uses this mechanism; adding new persistence semantics is out of scope.
- **A8**: The auto-merge / denylist / prior-state capture requirements from the RFC's "Remediation trust boundary" section are Stage 3 concerns, not Stage 1. This feature ships the strategy-list runner and the SECURITY.md control's basic Remediate step (draft-a-file, open-a-PR), not the auto-merge machinery.

## Out of Scope

- Stage 2 work: shrinking `darnit-core`, defining the Integration contract, `NormalizedFindings`, importers for Scorecard/SARIF/OSV, derived cache keys, cost/safety invariant splits.
- Stage 3 work: `darnit-agent` packaging, the deduped manual queue, confirmation persistence-and-expiry semantics (Stage 1 uses the existing simple persist-forever behavior), remediation denylist enforcement, auto-merge gating, prior-state capture.
- Durable-execution backend (Temporal-style). `HarnessState` must be serializable, but no durable store is wired.
- Replacing Pydantic AI with a different `LLMStep` implementation. That is a single-file change made when a concrete need arises.
- New MCP transport (stdio / SSE / HTTP) beyond what the current server supports.
- Redoing attestation predicate types. Baseline's `https://openssf.org/baseline/assessment/v1` predicate continues to be emitted; the `authority` field is added inside its existing structure without changing the predicate type.
- Composing multiple frameworks in one audit (spec 013 territory). Stage 1 lands in a single-framework flow.
- Fitness gate demo (Stage 2 acceptance). Deleting Python check logic in favor of TOML+integrations is measured in Stage 2; Stage 1 lays the substrate.
