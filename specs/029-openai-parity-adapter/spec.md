# Feature Specification: OpenAI Tier 2 Parity Adapter

**Feature Branch**: `029-openai-parity-adapter`

**Created**: 2026-08-10

**Status**: Draft

**Input**: User description: "Add an OpenAI SDK adapter to feature 028's Tier 2 parity check so an OpenAI-based coding-assistant invocation can be diffed against raw MCP tool output alongside the existing Claude Agent SDK path (issue #368)."

## Clarifications

### Session 2026-08-10

- Q: Which OpenAI API surface does the adapter use? -> A: OpenAI Chat Completions API with `tools=[...]` and a hand-rolled tool-call loop. Stateless per invocation -- no server-side thread/assistant lifecycle to manage; the turn cap is a plain message count. Symmetric with feature 028's Claude adapter (also stateless per-fixture) so both adapters slot cleanly into the same shared `SkillInvocationBackend` Protocol.
- Q: How are backends registered with the runner? -> A: Simple factory dict `BACKEND_REGISTRY = {"claude_agent_sdk": ..., "openai": ...}` in a shared module. Runner reads via string lookup; tests inject a `MockBackend` by monkey-patching the registry or by passing an explicit `backends=` dict. TEST-ONLY seam -- no entry-point discovery. Matches the fact that no third-party outside darnit's own test suite extends this Protocol (unlike feature 027's `QuestionResolver`, which is product-facing).
- Q: What outcome does the runner report when the turn cap is exhausted without a final message? -> A: New distinct outcome `turn_cap_exhausted` with exit code `5`. Diagnostically separate from `unparseable` (model summarized but the parser missed the format) and from `per_control_disagree` (model summarized fine, but disagreed with the tool). Maps to a different fix: adjust prompt or raise cap, not a parser fix. The set of documented exit codes is now: 0 success, 1 disagreement, 2 unparseable, 3 setup, 4 rate-limit, 5 turn-cap-exhausted.
- Q: How is the default OpenAI model chosen and updated? -> A: Pin a specific model string with a version suffix (e.g., `gpt-4o-2024-08-06`) as the default in `parity-tier2-openai.yml`. Reproducibility is load-bearing for a diagnostic: if OpenAI silently reinterprets what a moving alias means and the parity test's baseline shifts, we cannot distinguish "model changed" from "darnit tool changed." Bumping requires a PR editing the workflow -- explicit, reviewable, correlatable with any subsequent test result changes. A workflow input overrides the pinned default for one-off investigations.
- Q: Where does the `NoopBackend` used to verify SC-005 and SC-007 live? -> A: Test-only fixture at `tests/darnit/parity/tier2/backends/noop.py`. Concrete class satisfying the Protocol; imported by conformance and extensibility tests. Not shipped as a third-party template (matches Q2 -- this is a test-only seam, not a product-facing Protocol). The Protocol's shape is documented in `contracts/skill-invocation-backend-protocol.md`; anyone writing a real backend reads that contract.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Maintainer runs the OpenAI Tier 2 parity check (Priority: P1)

An authorized maintainer manually dispatches an OpenAI Tier 2 workflow to see whether an OpenAI-based coding-assistant invocation (using the same skill-shaped system prompt as the Claude path) preserves the darnit tool's raw per-control status in its user-facing summary. The workflow captures raw MCP tool JSON per fixture, invokes an OpenAI model via the OpenAI SDK with the darnit MCP tools registered as function-calling tools, parses the final assistant message, and diffs the two. Failure surfaces per-control drift as an artifact.

**Why this priority**: This is the direct closer for issue #368. Feature 028's Tier 2 covers Claude Code + Claude models. Users of darnit through OpenAI-backed coding assistants (e.g., Cursor with GPT-4, ChatGPT-in-IDE integrations, any custom OpenAI agent) deserve the same drift-detection surface. Without this, a silent WARN-to-PASS reclassification by an OpenAI-based agent would go undetected while the Claude path stays honest.

**Independent Test**: An authorized maintainer dispatches `parity-tier2-openai.yml` with `fixture_glob="*"`. The workflow pauses at the reviewer gate, is approved, runs to completion, and either exits 0 (skill agrees with tool) or exits 1 with a per-fixture diff artifact showing which controls the OpenAI assistant reclassified.

**Acceptance Scenarios**:

