# Feature Specification: E2E Regression Baseline for `darnit run` (cmd_run)

**Feature Branch**: `024-cmd-run-e2e-tests`

**Created**: 2026-08-05

**Status**: Draft

**Input**: Issue [#359](https://github.com/darnitdevorg/darnit/issues/359) -- Add E2E tests for `darnit run` (cmd_run) as baseline before harness driver.

## Context

`darnit run` (implemented as `cmd_run` in `packages/darnit/src/darnit/cli.py:631-728`) drives the inline audit -> collect_context -> remediate flow that today executes without an in-process LLM backend. RFC-0001 Stage 1 will replace this codepath with a driver-based Harness abstraction. The command has no end-to-end test coverage, so behavior-preservation across the migration cannot be verified.

This feature adds test-only coverage that pins the observable behavior of `darnit run` as it stands today, so any behavior drift introduced by the harness driver is caught mechanically rather than reported by users.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Golden-path regression pin (Priority: P1)

A maintainer preparing the RFC-0001 Stage 1 harness driver runs the test suite before, during, and after their change. When the harness driver alters the outputs of `darnit run` on a healthy fixture repository -- exit code, printed section labels, per-check totals, absence-of-error signal -- the tests fail with a diff that names the specific field that drifted.

**Why this priority**: Behavior on the healthy path is what users of the current command depend on. Locking it down first gives the migration a green baseline that is meaningful in isolation; the failure-path stories add coverage but do not by themselves prove the shipping behavior is preserved.

**Independent Test**: Run `pytest tests/darnit/cli/test_cmd_run_e2e.py -k golden` against the current `cmd_run`; all assertions pass. Then artificially perturb the exit-code logic at `cli.py:728` (e.g. always return 0) and re-run; the golden-path test fails and its assertion message identifies exit code as the drifted field.

**Acceptance Scenarios**:

1. **Given** a minimal fixture repository that satisfies at least one baseline check and fails none, **When** `cmd_run` is invoked in noninteractive mode with all deterministic controls (no LLM step, no MCP call, no network fetch), **Then** the process exits 0, prints the `Darnit run` header, prints `Run complete.`, and prints total/passed/failed/warned lines with counts consistent with the fixture's expected outcomes.
2. **Given** the same fixture, **When** `cmd_run` completes, **Then** it prints no `Error:` line, no `Pending human feedback` section, and no traceback.
3. **Given** the same fixture, **When** `cmd_run` completes, **Then** its exit code follows the documented rule (`1` if any check failed, `0` otherwise) and this rule is asserted directly against the printed `Failed` count.

---

### User Story 2 - Deterministic-only execution guarantee (Priority: P1)

A CI environment running `darnit run` under noninteractive feedback with no LLM API key configured produces a full result set without ever making an LLM call or an outbound network request. Any regression that would silently introduce a live LLM or network dependency into the deterministic path is caught.

**Why this priority**: The deterministic-only guarantee is the property that makes `darnit run` safe to invoke from CI without special credentials. If the harness driver quietly starts touching the network or an LLM, the failure mode is silent cost/latency/lockup in downstream pipelines, not a visible error. This story must exist for the golden-path pin to be trustworthy.

**Independent Test**: Run the deterministic-guarantee test in isolation with all outbound network syscalls, LLM SDK entry points, and MCP client entry points stubbed to raise. A passing run proves the current code path does not exercise any of them; an added dependency would surface as a raised stub.

**Acceptance Scenarios**:

1. **Given** a fixture repository and a `cmd_run` invocation with `--feedback noninteractive`, **When** every LLM backend entry point and MCP client entry point available to the codebase is stubbed to raise on call, **Then** `cmd_run` completes normally and returns the same exit code it would return without the stubs.
2. **Given** the same invocation, **When** `subprocess.run` for external tools (`gh`, `git subprocess`, other CLI checks) is stubbed to return canned successful output, **Then** `cmd_run` completes without attempting a real network fetch.

---

### User Story 3 - Failure-path exit contract (Priority: P2)

A user invokes `darnit run` against a broken environment -- no framework implementation registered, or a syntactically broken `.project/project.yaml`, or a missing repository path. The command surfaces a diagnostic to stdout/stderr and exits non-zero. The test suite pins which conditions map to exit non-zero versus a printed pending-feedback summary with exit 0, so a change in error-classification is not silently absorbed.

**Why this priority**: Failure-path behavior is what users rely on to distinguish "audit ran and found problems" from "audit could not run." A regression that collapses these into the same exit code, or that reclassifies a real error as a pending-feedback prompt, degrades caller ergonomics without any visible symptom during the migration. Priority is P2 because the failure paths are narrower in scope than the golden path and can land in a follow-up if needed.

**Independent Test**: For each failure condition, invoke `cmd_run` with the environment prepared to trigger it, and assert on exit code plus a substring of the printed diagnostic. Each test fails independently if its specific failure mode changes.

**Acceptance Scenarios**:

1. **Given** a repository path that does not exist, **When** `cmd_run` is invoked with that path, **Then** the process exits non-zero and prints a diagnostic identifying the missing path.
2. **Given** a repository with no discoverable framework implementation (empty plugin registry or no framework requested), **When** `cmd_run` is invoked, **Then** the process exits non-zero and prints a diagnostic naming the missing implementation.
3. **Given** a repository containing a malformed `.project/project.yaml`, **When** `cmd_run` is invoked, **Then** the process exits non-zero and prints a diagnostic naming the config file.
4. **Given** any fixture that produces unanswered feedback questions in noninteractive mode, **When** `cmd_run` completes, **Then** it prints a `Pending human feedback (N unanswered):` section with each control ID and question, and the exit code reflects the audit's own pass/fail state (not the pending-question count).

---

### Edge Cases

- The audit terminates early because of the `MAX_AGENT_ITERATIONS = 10` safety ceiling. The tests must not depend on iteration count behavior beyond the fact that termination is bounded; asserting exact iteration counts would tie the tests to internal orchestration semantics that the harness driver is expected to change.
- `route()` returns a state indicating collect_context but the noninteractive feedback handler answers nothing. The current code breaks the loop; the test pins this behavior via the golden-path expectation that a fixture producing no answerable questions still terminates and reports.
- A fixture check emits status `N/A` (with a slash) rather than the deprecated `NA`. The tests must accept `N/A` in outputs, matching the fix in `cli.py:72,94,145` from feature 022.
- A fixture check emits status `ERROR` or `PENDING_LLM`. These are not among the current status buckets counted by `cmd_run` (only `PASS`/`FAIL`/`WARN` are printed). Tests must either avoid emitting these statuses from fixtures or explicitly document that they contribute only to `Total` and not to the other counts, so that adding them to the printed bucket set later is a visible test change rather than a silent gain.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A new test file at `tests/darnit/cli/test_cmd_run_e2e.py` MUST exercise `cmd_run` end-to-end by invoking it through its argparse entry point (not by internal calls into `audit()` / `collect_context()` / `remediate()`).
- **FR-002**: The test suite MUST pass on the codebase as it stands at merge time (green baseline). It MUST NOT modify any code under `packages/darnit/src/darnit/cli.py`, `packages/darnit/src/darnit/agent/`, or any production module. Fixture files, `conftest.py`, and test helpers are permitted.
- **FR-003**: The golden-path test MUST assert on: (a) exit code, (b) presence of the `Darnit run` and `Run complete.` header/footer strings, (c) presence of `Total`, `Passed`, `Failed`, `Warned` labels with numeric values, (d) absence of an `Error:` line and absence of a Python traceback.
- **FR-004**: The deterministic-only test MUST stub the LLM backend entry points and MCP client entry points reachable from the `cmd_run` codepath, such that any call into them during the test raises. It MUST also stub external subprocess calls (`gh`, other CLI checks) to return canned output rather than executing real commands.
- **FR-005**: Failure-path tests MUST cover, at minimum: missing repository path, no framework implementation resolvable, and a malformed `.project/project.yaml`. Each test MUST assert both a non-zero exit code and a diagnostic string that names the specific failure category.
- **FR-006**: A dedicated test MUST assert the `Pending human feedback` behavior for noninteractive mode with unanswered questions, so that reclassification of pending-feedback into an error (or vice versa) surfaces as a test change.
- **FR-007**: Tests MUST use existing fixtures under `tests/` where possible; new fixtures MUST live under `tests/darnit/cli/fixtures/` and MUST be minimal (a single-repo tree with a single satisfied control is sufficient for the golden path).
- **FR-008**: Stubbing of `subprocess.run` MUST follow the pattern established in `tests/darnit_baseline/controls/test_branch_protection.py` (patch the module-scoped `subprocess.run` reference, provide canned `CompletedProcess`-shaped return values). The intent is that a future maintainer sees the same idiom in both files and does not need to invent a new one.
- **FR-009**: The test file MUST be discoverable by the existing pytest configuration without any changes to `pyproject.toml`, `conftest.py` at the repo root, or the CI workflow.
- **FR-010**: Tests MUST NOT depend on network access, on the presence of a real `git` binary beyond what fixtures require, on any LLM API key, or on any specific host toolchain beyond Python 3.11/3.12.
- **FR-011**: Test names, docstrings, and assertion messages MUST make explicit which observable output field is being pinned, so a future test failure identifies the drifted field (exit code, header string, count line, error line, pending-feedback section) rather than requiring the reader to reconstruct the intent.
- **FR-012**: All test source files added under this feature MUST be ASCII-only, matching the project convention already applied in the `darnit-baseline` package.

### Key Entities

- **Fixture repository**: A minimal filesystem tree used as the `repo_path` argument to `cmd_run`. Contains just enough structure (a couple of files satisfying at least one baseline check) to produce a nonzero `Total` without triggering LLM or MCP paths.
- **Stub registry**: The collection of monkeypatched entry points (LLM backends, MCP clients, `subprocess.run`) applied by the deterministic-only test to prove no live call escapes the codepath under test.
- **Observable output**: The stdout stream and exit code of a `cmd_run` invocation. This is the contract the tests pin; internal state of `AuditState` is out of scope except where it is directly rendered to output.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every test in the new file passes against `main` as of the feature's merge commit. Zero flaky retries in CI over five consecutive scheduled runs on the day after merge.
- **SC-002**: A deliberate breaking edit to the exit-code logic in `cmd_run` (e.g. force `return 0`) causes at least one test in the new file to fail with an assertion message that names `exit code` or `returncode`. Verified during PR review by inspection of the test names/messages, not by actually making the edit on `main`.
- **SC-003**: A deliberate breaking edit that removes the `Run complete.` line from the output causes at least one test in the new file to fail with an assertion message that names the missing header string.
- **SC-004**: A deliberate breaking edit that inserts a bare `LLMClient().generate(...)` call anywhere in the `cmd_run` codepath causes the deterministic-only test to fail with a stub-raised exception that identifies the LLM entry point as the offending call.
- **SC-005**: The new test file adds no more than 30 seconds to the wall-clock runtime of the full `pytest tests/darnit/` suite on a developer laptop, and no more than 60 seconds on the CI runner.
- **SC-006**: The new file plus any supporting fixture files add no more than 800 lines of code total (production zero; tests + fixtures under 800).

## Assumptions

- **A1**: Feature 022's `list[CheckResult]` typing of `AuditState.audit_results` is in place at merge time. Tests may assert on results as `CheckResult` dicts with `status` in the six-status Literal (`"PASS"`, `"FAIL"`, `"WARN"`, `"N/A"`, `"ERROR"`, `"PENDING_LLM"`).
- **A2**: The `noninteractive` feedback handler continues to return `None` from `ask()` for every prompt. If a future change introduces a nontrivial noninteractive answering path, the golden-path fixture may need adjustment.
- **A3**: The `darnit-baseline` implementation is discoverable via the plugin registry in the test environment (installed by the workspace dev dependencies). If the plugin registry becomes lazily loaded or gated behind an env var, the tests may need adjustment.
- **A4**: RFC-0001 Stage 1 will replace `cmd_run` with a harness-driven implementation but will preserve the CLI surface (`darnit run [--feedback ...] [repo_path]`), the exit-code contract, and the header/footer output strings the tests pin. If the harness driver deliberately changes any of these, the tests are expected to fail and be updated in the same PR as the driver change.
- **A5**: The fix committed in feature 022 to use `"N/A"` (with slash) consistently is not reverted before this feature ships; tests may pin `N/A` in outputs without a fallback for `NA`.
- **A6**: The scope of `cmd_run` behavior pinned by this feature is limited to the deterministic path (no LLM key present, no MCP round-trip). Coverage of the future LLM-backed harness path is out of scope and will be added alongside the harness driver.

## Out of Scope

- Modifying `cmd_run` or any production code. This feature is test-only per issue #359.
- Coverage of the LLM-backed execution path (no LLM API key wiring in tests, no LLM response fixtures). That coverage is expected to accompany RFC-0001 Stage 1.
- Coverage of the `darnit audit` command (already tested by `tests/darnit/test_cli.py`).
- End-to-end coverage of `darnit serve` (MCP server), `darnit install`, or any other subcommand.
- Contract tests for individual sieve handlers or framework implementations. Those live in their respective per-package test trees.
- Adding new fixture repositories large enough to double as real audit targets (e.g. a full-scale repo clone). Fixtures should be minimal and single-purpose.
