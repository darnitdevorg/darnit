# Feature Specification: `darnit-harness` -- End-to-End Audit Driver with LLM Dispatch

**Feature Branch**: `026-darnit-harness`

**Created**: 2026-08-05

**Status**: Draft

**Input**: "Let's make sure we have something actually deliverable here. I want a harness and that's what I want delivered."

## Clarifications

### Session 2026-08-05

- Q: Where does the harness look for pre-declared context answers? -> A: Auto-discover `.project/project.yaml` in the target repo (reuses feature 018's persistence path so a confirmation captured via the coding-agent MCP flow is picked up automatically by a later harness run); `--answers <path>` flag supplements or overrides. IMPORTANT extension: answer sources MUST be designed as a pluggable interface, not a hardcoded file-reader. MVP ships file-based (auto-discovery + `--answers` flag), but the seam MUST accommodate future adapters that read from non-file sources -- email replies, GitHub issue comments, Slack bot responses, ticketing systems, etc. This makes deferred-answer collection (fleet operators sending a batch of questions to their team via email/issues and consuming responses on the next run) a natural extension rather than a redesign.
- Q: How does the harness report progress during long audits? -> A: Structured progress lines to stderr per-control transition, following common CLI/logging output patterns (Python stdlib logging conventions -- the format darnit already uses across its other subcommands). One line per control as it starts / completes / dispatches an LLM step, using the existing `INFO: message` / `WARNING: message` shape so a CI operator parsing logs sees familiar output. `[N/M]` progress counters. Stdout stays clean and reserved for the final report; stderr carries all progress + the exit-summary line (FR-009).
- Q: How is the harness invoked? -> A: New subcommand on the existing `darnit` CLI: `darnit harness <repo-path>`. Ships in `darnit-core` (same package as `darnit audit` / `darnit run` / `darnit serve`). No new PyPI distribution. Users who install `darnit` today get the harness available immediately with the workspace-standard `darnit ...` invocation shape. A future split into `packages/darnit-harness/` remains possible but is not this feature's concern; the CLI surface users learn now stays stable.

## Context

Feature 025 (RFC-0001 Stage 1) shipped the substrate: `Authority`, `ActionPlan` protocol, MCP tools, `LLMStep` Protocol with a `PydanticAILLMStep` default implementation. What it did NOT ship is a code path that actually dispatches an LLM call from an audit. Every current darnit entry point (`darnit audit`, `darnit run`, the `audit_openssf_baseline` MCP tool) uses `stop_on_llm=True` and leaves LLM steps as `PENDING_LLM` -- no key, no call, no LLM contribution. The `PydanticAILLMStep` is scaffolding waiting for a caller.

The one product path where LLM contribution DOES happen today is the coding-agent flow: a user opens Claude Code (or another MCP-capable coding agent), points it at a `darnit serve` instance, and the AGENT does the LLM work using its OWN model subscription. That works but is bounded to interactive single-project use.

**What this feature ships:** `darnit-harness` -- the RFC-0001-named "custom-harness driver" -- a runnable, non-interactive audit path that dispatches LLM steps itself using a user-supplied API key. A fleet operator running audits from CI, or a solo user without a coding-agent setup, invokes the harness and receives a completed audit report (not a `PENDING_LLM`-heavy shell of one). Same core code as MCP; a second entry point.

The harness is the missing "actually usable end-to-end" piece. It closes the loop the RFC opened: the same ActionPlan / next_action / submit_result surface the MCP tools expose, wrapped by a driver that owns pacing, LLM dispatch, feedback handling, and reporting, so a machine (CI, scheduled job) can drive it start to finish without a human clicking through a coding agent.

## User Scenarios & Testing *(mandatory)*

### User Story 1 -- Fleet operator runs a scheduled audit with an API key (Priority: P1)

A platform engineer at an organization runs `darnit-harness audit <repo-path>` from a scheduled CI job. The environment has an `ANTHROPIC_API_KEY` set. The harness performs a full audit end-to-end: deterministic handlers run as they do today, LLM-backed steps are dispatched to Claude using the configured key, human-confirmation steps that lack a stored answer are either skipped-with-report or answered from a config-declared source. The job produces a Markdown or JSON report and exits with a code that reflects the audit's compliance state.

**Why this priority**: This is the load-bearing user scenario the feature exists to serve. Without it, Stage 1's LLM machinery has no caller in the shipping code. Priority P1 because the entire feature's justification is "make the LLM dispatch actually reachable by a user."

**Independent Test**: An operator sets `ANTHROPIC_API_KEY`, invokes `darnit-harness audit /path/to/repo`, and observes: (a) the process runs to completion without exit-1 unless there are actual compliance failures, (b) the report contains at least one control whose evidence includes an `authority = "suggestive"` LLM contribution (proving the LLM was actually called), (c) no control appears with status `PENDING_LLM` (proving the LLM step resolved instead of staying pending), (d) exit code reflects the audit's failed-count.

**Acceptance Scenarios**:

1. **Given** a repository with a `.baseline.toml` and an `ANTHROPIC_API_KEY` in the environment, **When** the harness is invoked with an audit target, **Then** the audit completes end-to-end, no control's final status is `PENDING_LLM`, and any LLM step that ran has its output recorded as `suggestive` evidence on the affected control.
2. **Given** the same repository but WITHOUT `ANTHROPIC_API_KEY`, **When** the harness is invoked, **Then** the harness fails fast with a clear error naming the missing env var, no partial output is written to disk, and exit code is non-zero. The failure occurs BEFORE any audit control runs (so a badly-configured CI job doesn't silently produce a deterministic-only report labeled as complete).
3. **Given** a repository whose audit produces at least one FAIL, **When** the harness completes, **Then** the exit code is non-zero and the report identifies each FAIL by control id + reason.
4. **Given** a repository whose audit produces only PASS/N/A results, **When** the harness completes, **Then** exit code is 0 and the report lists the compliance summary.

---

### User Story 2 -- Batch feedback without a human present (Priority: P1)

A fleet audit encounters a control that requires human-judgment confirmation (e.g., "who is the security contact"). No human is present at the CI runner. The operator has pre-declared answers in an org-level context source (e.g., a `.project/` file at the org level or a config-declared answer file passed to the harness). The harness reads the answers from that source, applies them as `asserted` values, and the audit resolves the control without prompting.

**Why this priority**: Fleet audits are inherently non-interactive. If the harness can only run when a human answers prompts, it cannot serve its purpose. Priority P1 because scenario 1's "runs to completion without human" precondition depends on this.

**Independent Test**: An operator declares `security_contact` in a config-declared answer source, runs the harness against a repo whose audit would emit a `security_contact` feedback question, and observes: (a) the question is NOT printed to stdout as an interactive prompt, (b) the audit proceeds using the declared value as an `asserted` context value, (c) the affected control's status reflects the confirmed value being used.

**Acceptance Scenarios**:

1. **Given** a config-declared answer source containing `security_contact = "sec@example.com"`, **When** the harness runs and the audit emits a `security_contact` feedback question, **Then** the harness applies the declared value automatically (as `asserted` authority) and continues without human input.
2. **Given** a feedback question whose `context_key` has NO answer in the declared source, **When** the harness runs, **Then** the question is captured in the final report under a "pending human feedback" section AND the affected control's status reflects that the question was not answered (per Stage 1's authority rule, likely WARN). Exit code is non-zero.
3. **Given** an org-level `.project/` source (feature 017 territory) declaring shared answers, **When** the harness runs against a repo that inherits from it, **Then** answers flow through the same persistence layer feature 018 already provides.

---

### User Story 3 -- Report format the operator can consume (Priority: P2)

A fleet operator wants the audit output in a format their existing tooling can consume. The harness supports at least Markdown (human-readable summary for dashboards / issue creation) and JSON (structured for programmatic pipelines / downstream tools). Format is selected by a command-line flag or config setting.

**Why this priority**: Fleet operators typically wire darnit into a broader compliance pipeline. A tool that only prints human-readable output to stdout is hard to integrate. Priority P2 because Markdown alone (User Story 1's default) is enough to prove the harness works end-to-end; JSON is quality-of-life for pipeline integration.

**Independent Test**: Invoke the harness with `--format=markdown` and verify the report is a readable Markdown document. Invoke with `--format=json` and verify the report is a JSON document whose top-level keys include per-control results with authority attached.

**Acceptance Scenarios**:

1. **Given** a completed audit, **When** the harness is invoked with format = markdown, **Then** the output is a Markdown document with a summary section, a per-level compliance table, and a per-control details section. Every control result includes its authority.
2. **Given** the same audit, **When** the harness is invoked with format = json, **Then** the output is valid JSON containing `summary`, `controls` (with `id`, `status`, `authority`, `evidence`), and `pending_feedback` fields.
3. **Given** the report writes to stdout by default, **When** the harness is invoked with `--output <path>`, **Then** the report writes to that path and stdout carries only progress + summary lines.

---

### User Story 4 -- Verifiable exit code contract for CI integration (Priority: P2)

A CI pipeline treats a non-zero exit code from the harness as "audit found issues; block deploy or open an issue." The operator wants the exit-code convention to be documented, stable, and distinguishable across failure classes: setup error (missing API key, missing repo) vs audit failure (real compliance issue found) vs successful audit with all-pass. The harness prints a one-line summary to stderr before exit that names the exit class.

**Why this priority**: Automation depends on predictable exit codes. Priority P2 because User Story 1 acceptance #4 already establishes the base rule; this story tightens it for CI use.

**Independent Test**: Invoke the harness in each of the four scenarios (missing key, missing repo, FAIL result, all-pass result) and observe distinct exit codes + summary lines that let a shell script (or CI tool) branch appropriately.

**Acceptance Scenarios**:

1. **Given** any invocation, **When** the harness exits, **Then** a one-line summary is printed to stderr naming the exit reason (e.g., "harness: audit complete, N failed, exit 1" or "harness: setup error, missing ANTHROPIC_API_KEY, exit 2").
2. **Given** the four scenarios above, **When** each is invoked, **Then** exit codes are: 0 = all pass, 1 = audit found failures, 2 = setup/config error, 3 = harness internal error (unhandled exception). A CI script MUST be able to distinguish "audit ran and failed a control" from "audit couldn't run at all."

---

### Edge Cases

- API key is present but invalid (e.g., typo). The harness gets a 401 from the LLM provider on first call. It reports the error clearly (with the affected control's context) and exits with class 2 (setup error), not class 1 (audit failure). Difference matters because a CI operator triaging the failure needs to know the audit didn't actually run.
- API rate limit hit mid-audit. The harness has a bounded retry (matching the LLMStep Protocol's built-in retry semantics), then reports the affected control as ERROR (dispositive-authority ERROR is terminal per Stage 1), and continues with other controls. Final report distinguishes "control errored due to LLM outage" from "control legitimately failed."
- Config-declared answer source references a `context_key` the framework does not emit questions for. Harmless: the value is stored in context and available for `${context.*}` substitution, but no control actively consumes it. No warning printed.
- Repository has no `.baseline.toml`. Harness fails with exit class 2 and a message pointing at `darnit init` (or the equivalent).
- Report output path is a directory that doesn't exist. Harness attempts to create it (single level), fails with a clear error if creation fails, exits class 2.
- Config-declared answer source declares an answer for a `context_key` the framework marks as `auto_detect = false` (i.e., a user-judgment key per Constitution IV). The declared answer IS accepted -- the operator has explicitly asserted the value in a config the operator controls. No principle-IV violation because a human wrote the config; the harness is executing the operator's explicit assertion. This behavior is documented in the harness's docs.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The harness MUST be invokable as `darnit harness <repo-path>` -- a new subcommand on the existing `darnit` CLI, shipping in the `darnit-core` package (same distribution as `darnit audit` / `darnit run` / `darnit serve`). No separate binary; no new PyPI distribution. Positional argument is the target repo path; flags per FR-005 / FR-007 / FR-009a follow.
- **FR-002**: The harness MUST read `ANTHROPIC_API_KEY` (and equivalent env vars for any other supported providers, added later per FR-011) at startup. If required credentials are absent, the harness MUST fail fast with a named error and exit class 2. It MUST NOT begin running any audit control before credentials are verified.
- **FR-003**: The harness MUST use the `LLMStep` Protocol from feature 025 (`darnit.core.llm_step`). The default implementation is `PydanticAILLMStep` targeting the model configured via env or config (default: `anthropic:claude-sonnet-4-6`). Callers MUST NOT need to write adapter code to use the harness.
- **FR-004**: The harness MUST dispatch LLM steps in-band during audit execution. A control whose only path to a conclusion is an LLM step MUST have its LLM step actually run and its result attached as `suggestive` evidence (per feature 025's authority rule) -- NOT left as `PENDING_LLM` in the final report.
- **FR-005**: The harness MUST support reading pre-declared context answers from ONE OR MORE pluggable answer sources. Sources are consulted in a documented precedence order (later sources override earlier for the same `context_key`). MVP ships two file-based sources: (a) auto-discovered `.project/project.yaml` at the target-repo root (reuses feature 018's persistence path), and (b) an optional operator-supplied path via `--answers <path>` (YAML/JSON), which overrides the auto-discovered source per key. Values from any source resolve as `asserted` authority in the audit; no interactive prompt is shown for keys that have an answer from any source.
- **FR-005a**: Answer sources MUST be defined behind a Protocol (or equivalent Python-typed interface) so a future non-file adapter (email inbox, GitHub issue comments, Slack bot, ticketing system) can be added without modifying the harness core. MVP ships file adapters only; the seam is required so deferred / asynchronous answer collection (fleet-scale workflows where questions are batched to a team via email or issue tracker and consumed later) is an extension, not a rewrite. A test MUST assert the Protocol admits a mock non-file source that returns canned answers.
- **FR-006**: Feedback questions whose `context_key` has NO declared answer MUST be captured in the final report under a "pending" section. The harness MUST NOT block waiting for interactive input in the default (non-interactive) mode. An `--interactive` flag MAY be added to opt into stdin prompting for developer/local use; not required for MVP.
- **FR-007**: The harness MUST produce a report at completion. Default format is Markdown. `--format=json` MUST be supported. Every result in the report MUST include the `authority` field per feature 025's contract. Reports are written to stdout by default; `--output <path>` writes to a file instead.
- **FR-008**: Exit codes: `0` (audit completed, all applicable controls PASS or N/A), `1` (audit completed, at least one FAIL), `2` (setup / config error: missing credentials, missing repo, unparseable answer file, etc.), `3` (harness internal error: unhandled exception, invariant violation).
- **FR-009**: The harness MUST print a one-line summary to STDERR immediately before exit, naming the exit class and, for classes 0-1, the counts (e.g., "harness: complete, 42 PASS, 3 FAIL, 0 pending, exit 1"). Machine-readable enough that a CI script can pattern-match on it.
- **FR-009a**: During audit execution the harness MUST emit structured progress lines to STDERR at each control transition, following the same `LEVEL: message` shape darnit already uses across its other subcommands (Python stdlib logging conventions -- e.g. `INFO: [12/62] OSPS-VM-01.01 dispatching llm_extract`, `INFO: [12/62] OSPS-VM-01.01 -> PASS (dispositive)`). The format MUST include (a) a `[N/M]` progress counter, (b) the control id, and (c) a short human-readable phase / verdict description. Stdout MUST stay clean and reserved for the final report (FR-007). A `--quiet` flag MAY suppress progress lines while leaving the exit-summary intact; adopting the convention that the exit summary always prints is worth losing the `--quiet` option if it complicates things.
- **FR-010**: The harness MUST NOT invoke any handler that has side effects beyond the repository being audited (per Stage 1 Constitution V: "no step with side effects may run during Check or Collect"). Remediation is OUT OF SCOPE for this feature; the harness reports only, does not fix.
- **FR-011**: Provider support beyond Anthropic (e.g., OpenAI) MAY be added in a subsequent slice. When added, the provider is selected via a config field or env var (e.g., `DARNIT_LLM_MODEL=openai:gpt-4o` reading `OPENAI_API_KEY`). The `LLMStep` Protocol seam ensures adding a provider is a single-file source change per Q3 of feature 025.
- **FR-012**: The harness MUST share the same TOML / control-loading path as `darnit audit` and the MCP tools. A control that runs correctly under MCP MUST run identically under the harness (same integration name resolution, same authority rules, same evidence shape). A test MUST assert this equivalence on at least one non-trivial fixture.
- **FR-013**: Confirmation persistence works the same as it does for `graph.collect_context` today: any confirmed value (whether from the config-declared source OR from `--interactive` input, if that flag is added later) is persisted to `.project/project.yaml` via feature 018's `save_context_values`. Subsequent runs pick up the persisted answers.
- **FR-014**: The harness MUST NOT hang. Bounded operations: (a) LLM calls are subject to whatever timeout `PydanticAILLMStep` / the underlying SDK provides plus a harness-level ceiling (recommend 60s per call); (b) any subprocess handler (exec, git remote) inherits the sieve's existing timeout defaults; (c) total audit-run wall-clock has a configurable ceiling (default 15 minutes) after which the harness reports "audit timed out" as ERROR-class terminal and exits class 3.
- **FR-015**: ASCII-only in all new source files (matches project convention from features 022/024).
- **FR-016**: A shipping test MUST exercise the harness end-to-end against a fixture repository, WITH a mocked `LLMStep` (so tests do not require a real API key). The test MUST assert: (a) the mocked LLM was called, (b) the LLM's output was recorded as `suggestive` evidence, (c) no control status is `PENDING_LLM` in the final report, (d) exit code follows the rule.

### Key Entities

- **Harness invocation**: a single command run with a repo path, an optional answer-source path, and an optional output-format flag. Reads credentials from env. Exits with a documented code.
- **Answer source**: a pluggable interface over one or more origins that provide pre-declared answers to feedback-question `context_key`s. MVP file adapters: `.project/project.yaml` (auto-discovered in target repo; feature 018 persistence layer) and an operator-supplied YAML/JSON via `--answers <path>`. Future adapters (email, GitHub issues, Slack, ticketing) plug into the same Protocol without harness-core changes. Values from any adapter become `asserted` authority in the audit.
- **Audit report**: the Markdown or JSON document the harness emits at completion. Contains a summary, per-level compliance breakdown, per-control results (with `authority`), and a pending-feedback section for unresolved questions.
- **Harness exit summary**: a one-line stderr message before process exit, machine-readable enough for CI scripts.
- **`LLMStep` (from feature 025)**: the Protocol the harness uses to dispatch LLM calls. Default implementation is `PydanticAILLMStep`; tests inject `MockLLMStep`.
- **Config-declared answer source (MVP file adapter)**: NOT a new schema; the MVP `.project/project.yaml` adapter reuses feature 018 shape so the same file that the coding-agent path writes to is the file the harness reads from. This ensures a repo whose confirmations were captured via one path (Claude Code + MCP) can be audited via the harness later with those confirmations intact. The `--answers <path>` adapter accepts YAML or JSON at the same key/value shape.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A fleet operator with an `ANTHROPIC_API_KEY` and a repo can invoke a single command and receive a complete audit report where no control has status `PENDING_LLM`. This is the load-bearing "actually deliverable" property.
- **SC-002**: Startup fails within 2 seconds when credentials are missing, before ANY audit control runs. Verifiable by checking exit code + timing on a fixture with no API key set.
- **SC-003**: The harness runs to completion on the feature-024 `minimal_repo` fixture (deterministic-only path, no LLM step needed) in under 30 seconds wall-clock, exit code 0. Verifiable in CI.
- **SC-004**: The harness runs to completion on a fixture that DOES require an LLM step, with a `MockLLMStep` injected, in under 30 seconds wall-clock. The mocked LLM's output appears as `suggestive` evidence on the affected control's result. Verifiable in CI (no API key required for the test).
- **SC-005**: Exit codes are distinct for the four documented classes (0/1/2/3). Verifiable via parameterized test that invokes the harness under each condition and asserts on the exit code.
- **SC-006**: Report includes `authority` on every result. Verifiable by parsing the JSON output of a run against a fixture and asserting every `controls[i].authority` value is in the declared Literal domain.
- **SC-007**: A control that runs under the harness produces the same status + authority as the same control running under the coding-agent MCP path against the same fixture. Cross-driver equivalence test. This carries feature 025 SC-003's three-way equality property into the harness domain.
- **SC-008**: Feature 025 SC-001 (LLM cannot manufacture PASS) holds in the harness path: a mocked LLM that returns high-confidence PASS for a `suggestive` step MUST NOT cause the affected control's status to be PASS. Verifiable by test.
- **SC-009**: Harness produces the exit-summary stderr line in a format a shell script can `grep` on to distinguish the four exit classes. Verifiable via shell-scripted test that invokes the harness and asserts on the stderr content.

## Assumptions

- **A1**: Ships as a new subcommand `darnit harness <path>` on the existing `darnit` CLI (Q3 clarification). No new PyPI package; no separate binary. A future extraction into `packages/darnit-harness/` remains possible but is not this feature's concern.
- **A2**: MVP supports only Anthropic (Claude). OpenAI and other providers are FR-011 future work; the seam is already in place from feature 025 Q3.
- **A3**: Interactive mode (stdin prompts for missing answers) is NOT required for MVP. The harness's default use case is non-interactive CI. `--interactive` MAY be added as a small follow-up.
- **A4**: Remediation is OUT OF SCOPE. The harness reports; it does not fix. Fixing lives in a future feature (or via the existing `graph.remediate` path invoked separately).
- **A5**: The default LLM model is `anthropic:claude-sonnet-4-6` (matches Q3). Configurable via env / config later, but MVP hardcodes the default.
- **A6**: Feature 025 (RFC-0001 Stage 1) is in place. `LLMStep`, `PydanticAILLMStep`, `next_action`/`submit_result`, and the authority-keyed execution rule are all shipped. This feature CONSUMES those primitives; it does not re-implement them.
- **A7**: The harness uses `run_sieve_audit` (or the equivalent orchestrator entry point) BUT with `stop_on_llm=False` -- the opposite of every other current entry point. When the orchestrator reaches an LLM step, it dispatches via the injected `LLMStep` and gets a real result rather than returning `PENDING_LLM`. This is where the harness's value lives.
- **A8**: The persistence path for confirmations is `save_context_values` from feature 018. Nothing new is added at the persistence layer.
- **A9**: Attestation signing is out of scope for this feature. The harness reports; if attestation is desired, it composes with the existing baseline attestation path in a future integration. The `authority` field is already added to attestations by feature 025 T046.

## Out of Scope

- Remediation (auto-fix, PR creation, denylist enforcement, auto-merge). Reserved for RFC-0001 Stage 3.
- Multi-repo iteration (`darnit-harness audit-org`). Handleable via shell script wrapping single-repo harness invocations for MVP; native fleet-mode belongs in Stage 3 with the deduped question queue.
- Deduped org-level feedback queue (RFC "Fleet mode and the manual queue"). Stage 3 territory.
- OpenAI / other LLM provider adapters. FR-011 says the seam supports them; MVP is Anthropic-only.
- New MCP tools. This feature adds a NON-MCP driver; MCP surface from feature 025 Slice C is unchanged.
- Attestation signing changes. Feature 025's per-result authority is already in the predicate; nothing more here.
- Interactive TTY prompts (`--interactive`). Small enough to add later as a follow-up; not required for MVP.
- A new package on PyPI. Whether the harness ships as `packages/darnit-harness/` or as a subcommand of `darnit-core` is a plan-time decision. Users installing darnit today should get the harness available in either shape.
- Non-file answer-source adapters (email inbox reader, GitHub issue-comment reader, Slack bot answerer, ticketing-system integration). The Protocol seam (FR-005a) MUST land in MVP so these adapters can be added later without harness-core changes; the adapters themselves are follow-up features.
- Persistent LLM response caching across runs (RFC "Caching and non-determinism"). Stage 2 concern; MVP calls the LLM fresh each run.