1. **Given** the OpenAI-based invocation reports every control's status identically to the raw tool output, **When** the workflow runs, **Then** it exits 0 and the summary line shows "0 drifts, 0 unparseable."
2. **Given** the OpenAI-based invocation silently reclassifies at least one control's status, **When** the workflow runs, **Then** it exits 1 with a `diff_report.md` naming the offending controls; both raw artifacts (tool JSON + OpenAI final message) are uploaded.
3. **Given** the OpenAI-based invocation's final message cannot be parsed for per-control claims, **When** the workflow runs, **Then** it exits 2 (a distinct failure class from disagreement); the raw final message is uploaded so a maintainer can inspect the format the parser missed.
4. **Given** `OPENAI_API_KEY` is not configured on the `parity-tier2-openai` GitHub Environment, **When** an authorized maintainer approves the dispatch, **Then** the workflow fails fast with a clear setup error naming the missing key; no other steps proceed.

---

### User Story 2 - Author of a future provider adapter reuses the seam (Priority: P2)

A future maintainer wants to add a Gemini or xAI Tier 2 check. They read the shared Protocol definition in the darnit parity test suite, write a new backend adapter satisfying the Protocol, register it with the runner, and add a new workflow file. No changes to the shared parser, differ, artifact writer, runner CLI, or fixture corpus are required.

**Why this priority**: Feature 028 shipped a per-provider Tier 2 by wiring the Claude SDK directly into `run.py`. Adding OpenAI as a second inline path would make the runner harder to extend and force each future provider to duplicate scaffolding. Extracting a `SkillInvocationBackend` Protocol during feature 029 pays down the debt now, when we have two concrete examples to compare against, before it multiplies.

**Independent Test**: A stub `NoopBackend` implementation lives under `tests/darnit/parity/tier2/backends/` and is used by the runner to verify the seam's shape (accepts a fixture, returns a `SkillInvocationResult`, raises `SetupError` on missing env). Adding the backend requires no edits to `run.py`, `diff.py`, `artifact_writer.py`, `skill_markdown_parser.py`, or any fixture.

**Acceptance Scenarios**:

1. **Given** the Protocol shape is documented in `contracts/skill-invocation-backend-protocol.md`, **When** a third-party author writes a backend that implements the Protocol, **Then** they can register it with the runner (via constructor injection or a factory dict) without editing any file in `tests/darnit/parity/tier2/` other than to add their own module.
2. **Given** two registered backends (`claude_agent_sdk`, `openai`), **When** the runner is invoked with `--backend openai`, **Then** only the OpenAI backend is used; the Claude backend is not loaded.

---

### User Story 3 - Aggregate provider drift comparison (Priority: P3)

A maintainer wants to know, across a single fixture, whether the Claude-based and OpenAI-based skill invocations agree with EACH OTHER (not just with the raw tool). This surfaces provider-specific bias: if Claude reads the tool as WARN and OpenAI reads it as PASS on the same fixture, that is a signal worth capturing even if neither is technically "wrong" against the tool.

**Why this priority**: Genuinely useful but not urgent for closing #368. The MVP of feature 029 answers "does OpenAI drift from tool?" for each fixture individually. Cross-provider drift is a follow-up analysis a maintainer can perform manually on the two workflows' artifacts. Priority 3 because automating it adds workflow complexity for a nice-to-have report.

**Independent Test**: Given artifact bundles from both a Claude Tier 2 dispatch and an OpenAI Tier 2 dispatch on the same commit, a maintainer can run a local script that diffs the two providers' final messages for the same fixture and reports any control-level status mismatch between them. Not part of any CI job.

**Acceptance Scenarios**:

1. **Given** two artifact bundles for the same commit, **When** the maintainer runs the aggregate script, **Then** it produces a Markdown table listing per-control (Claude status, OpenAI status, disagreement flag).

---

### Edge Cases

