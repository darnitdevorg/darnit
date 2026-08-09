---
description: "Tasks for feature 027: Interactive Question Resolvers -- extensible resolver Protocol for `darnit harness`"
---

# Tasks: Interactive Question Resolvers

**Input**: Design documents from `specs/027-interactive-resolvers/`

**Prerequisites**: plan.md (loaded), spec.md (loaded, 5 clarifications), research.md (loaded, 8 decisions), data-model.md (loaded), contracts/{question-resolver-protocol,interactive-resolver-behavior,resolution-trail-schema}.md (loaded), quickstart.md (loaded)

**Tests**: Test tasks included. Every FR and SC has explicit test coverage. SC-002 (extensibility -- resolver defined outside `packages/darnit/src/darnit/harness/`), SC-003 (interactive answers = `authority: "asserted"`), SC-004 (Ctrl+C preserves collected answers), SC-005 (non-TTY / no-/dev/tty fail-fast), SC-007 (resolver-exception isolation), SC-008 (exactly two bookend lines), SC-009 (three-outcome trail) are load-bearing.

**Organization**: Tasks are grouped by user story per spec.md. Feature 026's invariants (especially "no re-audit after collect") MUST continue to pass unchanged.

**Branch base**: `026-harness-with-stage1` (PR #365, still open at time of writing). Rebase to `main` after PR #365 merges. Do NOT branch this from `main` directly -- feature 027 depends on 026's `HarnessRun`, `PendingFeedbackEntry`, and `_redact_secrets`.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Parallelizable with other [P] tasks in the same phase (different files, no deps on unfinished tasks)
- **[Story]**: Which user story (US1, US2, US3)
- File paths are exact and repository-relative

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the external-fixture package and update `pyproject.toml` so entry-point discovery has something concrete to find. No new runtime dependencies (this feature is stdlib-only on the production surface).

- [X] T001 Create `tests/darnit/harness/fixtures/mock_resolver_pkg/` directory. Add a minimal `pyproject.toml` declaring `[project] name = "mock-resolver-pkg"` and a `[project.entry-points."darnit.question_resolvers"]` block that registers `mock_answer = "mock_resolver_pkg.resolvers:build_answer"` and `mock_error = "mock_resolver_pkg.resolvers:build_error"`. Include `[tool.hatch.build.targets.wheel] packages = ["mock_resolver_pkg"]`.

- [X] T002 [P] Create `tests/darnit/harness/fixtures/mock_resolver_pkg/mock_resolver_pkg/__init__.py` (empty) and `resolvers.py`. Implement `AnsweringResolver` (returns `Answer(value="fixed", origin="mock_answer")`) and `ErroringResolver` (raises `RuntimeError("fixture failure")`). Add module-level `build_answer()` and `build_error()` factory functions returning fresh instances. Import `Answer` and `QuestionResolver` from `darnit.harness.question_resolvers` (dep on Phase 2).

- [X] T003 [P] Update `packages/darnit/pyproject.toml` to declare `[project.entry-points."darnit.question_resolvers"] interactive_terminal = "darnit.harness.interactive_resolver:build"`. Note: Python entry-point declarations are LAZY -- the referenced module is only loaded when `importlib.metadata` iterates entry points AND the caller invokes `ep.load()`. Declaring a target module that will be created later in Phase 3 (T008) is not an install-time error. Discovery gracefully skips broken entry points per contract QR-16.

**Checkpoint**: External fixture package installable via `uv pip install -e tests/darnit/harness/fixtures/mock_resolver_pkg`; darnit-core's own `interactive_terminal` entry point is declared.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the shared Protocol, entities, and exception types that ALL three user stories depend on. Each task creates a self-contained module.

**CRITICAL**: No user-story tasks can proceed until this phase is complete.

- [X] T004 Create `packages/darnit/src/darnit/harness/question_resolvers.py`. Define:
    - `Answer` (Pydantic `BaseModel` with `extra="forbid"`; fields `value: str`, `origin: str`, `authority: Literal["asserted"] = "asserted"`; per data-model.md section 2). The `Literal["asserted"]` with a fixed default enforces FR-009 / SC-003 at the model level -- resolver authors physically cannot construct an `Answer` with a different authority; Pydantic raises a validation error at construction time.
    - `ResolutionTrailEntry` (Pydantic `BaseModel` with `extra="forbid"`; fields `resolver_name: str`, `outcome: Literal["answered", "skipped", "errored"]`, `error_summary: str | None = None`; cross-field validator: `error_summary` required iff `outcome == "errored"`; per data-model.md section 3)
    - `QuestionResolver` (`@runtime_checkable` Protocol with `name: str` and `async def resolve(question) -> Answer | None`; per data-model.md section 1 + contract QR-1..QR-4)
    - `InteractiveAborted` (Exception subclass; docstring per data-model.md section 8)
    - `__all__` tuple exporting the four names above.
    Docstring: cite feature 027 spec + contracts.

- [X] T005 [P] Create `tests/darnit/harness/test_question_resolvers.py`. Tests:
    - `Answer` accepts non-empty strings; rejects `extra` keys (Pydantic extra=forbid).
    - `Answer(value="v", origin="o")` produces `authority == "asserted"` by default (SC-003 at the model layer).
    - `Answer(value="v", origin="o", authority="dispositive")` raises `ValidationError` (Literal enforcement).
    - `Answer(value="v", origin="o", authority="suggestive")` raises `ValidationError`.
    - `ResolutionTrailEntry` accepts each of the three outcomes.
    - `ResolutionTrailEntry` requires `error_summary` when `outcome == "errored"` (cross-field validation fails otherwise).
    - `ResolutionTrailEntry` forbids `error_summary` when `outcome` is `"answered"` or `"skipped"`.
    - A test class with `name` and async `resolve` passes `isinstance(x, QuestionResolver)`.
    - A test class MISSING `resolve` fails `isinstance` (proves the Protocol shape).
    - Serialization round-trip for `Answer.model_dump_json()` and `ResolutionTrailEntry.model_dump_json()` (baseline for schema stability). Assert `authority: "asserted"` appears in the serialized `Answer` JSON.

- [X] T006 [P] Create `tests/darnit/harness/test_protocol_conformance.py`. Contract tests QR-1..QR-27 from `contracts/question-resolver-protocol.md`:
    - QR-1..QR-4: `name` + `resolve` shape + `isinstance` recognition
    - QR-5, QR-6: `None` return -> skip semantics; `Answer(value="x")` -> answered semantics (verified via `MockQuestionResolver` and driver's collect path -- deferred to T023 for the driver-level part; T006 covers the boundary)
    - QR-9, QR-10: exception passes through as `errored`; `KeyboardInterrupt` NOT caught inside `resolve()` of programmatic resolvers
    - QR-26: Protocol shape v1 is exactly what's exported from `question_resolvers.py`
    Uses `MockAnsweringResolver`, `MockSkippingResolver`, `MockErroringResolver` fixtures defined in `tests/darnit/harness/conftest.py` (see T007).

- [X] T007 [P] Update `tests/darnit/harness/conftest.py` to add three feature-027 fixtures:
    - `mock_answering_resolver` -- yields a fresh instance of a resolver that returns `Answer(value="mock-answer", origin="mock_answering")`
    - `mock_skipping_resolver` -- yields one that returns `None`
    - `mock_erroring_resolver(exception_message="mock error")` -- factory fixture; yields a resolver whose `resolve()` raises `RuntimeError(exception_message)`
    Every fixture's resolver satisfies `isinstance(r, QuestionResolver)` (i.e., has `name` and async `resolve`).

**Checkpoint**: `uv run pytest tests/darnit/harness/test_question_resolvers.py tests/darnit/harness/test_protocol_conformance.py -q` passes. Entities and Protocol are locked; downstream code can import from `darnit.harness.question_resolvers`.

---

## Phase 3: User Story 1 -- Operator answers live at the terminal (P1) 🎯 MVP

**Goal**: `darnit harness <path> --interactive` at a TTY prompts the operator per pending question, records answers with `origin: "interactive_terminal"`, and preserves them across Ctrl+C.

**Independent Test**: Run the harness against a fixture repo with two pending questions on a scripted "TTY" (test-injectable streams); answer one, skip the other. The report shows one answered question with `origin: "interactive_terminal"`, one still-pending question, and no additional YAML file was needed.

### Implementation for US1

- [X] T008 [US1] Create `packages/darnit/src/darnit/harness/interactive_resolver.py`. Implement `InteractiveTerminalResolver` per contract `interactive-resolver-behavior.md`:
    - `name = "interactive_terminal"` (class attribute)
    - `__init__(self, input_stream=None, output_stream=None)` -- store streams; do NOT open `/dev/tty` here
    - `_open_tty()` -- lazily open `/dev/tty` in mode `"r+", buffering=1` on first `resolve()`. On `OSError` / `FileNotFoundError`, raise `HarnessSetupError` (imported from `darnit.harness.driver`) with message "interactive channel unavailable (/dev/tty not openable)".
    - `_format_prompt(question, position, total)` -- produce the exact byte sequence specified by IR-10 (blank line, `[N of M]`, control_id line, question text, optional `Help: ...` indented, `> ` chevron with no newline).
    - `async def resolve(question)` -- accepts an optional out-of-band `position` and `total` (see T009 for how the driver threads these in); writes prompt via `_format_prompt`; calls `readline()`; on `KeyboardInterrupt` raise `InteractiveAborted`; on empty `readline()` return raise `InteractiveAborted` (EOF/Ctrl+D); strip result; empty-after-strip -> return `None`; non-empty -> return `Answer(value=stripped, origin="interactive_terminal")`.
    - `close()` -- close `/dev/tty` handle idempotently. Subsequent `resolve()` raises `RuntimeError("resolver is closed")`.
    - Module-level `def build() -> InteractiveTerminalResolver: return InteractiveTerminalResolver()` (entry-point factory).
    - `__all__ = ("InteractiveTerminalResolver", "build")`.

- [X] T009 [US1] Update `packages/darnit/src/darnit/harness/driver.py`:
    - Add `question_resolvers: list[QuestionResolver] = field(default_factory=list)` to `HarnessRun` dataclass (per data-model.md section 7).
    - Add `per_resolver_timeout_s: float | None = None` to `HarnessRun` dataclass (per data-model.md section 7). Enforces FR-011.
    - Extend `_collect_unanswered` per research.md R6:
      - If `question_resolvers` is empty, current 026 behavior is preserved.
      - Otherwise: emit bookend log line `harness: starting interactive collection (%d pending questions)` on `darnit.harness` INFO.
      - Iterate remaining pending questions. For each, iterate `question_resolvers` in order. Thread `(position, total)` into the interactive resolver via a private branch (`isinstance(r, InteractiveTerminalResolver)` -> pass extra args; other resolvers get the question alone -- see design note in T009's docstring).
      - Wrap each `resolver.resolve(...)` call in `asyncio.wait_for(..., timeout=self.per_resolver_timeout_s)` when `per_resolver_timeout_s is not None`. On `TimeoutError`, append `ResolutionTrailEntry(outcome="errored", error_summary=f"resolver timed out after {self.per_resolver_timeout_s}s")` and continue to next resolver.
      - Catch: `Answer` with non-empty stripped value -> record answered; append `ResolutionTrailEntry(outcome="answered")`; set the parent `PendingFeedbackEntry.answer_authority = "asserted"` (per data-model.md section 5); break inner loop for this question.
      - `None` or `Answer` with empty/whitespace-only value -> append `ResolutionTrailEntry(outcome="skipped")`; continue to next resolver.
      - `InteractiveAborted` -> append `ResolutionTrailEntry(outcome="skipped")`; break BOTH loops (stop offering further questions to any resolver).
      - Any other `Exception` -> log warning; append `ResolutionTrailEntry(outcome="errored", error_summary=_redact_secrets(str(exc))[:200])`; continue to next resolver.
      - Close any resolver that exposes a `close()` method after collection.
    - Emit closing bookend `harness: finished interactive collection: %d answered, %d skipped, %d aborted` on INFO.
    - No `darnit.harness` log record emitted BETWEEN the two bookends contains any resolver-supplied value (FR-013 preservation). The bookends themselves reference counts only, never values.
    - MUST NOT re-audit any control (feature 026 no-reaudit invariant preserved).

- [X] T010 [US1] Update `packages/darnit/src/darnit/harness/report.py`:
    - Add `resolvers_used: list[str] = Field(default_factory=list)` to `HarnessReport`.
    - Add `resolution_trail: list[ResolutionTrailEntry] = Field(default_factory=list)` to `PendingFeedbackEntry`.
    - Add `answer_authority: Literal["asserted"] | None = None` to `PendingFeedbackEntry` per data-model.md section 5. Cross-field model validator: `answer_authority == "asserted"` required when `answered == True`; `answer_authority is None` required otherwise.
    - `to_json()` emits `resolvers_used`, `resolution_trail`, and `answer_authority` unconditionally (empty arrays / None when unused).
    - `to_markdown()`:
      - Emits a "Resolvers used" bullet list section immediately after "Answer sources used" ONLY if `resolvers_used` is non-empty.
      - For each `PendingFeedbackEntry` with a non-empty `resolution_trail`, renders a nested "Resolution trail:" list per contract `resolution-trail-schema.md` section 6.
      - Answered entries display their `answer_authority` inline (e.g., `Answered: security@example.com (asserted)`) so a human reader sees the provenance without diving into the JSON.

- [X] T011 [US1] Update `packages/darnit/src/darnit/cli.py` (`cmd_harness`):
    - Add `--interactive` boolean flag (default `False`) to the subparser.
    - Availability guard BEFORE `HarnessRun.run()` is invoked: if `--interactive`, verify (a) `sys.stdin.isatty()` returns True AND (b) `open("/dev/tty", "r+")` succeeds. Failure -> exit 2 within 2s with stderr summary `harness: setup_error: interactive channel unavailable (<cause>), exit 2` per contract IR-7/IR-8/IR-9.
    - On success: construct the resolver chain via `HarnessRun.build_default_resolver_chain(interactive=True)` (see T017 -- for MVP-first ordering, T011 constructs the interactive resolver directly if T017 not yet done, then swaps to the classmethod).
    - No new required arguments beyond `--interactive`.

### Tests for US1

- [X] T012 [P] [US1] Create `tests/darnit/harness/test_interactive_resolver.py`. Cover contract IR-1..IR-31:
    - IR-1: `resolver.name == "interactive_terminal"`
    - IR-4/IR-5: with test-injected streams, prompt output lands in `output_stream` and NOTHING is written to `sys.stdout` or `sys.stderr`. Assert both are empty via `capsys`.
    - IR-6: (mocking) `open("/dev/tty", ...)` raises -> `HarnessSetupError` from first `resolve()` call.
    - IR-10: golden-file test -- construct a `FeedbackQuestion(control_id="OSPS-GV-01.01", context_key="security_contact", question="Who is the security contact?", ...)`, call `_format_prompt(question, position=2, total=5)`, assert output exactly matches `tests/darnit/harness/fixtures/prompt_golden.txt`. Create the golden file as part of this task.
    - IR-11: prompt must NOT contain any answer from a previous question OR the string of any env var; test with a distinctive `ANTHROPIC_API_KEY` set.
    - IR-13..IR-16: input handling -- typed answer, empty input (skip), whitespace-only input (skip), leading/trailing whitespace stripped.
    - IR-17/IR-18: `KeyboardInterrupt` from `readline()` -> `InteractiveAborted`; empty-string return (EOF) -> `InteractiveAborted`.
    - IR-22: `close()` twice is a no-op; `resolve()` after `close()` -> `RuntimeError`.

- [X] T013 [P] [US1] Create `tests/darnit/harness/test_resolution_trail.py`. Cover SC-009, contract RT-1..RT-14:
    - RT-1: every `PendingFeedbackEntry` in a report has a `resolution_trail` field (may be empty).
    - RT-6..RT-9: `outcome == "errored"` requires `error_summary`; only one `"answered"` entry per trail and it is the last.
    - SC-009: register three resolvers (first errors, second skips, third answers) against one pending question; assert trail contains three entries in that order with the expected outcomes.
    - RT-10 + RT-11: an erroring resolver whose `str(exc)` contains `sk-ant-fake-KEY-1234567890` produces a trail entry whose `error_summary` DOES NOT contain the key literal (redacted); length <= 200.

- [X] T014 [P] [US1] Update `tests/darnit/harness/test_driver.py`. Add a new class `TestQuestionResolverChain`:
    - Injecting a `MockAnsweringResolver` into `HarnessRun.question_resolvers` -> pending question resolved; report's `answered` field is True; report's `answer_authority == "asserted"` (SC-003 end-to-end assertion); trail entry has `outcome="answered"`; `origin` is the resolver's own value.
    - Injecting a `MockSkippingResolver` FOLLOWED by a `MockAnsweringResolver` -> question resolved by the second; trail has two entries in order (skipped, answered).
    - Injecting a `MockErroringResolver` FOLLOWED by a `MockAnsweringResolver` -> question resolved by the second; trail has two entries (errored, answered); error resolver's exception does NOT propagate to caller (SC-007).
    - Injecting resolvers but NO pending questions -> chain is not invoked; bookend lines are NOT emitted; report's `resolvers_used` still lists them.
    - **Bookend count (SC-008)**: With N pending questions and an injected `MockAnsweringResolver`, capture all `darnit.harness` log records via `caplog`. Assert exactly one record starting with `harness: starting interactive collection (` and exactly one starting with `harness: finished interactive collection: `. Assert ZERO records between them match the `[N/M]` per-control progress-line pattern from feature 026.
    - **Programmatic empty-Answer skip (FR-006a / M1)**: A resolver that returns `Answer(value="", origin="x")` -> caught at the driver layer, trail entry has `outcome="skipped"` (NOT `"answered"`); question stays pending; `answer_authority` remains `None`. Same test with `Answer(value="   ", origin="x")` (whitespace-only).
    - **No values in progress logs (FR-013 / M2)**: A `MockAnsweringResolver` that returns `Answer(value="DISTINCTIVE-VALUE-XYZ-123", origin="mock")` -> assert NO `darnit.harness` log record contains the literal `DISTINCTIVE-VALUE-XYZ-123`. Mirrors feature 026's API-key-redaction pattern (`test_api_key_never_appears_in_stderr`).
    - **Per-resolver timeout (FR-011)**: With `HarnessRun.per_resolver_timeout_s=0.05` and a resolver whose `resolve()` awaits `asyncio.sleep(0.5)` -> trail entry has `outcome="errored"`, `error_summary` contains the substring `timed out`, the driver moves on to the next resolver (or leaves pending if no more).
    - The existing `test_answered_question_does_not_change_control_status_in_mvp` test (feature 026 no-reaudit invariant) MUST still pass unmodified when a resolver chain provides the answer -- add a variant asserting the same invariant with a resolver-provided answer.

- [X] T015 [P] [US1] Update `tests/darnit/harness/test_cli.py`. Add a new class `TestInteractiveFlag`:
    - SC-005: `--interactive` under non-TTY stdin (piped from a `StringIO`-backed input; use `monkeypatch.setattr(sys, "stdin", ...)`) -> exit 2 in <2s; stderr summary contains `interactive channel unavailable` and either `stdin is not a TTY` or `/dev/tty not openable`; ZERO `[N/M]` progress lines emitted before the setup_error line.
    - SC-005 variant: `--interactive` with stdin-is-TTY but `open("/dev/tty", ...)` mocked to raise -> exit 2 with the `/dev/tty not openable` variant of the error message.
    - `--interactive` with a mocked TTY and injected `MockAnsweringResolver` via `HarnessRun.question_resolvers=[...]` (test-only path bypassing the CLI's resolver-chain construction) -> exit 0; report's `resolvers_used` contains `"interactive_terminal"`.

- [X] T016 [P] [US1] Update `tests/darnit/harness/test_report.py`. Add:
    - JSON emission includes `resolvers_used: []`, per-`PendingFeedbackEntry.resolution_trail: []`, and `answer_authority: null` when unused (RT-1, RT-2).
    - JSON round-trip: build a `HarnessReport` with a trail containing all three outcomes AND one answered entry with `answer_authority: "asserted"`; `HarnessReport.model_validate_json(r.to_json())` reproduces it.
    - Markdown emission: with `resolvers_used=["interactive_terminal"]`, a "Resolvers used" section appears. With an empty `resolvers_used`, no such section.
    - Markdown emission: with a non-empty `resolution_trail`, the "Resolution trail:" nested list renders per contract section 6.
    - Markdown emission: an answered entry shows `answer_authority` inline (e.g., `Answered: security@example.com (asserted)`).
    - **Reconstructibility (SC-006 / M3)**: Build a `HarnessReport` with three trail entries produced by three named resolvers; serialize to JSON via `to_json()`; parse the JSON via `json.loads` (NOT via `HarnessReport.model_validate_json`, to simulate an external consumer that doesn't have the Pydantic model); iterate `pending_feedback[0].resolution_trail` and reconstruct the resolver chain as an ordered list of `(name, outcome)` pairs. Assert the reconstruction matches the input exactly. Proves that a report reader can trace how each value was obtained using only the JSON.
    - Pydantic cross-field validator on `PendingFeedbackEntry`: `answered=True` with `answer_authority=None` raises ValidationError. `answered=False` with `answer_authority="asserted"` also raises.

**Checkpoint**: `uv run darnit harness /path/to/repo --interactive` at a real TTY prompts the operator; skipped/answered questions are captured in the report; Ctrl+C preserves collected answers. US1 is independently shippable if we stop here.

---

## Phase 4: User Story 2 -- Third-party author writes a custom resolver (P2)

**Goal**: A resolver defined OUTSIDE `packages/darnit/src/darnit/harness/` is discovered via Python entry points and invoked by the harness with no code changes under that directory.

**Independent Test**: SC-002 -- add a resolver as the fixture package (Phase 1's `mock_resolver_pkg`), install it via `uv pip install -e ...`, run the harness, and observe the resolver being invoked. The test file lives outside `packages/darnit/src/darnit/harness/`; assertions do not modify anything under that directory.

### Implementation for US2

- [X] T017 [US2] Create `packages/darnit/src/darnit/harness/resolver_discovery.py`. Implement per research.md R2:
    - `def discover_registered_resolvers() -> dict[str, QuestionResolver]`:
      - Call `importlib.metadata.entry_points(group="darnit.question_resolvers")`.
      - For each entry: `ep.load()` inside try/except; on success, call the returned factory (zero args); verify `isinstance(instance, QuestionResolver)`; on any failure log a WARNING with the entry-point name and skip.
      - Return `{ep.name: instance}` dict.
    - `def build_default_resolver_chain(interactive: bool) -> list[QuestionResolver]` (this is the module-level function; the `HarnessRun.build_default_resolver_chain` classmethod delegates):
      - Discover all registered resolvers.
      - If `interactive` is True: put the `interactive_terminal` resolver first (raise `HarnessSetupError` if not discovered).
      - Append every OTHER resolver in `importlib.metadata` discovery order.
      - Return the list.
    - Docstring cites contract QR-14..QR-16 and R2.

- [X] T018 [US2] Update `packages/darnit/src/darnit/harness/driver.py`:
    - Add `@classmethod def build_default_resolver_chain(cls, interactive: bool)` that delegates to `resolver_discovery.build_default_resolver_chain`.

- [X] T019 [US2] Update `packages/darnit/src/darnit/cli.py` (`cmd_harness`):
    - Replace the direct `InteractiveTerminalResolver()` construction from T011 (if used) with `HarnessRun.build_default_resolver_chain(interactive=args.interactive)`.
    - Emit an INFO log line at CLI startup listing the resolvers configured for this run: `harness: resolvers configured: [interactive_terminal, gh_issue_comment, ...]`. This lands on `darnit.harness` before the audit begins.

### Tests for US2

- [X] T020 [P] [US2] Create `tests/darnit/harness/test_resolver_discovery.py`:
    - `discover_registered_resolvers()` returns a dict whose keys include `interactive_terminal` (registered by darnit-core itself in `pyproject.toml`).
    - With the `mock_resolver_pkg` fixture package installed (add a session-scope fixture that runs `uv pip install -e tests/darnit/harness/fixtures/mock_resolver_pkg` OR uses `importlib.metadata`-monkeypatching per pytest recipe), `discover_registered_resolvers()` returns `mock_answer` and `mock_error` alongside `interactive_terminal`.
    - A broken entry point (module that raises `ImportError` on load, mocked via `unittest.mock.patch` on `importlib.metadata`) is skipped with a WARNING but does not crash discovery; other entry points still register.
    - `build_default_resolver_chain(interactive=True)` returns a list where `interactive_terminal` is first.
    - `build_default_resolver_chain(interactive=False)` returns a list where `interactive_terminal` is NOT present (only third-party resolvers).

- [X] T021 [P] [US2] Create `tests/darnit/harness/test_extensibility_sc002.py` (SC-002 enforcement):
    - Assert that no file under `packages/darnit/src/darnit/harness/` was modified to enable the `mock_resolver_pkg` fixture's resolver to be invoked. Concretely: import the fixture's resolver, register it via a `HarnessRun.question_resolvers=[fixture_resolver]` injection, run the harness against a repo with one pending question, and assert the resolver's answer appears in the report.
    - The test itself lives in `tests/`, not in `packages/darnit/src/darnit/harness/`.
    - Include a directory-hash sanity check that lists files under `packages/darnit/src/darnit/harness/` and asserts none were modified during test execution (using `os.path.getmtime` before/after -- optional, use if the CI test flakiness allows).

**Checkpoint**: A wheel outside darnit-core can register a `QuestionResolver` via entry point and be invoked by the harness. SC-002 mechanically holds.

---

## Phase 5: User Story 3 -- Combining `--answers` file and `--interactive` (P3)

**Goal**: `--answers` file first, `--interactive` fills gaps. Each answered question shows its own origin in the report.

**Independent Test**: Fixture repo with three pending questions; `answers.yaml` covers one; run with `--answers ... --interactive` on a mock TTY that answers one prompt and skips the other. The report shows one answer from the file (origin `--answers <file>`), one from interactive (origin `interactive_terminal`), and one still pending.

### Implementation for US3

- [X] T022 [US3] Verify the AnswerSource -> QuestionResolver ordering in `_collect_unanswered` (contract QR-19). Read the updated `_collect_unanswered` from T009 and produce a one-paragraph review comment in the PR description confirming (a) the AnswerSource pass runs first, (b) only questions still-pending after that pass are offered to `question_resolvers`, and (c) the ordering is documented in an inline code comment referencing QR-19. If ordering is WRONG, open a bug against T009 and block T023/T024 until fixed. Deliverable: the review paragraph (in the PR desc) OR a follow-up commit fixing the ordering.

### Tests for US3

- [X] T023 [P] [US3] Update `tests/darnit/harness/test_driver.py`. Add a class `TestComposition`:
    - Seed `.project/project.yaml` with `security_contact: from_project@example.com` (one question answered by AnswerSource).
    - Seed an `--answers` file with `code_of_conduct_url: from_answers` (another question answered by AnswerSource; two-source ordering).
    - Inject `MockAnsweringResolver` (would answer any question with `"mock"`, origin `"mock"`).
    - Assert: the two questions covered by AnswerSource are answered with the file/project origins; the third gets answered by the resolver with origin `"mock"`; the report's `answer_sources_used` and `resolvers_used` both appear; `resolution_trail` is EMPTY for the two AnswerSource-answered questions (resolver was never offered them) and has exactly one `answered` entry for the third.

- [X] T024 [P] [US3] Update `tests/darnit/harness/test_cli.py`. Add:
    - `--answers <file> --interactive` invocation with two pending questions -- one covered by the file, one uncovered. With test-injected TTY streams answering the uncovered one, assert the report shows both answered, each with their own origin.

**Checkpoint**: File + interactive compose. US3 is verified.

---

## Phase 6: Polish & Cross-Cutting

**Purpose**: Docs, quickstart validation, and a final end-to-end sanity pass.

- [X] T025 [P] Update `packages/darnit/src/darnit/harness/__init__.py` to re-export the new public names: `QuestionResolver`, `Answer`, `ResolutionTrailEntry`, `InteractiveAborted`, `InteractiveTerminalResolver`, `discover_registered_resolvers`, `build_default_resolver_chain`. Preserve existing 026 re-exports.

- [X] T026 [P] Add feature 027 entry to `CLAUDE.md`'s "Recent Changes" section (top of the list). One-paragraph summary describing the QuestionResolver Protocol seam, the InteractiveTerminalResolver reference implementation, and the `--interactive` CLI flag.

- [X] T027 [P] Run `uv run ruff check .` and `uv run ruff format --check .` on the whole workspace. Fix any lint issues introduced by the new code.

- [X] T028 [P] Run `uv run python scripts/validate_sync.py --verbose` and address any handler-name / spec-sync failures. Feature 027 doesn't add controls but a validate_sync pass keeps us honest.

- [ ] T029 [P] Manual quickstart verification against a real repo. Run through `specs/027-interactive-resolvers/quickstart.md` end-to-end on a repo with at least three pending questions; capture the run output; verify: two bookend lines on stderr, position indicators in prompts, Ctrl+C preserves answers, report contains `resolution_trail` for each answered question. Not automated; produces a manual-sign-off note added to the PR description.

- [X] T030 [P] Full test sweep: `uv run pytest tests/ -q`. Expected: 2533 + new feature-027 tests all pass, 15 skipped (feature 026 baseline). No regressions in feature 025 or feature 026 tests.

- [ ] T031 Write the PR description. Structure per `feedback_no_ai_signoff.md`: no Co-Authored-By trailer, no Generated with Claude Code footer. Include a summary, the two new commits' rationale, test plan, and links to spec.md + plan.md.

---

## Dependencies & Story Completion Order

```
Phase 1 (T001-T003)  --setup--
        |
        v
Phase 2 (T004-T007)  --foundational: Protocol + entities--
        |
        +-----+---------------------+
        v     v                     v
     Phase 3 (T008-T016)     Phase 4 (T017-T021)     [independent of each other after Phase 2]
     US1 -- MVP              US2 -- extensibility
        |     |                     |
        +-----+---------------------+
              v
          Phase 5 (T022-T024)  --composition--
                  |
                  v
              Phase 6 (T025-T031)  --polish--
```

- **Phase 1 tasks are parallelizable** (T001, T002 [P], T003 [P]) but T002 depends on Phase 2's `question_resolvers.py` for its imports. Reorder as: T001, T003 first; T002 after T004.
- **Phase 2 tasks**: T004 first; T005, T006, T007 all [P] after T004.
- **Phase 3 tasks**: T008, T009, T010, T011 must be sequential (they touch overlapping files); T012-T016 are [P] tests that run in parallel after their subjects exist.
- **Phase 4 tasks**: T017 first; T018, T019 depend on T017; T020, T021 are [P] tests after implementation.
- **Phase 5 tasks**: T022 is a code-inspection task; T023, T024 are [P] tests.
- **Phase 6 tasks**: T025-T030 mostly [P]; T031 is last (needs the full picture).

## Parallel Execution Examples

Within Phase 3, once T008-T011 have landed the implementation, run T012, T013, T014, T015, T016 in parallel:

```bash
uv run pytest tests/darnit/harness/test_interactive_resolver.py \
              tests/darnit/harness/test_resolution_trail.py \
              tests/darnit/harness/test_driver.py::TestQuestionResolverChain \
              tests/darnit/harness/test_cli.py::TestInteractiveFlag \
              tests/darnit/harness/test_report.py \
              -q -n auto
```

## Implementation Strategy

**MVP-first order**: Phase 1 -> Phase 2 -> Phase 3 (US1 delivers the operator-visible value). US1 is independently shippable at that point; US2 and US3 layer on top without changing US1's contract.

**Time boxing**: Phase 3 is the largest slice (~5 implementation tasks + 5 test tasks). Phases 4 and 5 combined are smaller than Phase 3. Total estimated size: ~600-800 lines net production + ~600 lines tests. Feature 026 shipped ~1500 net production + ~1600 tests; feature 027 is meaningfully smaller because it composes on top of 026 rather than adding a whole new subsystem.

**Test coverage matrix** (each SC has at least one test task):

| Success Criterion | Test task(s) |
|---|---|
| SC-001 (5 questions in <3 min) | T029 (manual verification) |
| SC-002 (external resolver, no harness edits) | T021 |
| SC-003 (interactive answer = asserted) | T005 (model-layer), T014 (end-to-end), T016 (report shape) |
| SC-004 (Ctrl+C preserves answers) | T012 |
| SC-005 (non-TTY fail-fast) | T015 |
| SC-006 (origin reconstructible) | T013, T016 (external-consumer reconstruction) |
| SC-007 (resolver exception isolation) | T014 |
| SC-008 (exactly two bookend lines) | T014 (bookend-count assertion) |
| SC-009 (three-outcome trail) | T013 |
| FR-006a (programmatic empty Answer skip) | T005 (unit), T014 (driver-level) |
| FR-011 (per-resolver timeout mechanism) | T014 (timeout test with per_resolver_timeout_s=0.05) |
| FR-013 (no answer values in progress logs) | T014 (no-values-in-logs test) |
