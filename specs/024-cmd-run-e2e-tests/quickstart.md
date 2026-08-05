# Quickstart: E2E tests for `darnit run`

**Feature**: 024-cmd-run-e2e-tests
**Audience**: maintainers running or extending the E2E test suite

---

## Run the tests

```bash
# From the repo root, with the workspace installed via `uv sync`:
uv run pytest tests/darnit/cli/test_cmd_run_e2e.py -v
```

Expected: all tests pass in under 30 s on a developer laptop.

To run only one user story's tests:

```bash
uv run pytest tests/darnit/cli/test_cmd_run_e2e.py -v -k golden           # US1
uv run pytest tests/darnit/cli/test_cmd_run_e2e.py -v -k deterministic    # US2
uv run pytest tests/darnit/cli/test_cmd_run_e2e.py -v -k failure          # US3
```

---

## Verify the golden-path pin actually pins

Deliberate perturbation, undone after check:

```bash
# 1. Introduce a fake regression:
uv run python -c "
import pathlib
p = pathlib.Path('packages/darnit/src/darnit/cli.py')
s = p.read_text()
p.write_text(s.replace('return 1 if failed else 0', 'return 0  # intentionally broken', 1))
"
uv run pytest tests/darnit/cli/test_cmd_run_e2e.py -v -k golden      # expect at least one failure naming exit code
git checkout -- packages/darnit/src/darnit/cli.py                     # revert
uv run pytest tests/darnit/cli/test_cmd_run_e2e.py -v -k golden      # expect green again
```

If the first invocation does NOT fail, the test suite is not actually pinning the exit-code contract; fix the test before merging.

---

## Verify the deterministic-only guarantee

The deterministic-only test patches known external call sites (subprocess and any LLM/MCP entry points enumerated in `conftest.py::_ENTRY_POINTS_THAT_MUST_NOT_BE_CALLED`) with `side_effect=RuntimeError`. To verify manually:

```bash
# Confirm the patches don't leak: run against the fixture with real subprocess
uv run pytest tests/darnit/cli/test_cmd_run_e2e.py -v -k deterministic
```

If a future maintainer adds an unguarded outbound call (e.g. `subprocess.run(["gh", "api", ...])`) to any module in the `cmd_run` codepath, this test will fail with `RuntimeError: must not be called` and point at the offending module.

---

## Add a new test

1. Choose the fixture. `MinimalRepo` covers most cases. If a new fixture is needed:
   - Add a tree under `tests/darnit/cli/fixtures/<name>/`.
   - Register a copy-to-tmp helper in `tests/darnit/cli/conftest.py` (or reuse the existing `minimal_repo_tree` helper via parametrization).
   - Document the invariants of the new fixture at `specs/024-cmd-run-e2e-tests/data-model.md`.
2. Choose the assertion pattern. Pin at the output contract from `contracts/cmd_run-output.md`. Do not assert on internal `AuditState` shape unless a contract item requires it.
3. Include a docstring naming the pinned field (e.g. "pins exit code", "pins Run complete. header"). This makes failure messages self-describing.

---

## Update the contract

If you're intentionally changing the observable output of `cmd_run` (e.g. adding a new count bucket, renaming a header):

1. Update `specs/024-cmd-run-e2e-tests/contracts/cmd_run-output.md` in the same PR.
2. Update the corresponding assertion in `tests/darnit/cli/test_cmd_run_e2e.py`.
3. Note the change explicitly in the PR description under a `Contract change:` heading.

Reviewers should reject any PR whose test edits are not accompanied by a matching contract edit.

---

## Troubleshooting

**Test fails with `RuntimeError: must not be called: darnit.core.utils.subprocess.run`.**
A recent change added or exposed a subprocess call in the `cmd_run` codepath that wasn't stubbed. Either (a) stub it in `conftest.py::_ENTRY_POINTS_THAT_MUST_NOT_BE_CALLED`, if the call is desired and safe, or (b) remove the call, if it should not be there.

**Test fails with `FileNotFoundError` for the fixture tree.**
Fixture tree probably moved. Check `data-model.md` for the current fixture layout and update the `conftest.py` copy helper.

**Test fails only on CI, not locally.**
Likely a missing `git init` step on the copied fixture. CI runners may have older git configs; ensure `conftest.py` runs `git init && git commit --allow-empty -m init` after the copy.

**Test flake (passes sometimes, fails sometimes).**
Not tolerated by SC-005. File a follow-up issue immediately; do not merge.