- **OpenAI model + system prompt cannot invoke the darnit MCP tool directly** (OpenAI does not speak MCP protocol): the adapter MUST provide a function-calling shim that translates OpenAI tool calls to direct Python invocations of `audit_openssf_baseline` and returns the tool's JSON output back into the assistant's context. The adapter is not "invoking the actual MCP protocol" -- it's simulating a coding-assistant environment where the model can call darnit's audit function.
- **OpenAI model refuses to run the audit or returns a "safety-refused" message**: the parser produces `parseable=False`; the workflow exits 2 with the raw message in the artifact so a maintainer can inspect why.
- **OpenAI rate limit hit mid-run**: capture partial results; fail with a clear "rate limited" message per fixture; do not auto-retry. Same policy as feature 028's Tier 2.
- **`OPENAI_API_KEY` present but no `ANTHROPIC_API_KEY`**: OpenAI Tier 2 runs cleanly. It does NOT need Anthropic credentials. Similarly, Claude Tier 2 does not need OpenAI credentials. The two workflows are independent.
- **OpenAI SDK version bump changes response shape**: the adapter isolates SDK-specific access; a version bump requires updating only the OpenAI adapter, not the runner or shared parser.
- **Model-name defaulting**: OpenAI's model landscape (`gpt-4o`, `gpt-5`, etc.) evolves. The spec fixes a PINNED, VERSION-SUFFIXED model string (e.g., `gpt-4o-2024-08-06`) as the default in the workflow YAML. Reproducibility is load-bearing: if OpenAI silently reinterprets a moving alias and the parity baseline shifts, we cannot distinguish "model changed" from "darnit tool changed." Bumping the pinned default requires a PR editing the workflow. A workflow input overrides the pinned default for one-off investigations.
- **Turn cap reached without final message**: distinct outcome `turn_cap_exhausted` (exit 5). Different diagnostic than `unparseable` (exit 2) or `per_control_disagree` (exit 1). Maps to a different fix: adjust prompt / raise cap, not a parser fix. See FR-010.
- **Unauthorized dispatch attempt**: as with feature 028's Claude Tier 2, the `parity-tier2-openai` Environment is reviewer-gated. No API budget is consumed until an authorized reviewer approves.
- **OpenAI response streams "function_call" but the tool implementation returns an error**: adapter catches, injects an error response into the assistant's context, lets the model decide what to do next; the final assistant message is what the parser reads. If the model gracefully reports the error, that's a fine outcome (parser sees "audit failed to run" and Tier 2 marks the fixture as errored, not a drift).
- **Multiple assistant turns**: the adapter caps at a maximum turn count (same policy as feature 028's Claude client, default 20). A runaway conversation cannot burn arbitrary budget.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide an OpenAI-based Tier 2 parity backend that, for a given fixture, invokes an OpenAI model via the Chat Completions API with `tools=[...]` function-calling, executes tool calls in a hand-rolled loop, captures the final assistant message, and returns a `SkillInvocationResult`-shaped value analogous to feature 028's Claude backend. The backend is STATELESS per invocation: no persistent thread/assistant objects are created; the turn cap is enforced as a message count.
- **FR-002**: The backend MUST use the OpenAI Python SDK (available on PyPI). It is a TEST-ONLY dependency; no darnit product package gains a runtime dep on it.
- **FR-003**: The system MUST define a `SkillInvocationBackend` Protocol shared across all Tier 2 provider adapters. Both the existing Claude adapter (feature 028) and the new OpenAI adapter MUST conform to it. Future adapters (Gemini, xAI, self-hosted) can conform without editing the shared runner, differ, parser, or artifact writer.
- **FR-004**: The runner (`tests/darnit/parity/tier2/run.py`) MUST accept a `--backend <name>` CLI flag defaulting to `claude_agent_sdk` (preserves feature 028 behavior). Values `claude_agent_sdk` and `openai` are supported in this feature; unknown values fail with a clear error naming the supported set. Backend lookup uses a `BACKEND_REGISTRY` dict in a shared module (`tests/darnit/parity/tier2/backends/__init__.py`); tests inject a `MockBackend` by monkey-patching the registry or by passing an explicit `backends=` dict to the runner (no entry-point discovery, since this is a test-only Protocol seam).
- **FR-005**: The system MUST provide a separate GitHub Actions workflow file `.github/workflows/parity-tier2-openai.yml` that is manual-dispatch only, uses a distinct GitHub Environment named `parity-tier2-openai`, and reads `OPENAI_API_KEY` (not `ANTHROPIC_API_KEY`) from that Environment's secrets. The Claude Tier 2 workflow from feature 028 remains unchanged.
- **FR-006**: The `parity-tier2-openai` Environment MUST be configured with a required-reviewer list. Same governance model as feature 028's `parity-tier2` Environment.
- **FR-007**: `OPENAI_API_KEY` MUST NOT appear in any workflow file other than `parity-tier2-openai.yml`. Verifiable by iterating `.github/workflows/*.yml` and asserting the key literal appears only in the OpenAI workflow file. Mirror of feature 028's SC-005a for the Anthropic key.
- **FR-008**: When `OPENAI_API_KEY` is absent, the OpenAI backend MUST fail fast with a clear setup error naming the missing key. Silent skip is forbidden.
- **FR-009**: The OpenAI adapter MUST NOT modify the `/darnit-audit` skill's prompt snapshot committed by feature 028. It uses the SAME snapshot (adapted for OpenAI's tool-call format if the SDK requires it) so the two Tier 2 paths are testing the same coding-assistant behavior on different providers.
- **FR-010**: The OpenAI adapter MUST cap the assistant's turn count via an explicit `max_turns` value (default 20, configurable via workflow input) so a runaway conversation cannot burn arbitrary budget. When the cap is reached before the model emits a final text message, the runner MUST report the outcome as `turn_cap_exhausted` with exit code `5` -- distinct from `unparseable` (exit 2) and `per_control_disagree` (exit 1). The full documented exit-code set for the OpenAI backend is: `0` success, `1` disagreement, `2` unparseable, `3` setup, `4` rate-limit, `5` turn-cap-exhausted.
- **FR-011**: Per-control status disagreement between the OpenAI final assistant message and the raw MCP tool output is a HARD failure regardless of authority level. The OpenAI model has no license to reinterpret the tool's verdicts, same as the Claude path in feature 028.
- **FR-012**: The runner MUST support `--dry-run` for the OpenAI backend, same as for the Claude backend, so the OpenAI code path is offline-testable via a canned response.
- **FR-013**: Fixture corpus is REUSED from feature 028. No fixture changes are required by this feature. Adding fixtures happens by editing the fixtures directory; both providers automatically pick them up.
- **FR-014**: The Tier 2 skill Markdown parser is REUSED from feature 028. If the OpenAI adapter's final message format matches the parser's regex heuristics, existing patterns apply. If it does not, the failure class is "skill output unparseable" (distinct from "skill and tool disagree"), same as feature 028's FR-006a. No parser fork.
- **FR-015**: The workflow MUST perform a preflight audit log (actor + SHA + fixture_glob + selected backend) BEFORE consuming `OPENAI_API_KEY`, so post-hoc cost attribution works. Mirror of feature 028's T2-7/T2-8.
- **FR-016**: The parity test suite MUST NOT modify any darnit product package as a side effect of this feature. Enforced mechanically by the `test_no_product_changes.py` guard added in feature 028 (which already covers `packages/*/src/`).
- **FR-017**: This feature MUST close issue #368 when merged. Follow-up provider adapters (Gemini, xAI, self-hosted) are tracked as separate issues after merge; those are NOT in scope for this feature.

