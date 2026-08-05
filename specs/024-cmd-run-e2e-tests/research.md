# Research: E2E Regression Baseline for `darnit run`

**Feature**: 024-cmd-run-e2e-tests
**Date**: 2026-08-05
**Status**: Complete

Phase 0 output. Each open question from the plan resolved with a Decision / Rationale / Alternatives triplet.

---

## R1. Which framework does the golden-path fixture point at?

**Decision**: `darnit-testchecks`.

**Rationale**:
- `darnit-testchecks` exists in the workspace (`packages/darnit-testchecks/`) specifically for this kind of test-only setup. Its entry point is registered in the workspace dev install (`pyproject.toml` workspace section), so it is discoverable by the framework's plugin registry when the workspace is installed via `uv sync`, which the CI already does.
- Using `darnit-testchecks` keeps the E2E tests independent of the real `darnit-baseline` control set. Baseline controls exercise `gh`, `git`, filesystem probes, and CEL expressions -- each an extra failure surface for a test that is really about `cmd_run` orchestration, not about compliance verdicts.
- The testchecks framework provides trivial adapters and predictable pass/fail behavior, which lets the golden-path fixture be a two-file tree instead of a full baseline-compliant repo.
- The Constitution Rule I concern (framework tree importing implementation) is sidestepped: the test's fixture *names* `darnit-testchecks` via the plugin registry (identical mechanism used by real users), rather than the test code `import darnit_baseline`.

**Alternatives considered**:
- **`darnit-baseline`**: fatter fixture, more failure surfaces, real-world-looking. Rejected because the tests then also depend on the baseline control set staying stable, which pins tests to two orthogonal things.
- **A synthetic ad-hoc implementation defined in the test file**: possible, but requires wiring an entry point at test time (or monkeypatching the discovery registry), which is fragile and reproduces mechanisms already provided by `darnit-testchecks`.
- **`darnit-hello`**: minimal too, but marketed as the reference plugin template and is more likely to churn as we teach new patterns via it. `darnit-testchecks` is explicitly a test fixture package.

**Consequence**: `tests/darnit/cli/fixtures/minimal_repo/.baseline.toml` will set the framework to `testchecks`, and the fixture will emit at least one control per pass/fail state the tests care about.

---

## R2. What is the concrete stubbing surface for "deterministic-only" tests?

**Decision**: Two-tier stub registry, applied together by the `deterministic_run` fixture. See data-model.md section 4 for the canonical shape.

- **Tier 1 -- `_MUST_NOT_BE_CALLED` (raise-on-call)**: LLM SDK entry points and MCP client entry points. These are currently empty (no such import is reachable from `cmd_run`), but the tuple is wired so a future accidental introduction surfaces as `RuntimeError: must not be called: <dotted-name>`.
- **Tier 2 -- `_SUBPROCESS_STUBS` (canned-success)**: `subprocess` at `darnit.core.utils` (used by `_get_remote_url` and `_gh_enrich`) and `darnit.sieve.builtin_handlers` (used by the `exec` handler). Replaced with a namespace object exposing `.run` returning a `subprocess.CompletedProcess`.

| Call site | Tier | Why the choice |
|-----------|------|----------------|
| `subprocess.run` in `darnit.core.utils` | Canned-success | Required for the golden path. `cmd_run` -> `prepare_audit` -> `detect_repo_from_git` -> `_get_remote_url` shells out to `git remote get-url`. Raising here breaks `prepare_audit` and collapses all US1 assertions. Canned-success returns exit-2 (matches real-git behavior for repos with no remote); the fixture's `git init` gives `detect_repo_from_git` enough context to auto-detect via other paths. |
| `subprocess.run` in `darnit.sieve.builtin_handlers` | Canned-success | Belt-and-suspenders. Any testchecks control that shells out (currently none at level 1-3 that we exercise, but the safety is cheap). |
| LLM SDK entry points (openai, anthropic) | Raise-on-call | Not currently imported by anything reachable from `cmd_run`; grep confirms zero occurrences. Tuple is wired so a future import that fires from the run path surfaces immediately. |
| MCP client entry points (fastmcp.client) | Raise-on-call | Used only by `darnit serve`. If a future refactor pulls MCP into `cmd_run`, this tuple catches it. |
| `urllib.request.urlopen` and `requests.get` | Not stubbed at this layer | The two subprocess stubs already gate the real-world calls that `cmd_run` reaches; adding urllib-level stubs is out of scope for now. Revisit if a new dependency starts using them directly from the run path. |

The two-tier split is the correction to my earlier one-tier design: originally all stubs raised on call, which would have broken the golden path because auto-detect needs subprocess to run. Split resolves feature-024 analysis finding U1.

