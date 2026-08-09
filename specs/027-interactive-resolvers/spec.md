# Feature Specification: Interactive Question Resolvers

**Feature Branch**: `027-interactive-resolvers`

**Created**: 2026-08-07

**Status**: Draft

**Input**: User description: "Add an interactive question-resolver mechanism to `darnit harness` so an operator at the terminal can answer feedback questions live, alongside the existing file-based `--answers` flow."

## Clarifications

### Session 2026-08-07

- Q: How do third parties register a `QuestionResolver`? -> A: Hybrid -- Python entry points for third-party packages (matching darnit's existing `darnit.implementations` discovery pattern) AND direct injection into `HarnessRun.question_resolvers` for tests and inline library use.
- Q: Where does the interactive prompt write its output? -> A: `/dev/tty` for the MVP (matches the git/ssh/sudo private-operator-channel pattern; isolated from stdout/stderr). The prompt output channel MUST be designed as a pluggable seam so future variants can route prompts to event streams, log sinks, or other observability channels without requiring a Protocol change. `/dev/tty` is the default; configurability is post-MVP.
- Q: What does the operator see for progress during interactive collect? -> A: Bookends only. The prompt payload on `/dev/tty` includes an `[N of M]` position indicator. Stderr gets exactly one "starting interactive collection" line before the first prompt and one "finished interactive collection: X answered, Y skipped" line after the last. No per-question stderr progress line during collect; ordinary `[N/M]` audit-progress lines are suppressed for the duration of the interactive phase.
- Q: What semantics does `Answer("")` (or whitespace-only) have when returned by a programmatic resolver? -> A: Treated as skip, symmetric with interactive UX. A resolver that means "I have no answer for this" returns None; `Answer("")` and `Answer("   ")` are collapsed to skip so the question stays pending. This is a resolver-contract rule, enforced at the harness layer so no resolver author can accidentally record an assertion of emptiness.
- Q: Should the report record which resolvers DECLINED a question, or only which one answered? -> A: Full trail. For each pending question, the report captures a `resolution_trail` list containing one entry per resolver that was offered the question, with an outcome enum: `answered`, `skipped`, or `errored`. This is the Constitution IV audit-trail property: an auditor can see not just the final answer, but every resolver that was tried and why each one didn't produce the value.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Operator answers questions live at the terminal (Priority: P1)

A fleet-quality auditor runs `darnit harness some-repo --interactive` and the harness pauses to ask each unanswered feedback question in turn. The operator types an answer (or hits Enter to skip). Each answered value lands in the report with an origin string so a later reviewer can see how the value was obtained.

**Why this priority**: The whole point of the feature. Feature 026 shipped batch answer collection via `--answers <file>`; the operator experience of filling in answers by hand into a YAML file, then re-running the audit, is friction that keeps interactive users off the harness. This story replaces "write YAML, re-run" with "type the answer, next question."

**Independent Test**: Run the harness against a fixture repo with two pending questions on a TTY-attached terminal; answer one; skip the other. The report shows one answered question with `origin: "interactive_terminal"`, one still-pending question, and no additional YAML file was needed.

**Acceptance Scenarios**:

1. **Given** a repo with one pending question and stdin is a TTY, **When** the operator runs `darnit harness <path> --interactive` and types an answer at the prompt, **Then** the report records the answer with `origin: "interactive_terminal"` and no unanswered questions remain for that control.
2. **Given** the same setup, **When** the operator hits Enter without typing anything, **Then** the question stays in the report's pending-feedback list unchanged.
3. **Given** two pending questions, **When** the operator answers the first and hits Ctrl+C at the second, **Then** the report contains the first answer and lists the second question as still pending; the process exits with a documented exit code (audit outcome, not internal error).
4. **Given** stdin is NOT a TTY (piped from a file, running under CI), **When** the operator passes `--interactive`, **Then** the harness fails fast with a clear setup-error message identifying the missing TTY (exit code SETUP_ERROR, in under 2 seconds).

---

### User Story 2 - Third-party author writes a custom resolver (Priority: P2)

An engineer at a downstream org wants their fleet audit to fetch answers from an internal Slack workflow instead of prompting at the terminal. They write a class with a `name` attribute and an `async def resolve(question) -> Answer | None` method, register it with the harness, and rerun. The harness routes pending questions through their resolver without any change to `darnit.harness.driver`.

**Why this priority**: The QuestionResolver Protocol is the load-bearing contract of the feature. If P1 lands but the Protocol is not usable by third parties without forking the driver, the feature has failed at its extensibility goal. Interactive resolution is one concrete implementation of the Protocol; the Protocol itself is the deliverable.

**Independent Test**: A test that defines an in-repo `MockQuestionResolver` returning a fixed answer, injects it into `HarnessRun.question_resolvers`, and asserts the answer appears in the report with the mock's `name` in `origin`. The test must not touch `driver.py` internals.

**Acceptance Scenarios**:

1. **Given** a `MockQuestionResolver` class that satisfies the Protocol, **When** it is added to a `HarnessRun`'s resolver list, **Then** pending questions are offered to it and its returned answers appear in the report.
2. **Given** two resolvers registered in order (interactive first, mock second), **When** the interactive resolver returns None for a question (operator skipped), **Then** the mock resolver is offered the same question.
3. **Given** a resolver's `resolve()` raises an exception, **When** the harness processes a pending question, **Then** the exception is caught, logged with the resolver name, and the harness continues to offer the question to the next registered resolver (or leaves it pending if none remain).

---

### User Story 3 - Combining `--answers` file and interactive mode (Priority: P3)

An operator has a `answers.yaml` covering the values that are known ahead of time (e.g. `security_contact: security@example.com`) and wants to answer the rest live at the terminal. They pass both `--answers answers.yaml --interactive`. Only questions the file did not cover are prompted.

**Why this priority**: Composition of the two mechanisms is the natural workflow but adds no new safety or extensibility properties beyond P1/P2. A user could achieve the same result by running twice; the primary value is ergonomics.

**Independent Test**: Fixture repo with three pending questions; `answers.yaml` covering one; run with `--answers ... --interactive` on a fake TTY that answers one prompt and skips the other. The report shows one answer from the file (origin `--answers <file>`), one from interactive (origin `interactive_terminal`), and one still pending.

**Acceptance Scenarios**:

1. **Given** an `--answers` file covers one question and one is uncovered, **When** the harness runs with both `--answers` and `--interactive`, **Then** the operator is prompted only for the uncovered question.
2. **Given** the same setup, **When** viewing the final report, **Then** each answered question shows its own origin (file vs. interactive).

---

### Edge Cases

- **Empty input on Enter**: treated as skip. The question stays pending. Empty input is never recorded as an asserted answer.
- **Whitespace-only input**: also treated as skip. Rationale: a whitespace-only answer is almost certainly a mis-keystroke; recording it as an assertion produces a value that will fail downstream validation anyway, but with confusing provenance ("a human said ''"). Skip is safer and honest.
- **Ctrl+C mid-question**: interpreted as "stop asking further questions." Already-collected answers remain in the report. The harness continues to report assembly (does not treat this as an internal error).
- **Ctrl+D (EOF) mid-question**: same behavior as Ctrl+C -- stop asking, keep what was collected.
- **Very long answer** (over 10KB): accepted. There is no product-level cap; the resolver contract does not constrain answer size. Downstream consumers may truncate for display.
- **A resolver's `resolve()` hangs**: covered by per-resolver timeout (see FR-011). The interactive resolver has no built-in timeout by default (a human at a terminal may take arbitrary time); a fleet operator may set one via configuration if desired.
- **Non-TTY stdin with `--interactive`**: setup error, fail fast. Never silently degrade to skipping all questions.
- **`/dev/tty` unavailable with `--interactive`** (e.g., detached process, unusual container / chroot without the device node): setup error, fail fast. Same class as non-TTY stdin. The interactive resolver's private operator channel is a hard requirement in the MVP.
- **`--interactive` and `--output <file>`**: coexist. Prompts still go to stdin/stdout; the final report goes to the file.
- **Multiple resolvers claim to answer the same question**: first non-None wins. Ordering is registered order; interactive is registered first (immediately after `--answers` in the source chain).
- **Empty pending-questions list at collect time**: interactive resolver is not invoked (nothing to ask). This is not an error; the operator sees no prompt.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a `QuestionResolver` Protocol distinct from `AnswerSource`. `QuestionResolver` represents an active, potentially-async answer producer (asks a human, calls an external service, opens an issue) rather than a passive lookup.
- **FR-002**: The Protocol MUST expose at minimum a stable identifier (`name`) and an async `resolve` method that takes one pending feedback question and returns either an answer with provenance or nothing.
- **FR-003**: The harness MUST run registered resolvers downstream of the existing `AnswerSource` chain: `.project/project.yaml` -> `--answers <file>` -> registered resolvers in registration order. Any question left uncovered by the source chain is offered to each resolver in turn until one returns an answer or the list is exhausted.
- **FR-004**: An `InteractiveTerminalResolver` MUST be provided as the reference implementation. It writes prompts to and reads answers from `/dev/tty` (the private operator channel used by git, ssh, and sudo), so the report stream on stdout and the progress/exit-summary stream on stderr from feature 026 both remain uncontaminated. The prompt payload MUST include, at minimum, the control identifier, the question text, and any control-level help text available.
- **FR-004a**: The prompt output channel MUST be a resolver-internal seam (not baked into the Protocol contract). A future variant that routes prompts to an event stream, log sink, WebSocket, or other observability channel MUST be possible without changing `QuestionResolver` itself. `/dev/tty` is the MVP default; alternative output channels are post-MVP.
- **FR-005**: The interactive resolver MUST refuse to run when stdin is not a TTY OR when `/dev/tty` is not openable (e.g., detached process, chroot without the device). This case is a setup error, not a silent degrade.
- **FR-006**: Empty input (including whitespace-only input) at the interactive prompt MUST be treated as "skip" -- the question stays pending; nothing is asserted.
- **FR-006a**: A resolver that returns an `Answer` whose `value` is empty or whitespace-only MUST be treated identically to a resolver that returns None: the question stays pending; no assertion is recorded. This applies uniformly across all resolvers (interactive, programmatic, future A2A / GH-issue / Slack). "I have no answer" is the single canonical way to skip a question; asserting an empty value is not a supported semantic in the MVP.
- **FR-007**: Ctrl+C or EOF during interactive collection MUST stop prompting for further questions and preserve already-collected answers. This case is not an internal error; the report is still assembled and returned.
- **FR-008**: Every answer produced by a resolver MUST carry an origin string identifying which resolver produced it (e.g. `"interactive_terminal"`, `"gh_issue_42_comment"`, `"a2a_agent_xyz"`). The origin MUST appear in the final report against each answered question.
- **FR-009**: An answer produced by a resolver MUST be tagged with `authority: "asserted"` in the report. Consumers can distinguish it from `dispositive` (observed) or `suggestive` (inferred) provenance.
- **FR-010**: The CLI MUST support a `--interactive` flag on `darnit harness`. It defaults off. Passing it registers the interactive resolver at the head of the resolver chain.
- **FR-011**: The system MUST support a per-resolver timeout mechanism. The interactive resolver's default is no timeout (a human may take arbitrary time); resolver authors and operators MAY configure explicit bounds.
- **FR-012**: A resolver whose `resolve()` raises an exception MUST NOT crash the harness. The error MUST be logged with the resolver's name and the harness MUST continue to offer the same question to any remaining resolvers.
- **FR-013**: Answer values MUST NOT appear verbatim in progress log lines. Log lines may reference the question by control id and context key, but the operator-supplied value belongs in the report, not the log stream.
- **FR-013a**: During interactive collection, the harness MUST emit exactly two bookend lines on stderr: one "starting interactive collection (N pending questions)" line before the first prompt, and one "finished interactive collection: X answered, Y skipped, Z aborted-via-interrupt" line after the last prompt or after Ctrl+C. Ordinary per-control `[N/M]` progress lines MUST be suppressed for the duration of the interactive phase so they do not collide with the prompt.
- **FR-013b**: Each interactive prompt payload written to `/dev/tty` MUST include a position indicator (e.g. `[2 of 5]`), the control identifier, the question text, and any control-level help text available. The position indicator lives in the prompt payload -- NOT in stderr -- so an operator sees exactly one place per prompt where "where am I in this collection?" is answered.
- **FR-014**: The Protocol MUST be discoverable via two mechanisms: (a) Python entry points under a dedicated group (e.g. `darnit.question_resolvers`) so third-party packages can register a resolver by shipping a wheel with an entry-point declaration, matching darnit's existing pattern for framework implementations; and (b) direct injection into `HarnessRun.question_resolvers` at construction time, for tests and inline library use. Neither mechanism requires editing files under `packages/darnit/src/darnit/harness/`.
- **FR-015**: The report MUST record which resolvers were configured for the run, in the same shape as it already records `answer_sources_used`. This is provenance for the audit trail.
- **FR-015a**: For every pending question that reaches the resolver chain, the report MUST include a `resolution_trail` list capturing one entry per resolver that was offered the question. Each entry MUST include the resolver's `name` and an `outcome` value from a small closed set: `answered` (resolver returned a valid non-empty answer), `skipped` (resolver returned None, or an empty-or-whitespace-only Answer per FR-006a), or `errored` (resolver raised an exception per FR-012). `errored` entries MUST also include a truncated exception summary; `answered` entries MUST reference the `Answer.origin` on the accompanying answer. Trail entries appear in the order resolvers were offered the question, so a reader can reconstruct the chain.
- **FR-016**: The existing MVP policy that answer collection does NOT trigger re-audit (feature 026 data-model.md) applies unchanged to interactively collected answers. This spec does not introduce automatic re-audit on interactive input.

### Key Entities

- **QuestionResolver**: A pluggable active answerer for a pending feedback question. Has a stable name, an async resolve method, and may fail, time out, or return None ("I can't answer this one").
- **Answer**: The value returned by a resolver, together with its origin string (which resolver produced it) and its authority tag (`asserted` in every case that flows from this feature). The value MUST be a non-empty, non-whitespace-only string; empty and whitespace-only `Answer` objects are collapsed to skip (equivalent to returning None) by the harness before landing in the report. There is no supported way in the MVP for a resolver to assert an empty value.
- **FeedbackQuestion**: The pending question the sieve produced during audit (already present in feature 026 data-model). Feature 027 adds no new fields.
- **ResolverChain**: The ordered list of resolvers configured on a `HarnessRun`. Composed by the CLI when parsing flags; injectable directly for library/test use.
- **ResolutionTrailEntry**: One entry in the per-question audit trail. Carries the resolver's `name` and an `outcome` (`answered` | `skipped` | `errored`). `errored` entries carry a truncated exception summary; `answered` entries reference the `Answer.origin` of the answer that was accepted. Ordered by the sequence in which resolvers were offered the question.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator sitting at a terminal can answer five pending questions in under three minutes, end-to-end, from harness invocation to report assembly. Baseline for comparison: the file-round-trip workflow (edit YAML, re-run audit) takes longer than five minutes for the same five questions.
- **SC-002**: A third-party developer can add a new resolver (mock, real, or otherwise) that satisfies the Protocol without modifying any file in `packages/darnit/src/darnit/harness/`. This is enforceable by a test that adds a resolver defined outside that directory tree and asserts it is invoked.
- **SC-003**: Every answer surfaced through a `QuestionResolver` in the final report carries `authority: "asserted"`. No path through this feature emits an answer tagged `dispositive` or `suggestive`. Enforced by test.
- **SC-004**: If the operator hits Ctrl+C after answering some questions, the report still contains those answers. No answer is lost due to interrupt handling. Enforced by test using a scripted resolver that raises `KeyboardInterrupt` after N answers.
- **SC-005**: Running `darnit harness ... --interactive` when no operator channel is available (stdin is not a TTY, OR `/dev/tty` is not openable) fails within 2 seconds with exit code `SETUP_ERROR` and a stderr summary that names the missing channel as the cause. No control is ever executed before this failure.
- **SC-006**: For every answered question in a report, an auditor can determine which resolver produced it by reading a single `origin` field. This is verifiable via schema check on report output.
- **SC-007**: A resolver that raises an exception on `resolve()` does not affect other resolvers or other questions. Verified by a test that registers two resolvers where the first always raises; the second is still invoked and its answers appear in the report.
- **SC-008**: During an interactive run with N pending questions, stderr contains exactly two harness-emitted collection-related lines: the "starting interactive collection" bookend and the "finished interactive collection" bookend. Verified by capturing stderr across a scripted interactive run and asserting the count.
- **SC-009**: For every pending question in the report, an auditor can reconstruct the full resolver chain that was attempted: which resolvers were offered the question, in what order, and with what outcome for each. Verified by a test that registers three resolvers (first errors, second skips, third answers) against one pending question and asserts the `resolution_trail` contains exactly those three entries in order with outcomes `errored`, `skipped`, `answered`.

## Assumptions

- The primary interactive medium is the operator's terminal (stdin/stdout). Future resolvers may use other channels (Slack, GitHub, A2A) but this feature ships one reference resolver only.
- The interactive resolver uses stdlib I/O. No dependency is added on `rich`, `click`, `prompt_toolkit`, or similar libraries. Terminal ergonomics beyond "print prompt, read line" are out of scope for the MVP.
- The interactive resolver's prompt output channel is `/dev/tty` in the MVP. A future post-MVP variant may route prompts to an event stream, log sink, or other observability channel for headless / audited operator flows. FR-004a captures this as a design constraint; the specific alternative channels are out of scope for this feature.
- The `AnswerSource` -> `QuestionResolver` two-phase model is the correct shape. Passive lookup and active resolution are semantically distinct enough to warrant separate Protocols. If future evolution merges them, that is a spec change, not a refactor.
- The "no re-audit after collect" MVP policy from feature 026 remains in effect. A separate feature (not this one) may introduce re-audit-on-fresh-answer.
- Progress lines and exit-summary contracts from feature 026 remain unchanged. Interactive prompts appear on stdout; existing stderr contract for exit summaries is untouched.
- CI environments will not use `--interactive`. The non-TTY fail-fast is a safety net, not a common code path.
- Every entry point for creating a `HarnessRun` will provide a way to inject `question_resolvers`, including from the CLI, from the Python API, and (later) via configuration files. The exact injection surface is a plan-phase concern.
- The Constitution IV property ("Never Guess User Values") is not weakened by this feature. A human answering a prompt is confirmation, which promotes a value from candidate to usable -- an asserted answer is the point at which the human explicitly speaks. It never authorizes concluding a value on the human's behalf.
- Constitution IV requires a confirmation to record when it was made, by whom, and which candidate it was based on. This feature does NOT persist interactive answers (feature 026's "no re-audit after collect" MVP policy applies unchanged). The record-when/by-whom/which-candidate requirement therefore applies to a future persistence step (writing the value to `.project/project.yaml`), not to this feature's in-memory capture. Feature 027 is complete without those fields; a follow-up feature that persists interactively supplied values MUST add them.
- Existing tests for feature 026 (batch collection, `--answers`, no re-audit invariant) MUST continue to pass without modification. This feature is additive to the answer-collection surface.