### Key Entities

- **SkillInvocationBackend**: A Protocol that any provider adapter satisfies. Exposes a stable identifier (`name: str`), an async `invoke(fixture_dir) -> SkillInvocationResult` method, and a `check_env()` classmethod (or equivalent) that fails fast when the provider's credentials are absent. The Claude Agent SDK adapter from feature 028 is refactored to satisfy this Protocol; the OpenAI adapter is a new implementation.
- **OpenAIBackend**: The concrete implementation of `SkillInvocationBackend` that wraps the OpenAI SDK. Uses the shared skill prompt snapshot as the system prompt; registers the darnit MCP tools as OpenAI function-callable tools; loops on tool calls until the assistant emits a final text message or the turn cap is reached.
- **BackendRegistry**: A module-level dict `BACKEND_REGISTRY = {"claude_agent_sdk": ..., "openai": ...}` in `tests/darnit/parity/tier2/backends/__init__.py`. Tests inject a `MockBackend` or `NoopBackend` (see below) by monkey-patching the dict or passing an explicit `backends=` dict to the runner. Not a Protocol-with-entry-points -- this is a test-only seam.
- **NoopBackend**: Test-only fixture at `tests/darnit/parity/tier2/backends/noop.py`. A concrete class satisfying the `SkillInvocationBackend` Protocol; used by conformance tests (SC-005) and extensibility tests (SC-007). NOT shipped as a "how to write a backend" template -- a real backend author reads `contracts/skill-invocation-backend-protocol.md` instead.
- **`parity-tier2-openai` Environment**: A GitHub Actions Environment with a required-reviewer list and `OPENAI_API_KEY` at the Environment level. Distinct from feature 028's `parity-tier2` Environment (which holds `ANTHROPIC_API_KEY`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A single command dispatches the OpenAI Tier 2 workflow, waits for reviewer approval, runs against the fixture corpus, and produces an artifact bundle with per-fixture `diff_report.md`, `mcp_tool_result.json`, and `openai_final_message.md`. Verified end-to-end by an authorized maintainer.
- **SC-002**: `OPENAI_API_KEY` never appears in any workflow file other than `.github/workflows/parity-tier2-openai.yml`. Verified by an automated test that iterates `.github/workflows/*.yml` and asserts the count is exactly 1.
- **SC-003**: A hand-built OpenAI-style final message reclassifying a WARN control as PASS is caught by the diff, regardless of the control's authority level. Verified by an adversarial test that mocks the OpenAI backend and asserts the diff outcome is `per_control_disagree`.
- **SC-004**: Missing `OPENAI_API_KEY` causes the runner to exit with a documented setup-error exit code (`3`) in under 2 seconds. Verified by a subprocess test with the env var stripped.
- **SC-005**: The `SkillInvocationBackend` Protocol is satisfied by both the refactored Claude adapter AND the new OpenAI adapter. A third `NoopBackend` used only in tests also satisfies it. Verified by `isinstance` checks against the Protocol.
- **SC-006**: The parity test suite adds NO runtime dependency to `packages/darnit/pyproject.toml` or `packages/darnit-baseline/pyproject.toml`. The OpenAI SDK is added to the workspace dev group only. Verified by a diff of the two files' dependency lists pre- and post-feature.
- **SC-007**: Adding a new backend (e.g., a scripted `GeminiBackend`) does NOT require modifying `run.py`, `diff.py`, `skill_markdown_parser.py`, `artifact_writer.py`, or any fixture. Verified by adding a `MockGeminiBackend` in the tests and asserting registration + invocation succeed without any edit to those files.
- **SC-008**: An issue #368 status check MUST show "Closed" within one working day of this feature's PR merging. Manual verification.
- **SC-009**: The OpenAI Tier 2 workflow's execution wall-clock time per fixture is bounded by the assistant's turn cap (default 20 turns), the per-turn OpenAI latency (typically 5-30 seconds), and the fixture's audit cost. A full corpus run (4-6 fixtures) SHOULD complete in under 30 minutes. Verified by measuring one production dispatch after merge.
- **SC-010**: The default OpenAI model is a PINNED, VERSION-SUFFIXED string in `parity-tier2-openai.yml`. Verified by a workflow-config test that greps the workflow for the model input's default and asserts it matches the pattern `<model>-<YYYY>-<MM>-<DD>` OR another explicit versioned form. A moving alias (e.g., `gpt-4o` without suffix) fails the test.
- **SC-011**: The `turn_cap_exhausted` outcome is caught by the runner and produces exit code `5` with a documented `diff_report.md` naming the offending fixture. Verified by an adversarial test that mocks the OpenAI backend to always return a tool call (never a text message), runs the runner, and asserts the exit code + report shape.