**Rationale**:
- The `patch("<module>.subprocess", <namespace>)` pattern (replacing the module-scoped `subprocess` reference) mirrors `tests/darnit_baseline/controls/test_branch_protection.py:121` (which does `patch("darnit.sieve.builtin_handlers.subprocess.run", side_effect=_fake_run)`). We patch at the module level (not `builtins`) so `conftest.py`'s own `subprocess.run(["git", "init"])` in fixture setup keeps working.
- Splitting the tuples in `conftest.py` (not in the test file itself) makes both lists reusable if a second test file ever exercises the same guarantees.

**Alternatives considered**:
- **Env-var-based egress blockers** (e.g. `NO_PROXY`, `http_proxy=127.0.0.1:1`): unreliable across HTTP libraries and CI runners; patches surface as opaque timeouts rather than named assertion failures.
- **`socket.socket` monkeypatch to raise on any bind**: catches network at the syscall level but breaks unrelated things (pytest-xdist, logging, some test collection paths). Rejected as too invasive.
- **Single-tier raise-on-call for everything**: original design; rejected because it breaks auto-detect on the golden path (see finding U1).

**Alternatives considered**:
- **Env-var-based egress blockers** (e.g. `NO_PROXY`, `http_proxy=127.0.0.1:1`): unreliable across HTTP libraries and CI runners; patches surface as opaque timeouts rather than named assertion failures.
- **`socket.socket` monkeypatch to raise on any bind**: catches network at the syscall level but breaks unrelated things (pytest-xdist, logging, some test collection paths). Rejected as too invasive.
- **Not stubbing LLM entry points**: fine today, fragile tomorrow -- would silently pass if a future edit adds `openai.ChatCompletion.create(...)` inside `cmd_run`'s codepath.

---

## R3. How does the fixture repository get from "empty tmp_path" to "cmd_run runs cleanly"?

**Decision**: Ship a static fixture tree at `tests/darnit/cli/fixtures/minimal_repo/`, copy it to `tmp_path` per test via a session-scoped `conftest.py` helper, and run `git init` + `git commit --allow-empty` on the copy. Do not check in a `.git/` directory.

**Rationale**:
- `detect_repo_from_git` requires a git repo (or falls back to error). Running `git init` is cheap (~50 ms) and gives auto-detection something to consume. The mock of `_get_remote_url` supplies the fake owner/repo so the git remote doesn't actually need to exist.
- Copying the fixture per test ensures each test gets a clean tree; two tests can safely run in parallel under `pytest-xdist`.
- Not checking in a `.git/` directory keeps the diff clean and avoids submodule-adjacent oddities.

**Alternatives considered**:
- **Programmatic fixture assembly inside each test**: verbose, easy to drift across tests. Rejected in favor of the shared static tree.
- **Point `cmd_run` at the darnit repo itself**: obviously wrong -- couples tests to whatever main happens to look like.

---

## R4. How are exit codes verified when `cmd_run` calls `sys.exit`-like paths?

**Decision**: Invoke via the argparse dispatcher: construct `args` from the argparse parser (`build_parser().parse_args(["run", str(fixture_path), "--feedback", "noninteractive"])`), then call `args.func(args)` and assert on the returned integer. Do not run through `subprocess.run(["darnit", ...])` from the tests.

**Rationale**:
- `cmd_run` returns an `int` (never calls `sys.exit`), so direct call yields a clean assertion without a subprocess round-trip.
- Direct call runs in-process, so `caplog` / `capsys` cleanly capture output and can be asserted line-by-line.
- Subprocess-based invocation would add ~500 ms per test and would defeat the module-level `patch` calls.
- The argparse-parse step is included so the tests exercise the actual CLI wiring, not just the `cmd_run` function body. A regression in the argparse wiring (missing `--feedback` flag, wrong default) still fails the tests.

**Alternatives considered**:
- **Use `pytest.mark.script_launch` / `subprocess.run`**: gives the highest fidelity but breaks in-process patching and slows the suite meaningfully. Rejected.
- **Import and call `cmd_run` directly with a hand-built `argparse.Namespace`**: skips the wiring test. Rejected; the marginal cost of parsing an arg vector is negligible and the coverage gain is real.

---

## R5. How is "no LLM call, no MCP round-trip" proved rather than assumed?

**Decision**: Two-layer proof, applied ONLY to the `_MUST_NOT_BE_CALLED` tier (LLM/MCP). The `_SUBPROCESS_STUBS` tier is not covered by this proof because subprocess calls ARE expected on the golden path (they just route to canned stubs, not real commands).

