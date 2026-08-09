# Phase 0 Research: Interactive Question Resolvers

**Feature**: 027-interactive-resolvers | **Date**: 2026-08-08

All five load-bearing decisions were resolved in `/speckit-clarify` and are recorded in `spec.md`'s Clarifications section (2026-08-07 session). This research file covers the *technical* how -- the residual mechanics that Phase 1's design work needs to sit on top of.

## R1. Protocol shape + registration mechanism

**Decision**: `QuestionResolver` is a `@runtime_checkable` Protocol with (a) a `name: str` class or instance attribute and (b) an async `resolve(question: FeedbackQuestion) -> Answer | None` method. Registration is hybrid per the clarify session:

- **Entry point** group: `darnit.question_resolvers`. Format matches `darnit.implementations` (existing pattern): `entry-point-name = "package.module:factory_callable"`. The factory returns an instance implementing the Protocol.
- **Direct injection**: `HarnessRun(question_resolvers=[MyResolver(), ...])`. Bypasses discovery entirely -- used by tests and library consumers.

The CLI resolves an operator-visible flag (`--interactive`) into a resolver by name: the terminal resolver is registered by darnit-core itself as an entry point named `interactive_terminal`, so `--interactive` is equivalent to "look up the `interactive_terminal` entry point and put it at the head of the chain."

**Rationale**: Matches darnit's existing extension pattern (`ComplianceImplementation`). Allows third-party packages to register without a code change to darnit-core (Constitution I, SC-002). Direct injection is the natural surface for tests -- no need to construct a wheel to test a resolver.

**Alternatives considered**:
- Direct injection only: rejected because a third party can't ship a wheel that drops into a fleet operator's environment; they'd need to write a wrapper. Fails the SC-002 extensibility test.
- Config-file registration (`.baseline.toml` resolver list by module path): rejected as another config surface with no offsetting benefit; entry points already give us packaged discovery.
- Auto-discovery scanning `sys.path` for `resolvers/*.py`: rejected as too magical; entry points are declared intent.

## R2. Entry-point discovery mechanics

**Decision**: Use `importlib.metadata.entry_points(group="darnit.question_resolvers")`. Guard against the Python 3.9 vs 3.10+ API drift by pinning to the 3.10+ shape (returns `EntryPoints` selection object). darnit already requires 3.11+ so this is safe.

Discovery result: a list of `EntryPoint` objects. For each, `ep.load()` returns the factory callable. Call it with no arguments; expect a `QuestionResolver` instance back. `isinstance(instance, QuestionResolver)` verifies conformance (Protocol is `@runtime_checkable`).

