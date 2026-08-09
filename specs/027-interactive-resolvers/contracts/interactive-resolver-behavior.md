# Contract: `InteractiveTerminalResolver` Behavior

**Feature**: 027-interactive-resolvers | **Consumers**: fleet operators running `darnit harness --interactive` and tests exercising the terminal behavior.

The Protocol contract in `question-resolver-protocol.md` covers what ALL resolvers must do. This contract covers the specific behavior of the reference implementation shipping in darnit-core.

## 1. Registration + naming

- **IR-1**: The resolver's `name` is the literal string `"interactive_terminal"`.
- **IR-2**: The resolver is registered by darnit-core itself as an entry point in `darnit.question_resolvers`. Operators do not need to install a separate package.
- **IR-3**: The CLI flag `--interactive` on `darnit harness` is equivalent to placing this resolver at the head of the resolver chain.

## 2. Channel

- **IR-4**: The resolver writes prompts to and reads answers from `/dev/tty`. Both directions use the same file descriptor pair.
- **IR-5**: The resolver MUST NOT write to `sys.stdout` or `sys.stderr` at any point during `resolve()`. Feature-026 stream contracts (stdout = report body, stderr = progress + exit summary) are preserved.
- **IR-6**: If `/dev/tty` cannot be opened (detached process, unusual chroot, non-POSIX platform), the resolver raises `HarnessSetupError` at first invocation. The CLI translates this to exit code 2 (`SETUP_ERROR`) with a stderr summary naming the missing channel.

## 3. Availability guard (fail-fast)

- **IR-7**: `cmd_harness` with `--interactive` MUST verify BOTH conditions BEFORE any control runs:
  - `sys.stdin.isatty()` returns True
  - `open("/dev/tty", "r+")` succeeds
- **IR-8**: Either check failing results in exit code 2 within 2 seconds. Stderr summary includes the phrase `interactive channel unavailable` and identifies whether stdin-not-TTY or `/dev/tty`-not-openable was the cause.
- **IR-9**: The guard exists so a CI environment invoking `--interactive` cannot silently degrade to a run that skips every question.

## 4. Prompt payload

- **IR-10**: Each prompt payload written to `/dev/tty` MUST include, in order:
  1. A blank line (separator from any previous prompt)
  2. A position header: `[N of M]` where `N` is the 1-indexed question number and `M` is the total pending
  3. The control identifier on its own line (e.g. `STAGE1-REF-SECURITY-01`)
  4. The question text, wrapped to a reasonable line width (target: 80 chars, but wrapping is a plan-phase detail)
  5. Any control-level help text available, indented (target: 2 spaces) and preceded by a `Help:` marker line
  6. A prompt line ending in `> ` (chevron + single space) with no trailing newline, so the operator's input appears on the same line

- **IR-11**: The prompt payload MUST NOT include:
  - The `Answer.value` from any previously answered question (privacy)
  - The API key from `ANTHROPIC_API_KEY` or any environment variable
  - The resolver's `name` (redundant; the operator knows they're in `--interactive` mode)

- **IR-12**: The exact byte sequence of a prompt for a given `(control_id, question, help_text, position)` tuple is LOCKED by a golden-file test at implementation time. Format changes require updating the golden.

## 5. Input handling

- **IR-13**: The resolver reads one line at a time via `readline()`. The trailing newline is stripped. The stripped result is the operator's raw input.
- **IR-14**: `.strip()` is applied to the raw input to normalize surrounding whitespace.
- **IR-15**: If the stripped input is empty (Enter pressed, or only whitespace typed), the resolver returns `None` (SKIP). Per FR-006 and FR-006a. No `Answer` is constructed.
- **IR-16**: If the stripped input is non-empty, the resolver returns `Answer(value=<stripped>, origin="interactive_terminal")`. The `value` is the stripped string; leading/trailing whitespace is not preserved (they are almost certainly typos).

## 6. Interrupt handling

- **IR-17**: `readline()` raising `KeyboardInterrupt` (Ctrl+C) causes the resolver to raise `InteractiveAborted`. The driver's collect loop catches this and stops offering further questions to any resolver.
- **IR-18**: `readline()` returning empty string (EOF / Ctrl+D) is treated identically to Ctrl+C -- raises `InteractiveAborted`.
- **IR-19**: The resolver DOES NOT install any signal handlers. The `KeyboardInterrupt` machinery is Python's default; the resolver just reacts to what surfaces from `readline()`.

## 7. Lifecycle

- **IR-20**: The `/dev/tty` file handle is opened lazily on first `resolve()` call, not in `__init__`. This allows tests to construct the resolver without touching `/dev/tty`.
- **IR-21**: The resolver exposes a `close()` method that closes the `/dev/tty` handle. `_collect_unanswered` calls it after finishing the interactive phase (or on `InteractiveAborted`).
- **IR-22**: Calling `close()` twice is a no-op (idempotent). Calling `resolve()` after `close()` raises `RuntimeError`.

## 8. Test-injectable streams

- **IR-23**: `InteractiveTerminalResolver(input_stream=..., output_stream=...)` uses the provided streams verbatim. `/dev/tty` is NOT opened when either argument is non-`None`.
- **IR-24**: Test code SHOULD pass `io.StringIO` for both streams. Writing to `output_stream` and reading from `input_stream` behaves identically to writing to and reading from `/dev/tty`.
- **IR-25**: Neither `input_stream` nor `output_stream` is a supported production configuration. The two-argument constructor exists exclusively for tests.

## 9. Trail contribution

- **IR-26**: An interactively answered question produces one trail entry with `outcome: "answered"` and `Answer.origin: "interactive_terminal"`.
- **IR-27**: A skipped question (empty input, or whitespace-only) produces one trail entry with `outcome: "skipped"` and no `error_summary`.
- **IR-28**: Ctrl+C mid-question produces one trail entry with `outcome: "skipped"` for that question. Questions the driver never got to offer (because collection was aborted) get NO trail entry -- they simply remain pending in the report with an empty `resolution_trail`.

## 10. Non-goals for MVP

- **IR-29**: No line editing (arrow keys, history, tab-completion). Vanilla `readline()`; the operator types and hits Enter.
- **IR-30**: No colored output, no ANSI escapes, no `rich`/`click`. Terminal ergonomics beyond plain text are out of scope.
- **IR-31**: No confirmation prompt ("You entered X, confirm? y/n"). The operator's Enter is the confirmation. If they typo, they can leave the question pending in a later run by editing `.project/project.yaml` -- this feature is about first-pass collection, not correction.