1. **Positive**: `_MUST_NOT_BE_CALLED` entries are patched to `Mock(side_effect=RuntimeError("must not be called: <dotted-name>"))`. Any invocation surfaces as a named test failure identifying which entry point was called. When the tuple is empty (current state), the positive layer is a no-op that costs nothing.
2. **Negative**: assert `caplog` records no `WARNING` or `ERROR`-level log line whose message contains the substrings `"llm"`, `"anthropic"`, `"openai"`, `"mcp"`. This defends against a future maintainer wrapping an LLM call in `try/except` and logging the failure instead of letting it propagate.

**Rationale**:
- Belt-and-suspenders: the positive layer catches direct calls; the negative layer catches "call, catch, log" patterns.
- Both layers are cheap: `patch` is a decorator, `caplog` is a fixture already available in pytest.
- Excluding `"api"` from the log-substring blocklist (present in an earlier draft) because production code legitimately logs about `.gitignore`-detected APIs and about `bestpractices.dev` API URLs -- too many benign hits.

**Alternatives considered**:
- **Only the positive layer**: acceptable but leaves a small hole (silent try/except around an LLM call). The negative layer is cheap enough to keep.
- **Coverage-based proof** (assert that some `llm_client.py` module was not imported): unreliable because coverage might be skipped or the module might be transitively imported for type hints without being called.
- **Extend the proof to subprocess (assert real `subprocess.run` was never called)**: does not compose with the golden path's need for auto-detect. The canned-success tier is the right approach; the negative layer for LLM/MCP is orthogonal.

---

## R6. Which failure paths from spec User Story 3 are testable without touching production code?

**Decision**: All three plus the pending-feedback case.

| Failure condition | How to trigger | Expected observation |
|-------------------|----------------|----------------------|
| Missing repository path | `parse_args(["run", "/does/not/exist"])` | exit non-zero; diagnostic names the missing path (from `validate_local_path`). |
| No framework implementation | Fixture has no `.baseline.toml`; framework registry has no entry that matches. Trigger by monkeypatching `get_implementation` to return `None`, OR by pointing the fixture at a framework name that isn't registered. | exit non-zero; diagnostic mentions the missing framework name. |
| Malformed `.project/project.yaml` | Fixture contains a `.project/project.yaml` with intentionally invalid YAML syntax (unclosed brackets, tab-indent inside a nested map, etc.) | exit non-zero; diagnostic names the config file OR the parse error site. |
| Pending human feedback in noninteractive | Fixture includes a control that requires context confirmation (e.g. `maintainers`); noninteractive handler returns `None` for the prompt; expect `cmd_run` to break the loop and print `Pending human feedback (N unanswered)`. | exit code reflects audit pass/fail state; `Pending human feedback` section printed. |

**Rationale**:
- All four are triggerable purely from the fixture-side; no production edits required.
- Each mode is exercised by an existing code branch (`validate_local_path` error, `get_implementation` None return, YAML parser exception, `noninteractive.ask` returning `None`), so the test suite verifies real behavior rather than a mock.

**Alternatives considered**:
- **Add a "run against permission-denied path" case**: requires OS-specific chmod dance; skipped as low-value relative to the other three.
- **Add "framework raises during discovery"**: introduces mock complexity for negligible additional coverage. Rejected.

---

## R7. What is the ASCII-only enforcement mechanism for the new test files?

**Decision**: No new enforcement mechanism. Author to ASCII per project convention; reviewer to check. If ASCII drift becomes recurring, a lint rule can be added under a separate feature.

**Rationale**:
- The project's ASCII convention is documented in `CLAUDE.md` and reinforced by prior review feedback. Existing files in `tests/darnit/` follow it.
- Adding a new lint rule (custom or via `ruff`) exceeds the scope of a test-only feature and would be premature abstraction.

**Alternatives considered**:
- **Add a pytest collection hook that scans test files for non-ASCII bytes**: works but overkill for a single-file feature; rejected.

---

## R8. Does the deterministic-only test suite need `pytest-xdist` opt-out or is it parallel-safe?

**Decision**: Parallel-safe. No opt-out needed.

**Rationale**:
- Fixture-tree copies are per-test (unique `tmp_path`), so no shared filesystem state.
- Module-level `patch` calls are automatically scoped to the test that applies them (pytest's `monkeypatch` fixture is function-scoped by default), so parallel tests do not race on the same patched attribute.
- No shared HTTP mock server, no shared subprocess -- nothing that would need per-worker isolation.

**Alternatives considered**:
- **Add `pytest.mark.serial` and configure `pytest-xdist` to run serially**: safer default but slows the suite. Only worth it if we hit a real race, which the current design avoids.

---

## Summary of resolved unknowns

All Technical Context items are concrete. No `NEEDS CLARIFICATION` markers remain. Ready for Phase 1.