Discovery runs at CLI startup, before any control iteration. Failures during `ep.load()` for a single entry point log a WARNING with the entry-point name and continue (don't crash the whole run on one malformed third-party wheel). Failure during `isinstance` check is likewise a warning + skip.

**Rationale**: Matches how `darnit.implementations` is discovered in `packages/darnit/src/darnit/core/discovery.py`. Same behavior on failure (log + continue). No new dependency; `importlib.metadata` is stdlib.

**Alternatives considered**:
- `pkg_resources` (setuptools legacy): rejected -- deprecated, slower, adds an implicit runtime dep on setuptools.
- Eager import at module load time: rejected -- would tie test isolation to global state; lazy discovery at CLI startup is cleaner.

## R3. `/dev/tty` mechanics

**Decision**: Open `/dev/tty` in mode `"r+"` with unbuffered binary or line-buffered text. Concretely: `open("/dev/tty", "r+", buffering=1)` (line-buffered text mode). Read one line at a time via `.readline()`; strip trailing newline; treat empty-after-strip as skip.

Availability check: at `InteractiveTerminalResolver` construction (or at the first `resolve()` call), attempt `open("/dev/tty", "r+")`. On `OSError` / `FileNotFoundError`, raise a subclass of `HarnessSetupError` so the caller (`cmd_harness`) can translate to exit code 2 with an intelligible stderr summary.

**Rationale**: `/dev/tty` is the POSIX-standard private operator channel. `readline()` returns the empty string on EOF, giving us a clean Ctrl+D signal (treat identically to Ctrl+C -- stop asking, keep collected). `open` failure names the platform reason directly.

Ctrl+C handling: `readline()` raises `KeyboardInterrupt`. The resolver catches it, closes the /dev/tty handle, and re-raises a small sentinel exception (`InteractiveAborted`) that the driver's collect loop catches and treats as "stop further prompts, preserve collected answers." Existing signal handlers are not overridden; we just react to the natural KeyboardInterrupt.

**Alternatives considered**:
- `input()` (writes to stdout, reads from stdin): rejected -- would pollute the report stream (Q2 of clarify).
- `getpass.getpass` (reads from `/dev/tty` on POSIX): rejected -- silent echo, wrong UX for these prompts which are not secrets.
- `curses` full-screen prompt: rejected -- vast overkill and forces a stdlib module that some minimal Python builds omit.
- Raw `os.open("/dev/tty", os.O_RDWR)` + manual read/write: rejected -- gives us nothing over the `open()` file-object wrapper and forces us to reimplement line buffering.

## R4. Testing `/dev/tty` -- inject streams

**Decision**: `InteractiveTerminalResolver.__init__` accepts optional `input_stream` and `output_stream` parameters (default: both `None`, meaning "open `/dev/tty`"). Tests pass `io.StringIO` for both. Production code path never sees `StringIO`.

Prompt-format regression: a golden-file test writes a scripted resolver run to a `StringIO` output stream and asserts the byte-for-byte prompt payload matches an expected fixture. Cheap way to lock in the position-indicator + control-id + question-text + help-text ordering.

**Rationale**: Same shape as feature 026's `harness_run_factory` fixture -- constructor-time injection lets tests exercise the code without touching real terminals. Matches Python community norms for testing CLI apps.

**Alternatives considered**:
- Monkey-patch `builtins.open` in tests: rejected -- global patch is fragile; interacts badly with pytest's own capture machinery.
- Use `pexpect` to script a pseudo-terminal: rejected -- brings in a heavyweight test dep; the injectable-stream approach gives 95% of the coverage at 5% of the cost.

## R5. Progress-line suppression during interactive collect

**Decision**: The driver's `_collect_unanswered` is the phase where interactive prompts fire. Ordinary per-control `[N/M]` audit-progress lines have already stopped by this point (the audit + LLM continuation loop both finish before collect begins). But the driver DOES emit progress lines from within `_llm_continuation_loop`. We ensure no such lines are emitted from inside the collect phase itself -- collect is silent on `darnit.harness` except for the two bookends specified in FR-013a.

Implementation shape: `_collect_unanswered` opens with `logger.info("harness: starting interactive collection (%d pending)", n)`, iterates the resolver chain, and closes with `logger.info("harness: finished interactive collection: %d answered, %d skipped, %d aborted", ...)`. Nothing between those two lines writes to `darnit.harness`.

**Rationale**: Simplest possible implementation of FR-013a. No log-level fiddling, no filter push/pop, no signal to progress emitters to hush. The audit-progress emitters are already quiescent by the time collect starts; we just have to keep collect itself quiet.

**Alternatives considered**:
- Install a logging filter for the duration of collect: rejected -- more state, more surface area, no benefit given the audit-progress emitters are already done.
- Route interactive-collect progress to a separate logger name: rejected -- adds an axis of configuration for no operator-visible benefit.

## R6. Resolution trail construction and error redaction

**Decision**: For each pending question the driver visits:

1. Iterate resolvers in registered order.
2. Call `await resolver.resolve(question)` inside a try/except.
   - On `Answer(...)` return with non-empty value: append `ResolutionTrailEntry(resolver_name=resolver.name, outcome="answered")`, apply the answer, stop iteration for this question.
   - On `Answer(...)` with empty/whitespace value OR `None` return: append `ResolutionTrailEntry(resolver_name=resolver.name, outcome="skipped")`, continue.
   - On any exception (except `InteractiveAborted`): capture `str(exc)`, redact via feature 026's `_redact_secrets`, append `ResolutionTrailEntry(resolver_name=resolver.name, outcome="errored", error_summary=redacted[:200])`, continue.
   - On `InteractiveAborted` from the interactive resolver: append `ResolutionTrailEntry(resolver_name=resolver.name, outcome="skipped")` (Ctrl+C is a skip for THIS question), stop the whole collection loop (do not offer remaining pending questions to any resolver).

3. If iteration completes with no `answered` entry, the question stays pending in the report with the full trail attached.

Error summary is truncated to 200 characters (research-time choice; adjustable in the plan phase if we prefer a different bound). Redaction reuses the exact `_redact_secrets` regex table from feature 026 so credential leakage is handled consistently across the harness.

**Rationale**: The trail is written incrementally -- every resolver visit produces exactly one entry. Ordering matches invocation order. Error summaries are bounded so a runaway third-party resolver with a 10KB stack trace can't bloat the report.

**Alternatives considered**:
- Emit the whole exception `__traceback__`: rejected -- privacy risk, size risk. Summary + truncation is the right conservative default.
- Collect exceptions into a sidecar file: rejected -- splits the audit trail across two artifacts, opposite of FR-015a's intent.

## R7. Interaction with `HarnessRun` public API

**Decision**: Add `question_resolvers: list[QuestionResolver] = field(default_factory=list)` to the `HarnessRun` dataclass. Add a `HarnessRun.build_default_resolver_chain(interactive: bool) -> list[QuestionResolver]` classmethod that:

- If `interactive` is True: opens the `interactive_terminal` entry point from `darnit.question_resolvers` and puts it first.
- Then appends every OTHER entry point in the `darnit.question_resolvers` group in the order returned by `importlib.metadata.entry_points()` (stable across a given interpreter session, undefined across installs; documented as such).

Direct-injection callers construct their own list; the factory exists only for the CLI path.

**Rationale**: Symmetric with feature 026's `build_default_resolver` (for `AnswerSource`). Keeps the CLI wiring in `cmd_harness` short and lets tests bypass discovery by passing `question_resolvers=[MockResolver()]` directly.

**Alternatives considered**:
- Auto-append discovered resolvers even when `--interactive` isn't passed: rejected -- surprising behavior; a fleet operator running non-interactive shouldn't have a random third-party resolver start prompting them. Non-interactive default = empty chain unless the operator asks for one.
- Merge `AnswerSource` and `QuestionResolver` behind one Protocol: rejected already in clarify (Q1 discussed the semantic difference); noting here for the record.

## R8. Backwards compatibility with existing 026 tests

**Decision**: Every feature-026 test that constructs a `HarnessRun` today does so WITHOUT `question_resolvers`. The default (empty list) means no resolver phase runs; `_collect_unanswered` behaves exactly as it does today for those cases. The "no re-audit after collect" invariant test (test_answered_question_does_not_change_control_status_in_mvp) is unchanged and MUST still pass.

Adding `question_resolvers` to the driver is additive; the report gains fields (`resolvers_used`, `resolution_trail`) but they default to empty lists / not-emitted so existing golden-file tests only need to be updated if they assert on exact JSON shape. Where they do, we update the assertion to match the new (superset) shape and note the reason in the test.

**Rationale**: Feature 027 is genuinely additive to the harness surface; no existing behavior changes when the new features aren't invoked. This is the litmus test for a well-scoped addition.

**Alternatives considered**:
- Only emit `resolution_trail` when non-empty: rejected -- makes JSON-schema conformance testing fussy (field is sometimes present, sometimes not).
- Version the report schema: rejected as over-engineering; a Pydantic model with new fields is the natural evolution.

## Summary of Phase 0 outcome

- No NEEDS CLARIFICATION remaining from the spec (all resolved in clarify).
- Every technical unknown for Phase 1 design work has a concrete decision above.
- No new runtime dependencies. stdlib + existing deps only.
- Test surface: injectable streams for `/dev/tty`, external fixture package for entry-point discovery, `MockQuestionResolver` for driver-level chain tests, `_redact_secrets` reuse for error-trail sanitization.
- Constitution IV interaction: interactive answer = `authority: "asserted"`; "no re-audit after collect" MVP policy from feature 026 stays intact.