## Assumptions

- Feature 028 is either merged or its branch is used as this feature's base. This feature builds on 028's Tier 2 machinery -- the shared parser, differ, artifact writer, runner CLI, and workflow shape are prerequisites.
- The OpenAI Python SDK is a reputable, publicly-available Python package on PyPI. It becomes a test-only workspace dev-group dep. If the SDK's install path is more complex (e.g., requires build-from-source), that is a plan-phase problem, not a spec-phase one.
- OpenAI's Assistants / Chat Completions API supports function-calling with the fine-grained control needed to loop over tool invocations, capture the final assistant message, and cap turn count. If a particular API surface is more amenable than another, that is a plan-phase decision.
- The `/darnit-audit` skill's system prompt snapshot from feature 028 is provider-neutral enough that OpenAI can consume it. If OpenAI's tool-call syntax requires prompt adjustments distinct from Claude's, the adapter documents those differences via a small transformation function on top of the shared snapshot -- NOT by forking the snapshot.
- Governance-wise, the OpenAI API key belongs to a specific company (same as the Anthropic key situation from feature 028). Manual-dispatch-only is preserved. Scheduled cadence is a follow-up (tracked by issue #369 for the Claude path; a sibling follow-up covers OpenAI).
- The parity test suite does not itself decide "which provider is correct." All three (Claude Tier 2, OpenAI Tier 2, raw tool) can disagree; each disagreement is a separate finding. The diagnostic value is knowing WHICH pair disagrees on WHICH control -- fixing the disagreement is a separate feature.
- Aggregate reporting across providers (US3) is out of scope for the MVP. A follow-up feature or a maintainer-run local script handles it.
- The OpenAI adapter simulates a coding-assistant environment (system prompt + tool-calling loop). It is NOT a full "MCP over OpenAI" bridge. The purpose is measuring whether an OpenAI-based coding-assistant style invocation preserves tool verdicts, not building a general-purpose MCP-to-OpenAI shim.
- The default model at snapshot time is whichever OpenAI model is the current recommended default for tool-calling agents. The exact string is captured in the workflow YAML AND is a workflow input, so a maintainer can dispatch against a specific model in an investigation without editing YAML.
- Follow-up provider adapters (Gemini, xAI, self-hosted) are explicitly out of scope. Feature 029 delivers the Protocol seam + OpenAI as the first non-Claude backend. Adding a third provider is a new feature that reuses the Protocol.
