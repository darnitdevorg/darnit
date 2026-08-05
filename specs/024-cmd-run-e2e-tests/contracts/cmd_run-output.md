# Contract: `darnit run` observable output

**Feature**: 024-cmd-run-e2e-tests
**Date**: 2026-08-05

The pinned observable contract of `cmd_run` as of the merge commit. This is what the test suite locks in. RFC-0001 Stage 1 (harness driver) MUST preserve every item below, or the accompanying test failure MUST be reviewed and the contract updated in the same PR.

Interface is the process boundary: exit code + stdout. Stderr and logs are secondary (asserted only for the "no-network-egress" guarantee).

---

## Exit code

- `0` if and only if `audit_results` contains zero entries with `status == "FAIL"` AND `state.error is None`.
- `1` in all other cases (any FAIL, any error, malformed input, missing plugin, missing repo path).

Source of truth: `packages/darnit/src/darnit/cli.py:724-728`.

## stdout structure

The following lines appear, in this order, for every non-error invocation:

```text
<blank>
Darnit run
  Repository : <resolved repo_path>
  Feedback   : <interactive|noninteractive>
<blank>
Run complete.
  Total  : <int>
  Passed : <int>
  Failed : <int>
  Warned : <int>
```

Followed optionally by, only if `len(pending) > 0`:

```text
<blank>
Pending human feedback (<N> unanswered):
  Control : <control_id>
  Question: <question text>
<blank>
  Control : <control_id>
  Question: <question text>
<blank>
...
```

Followed optionally by, only if `state.error is not None`:

```text
<blank>
Error: <error message>
```

### Contract items

- **C1**: The `Darnit run` header string appears exactly once and on its own line.
- **C2**: `  Repository : ` and `  Feedback   : ` are present, each on its own line, in that order, with the two-space indent shown.
- **C3**: `Run complete.` appears exactly once on its own line for every non-error path.
- **C4**: The four count labels are `Total`, `Passed`, `Failed`, `Warned`, in that order, each with the two-space indent.
- **C5**: When `len(pending) > 0`, the header line is `Pending human feedback (N unanswered):` where N is a decimal integer with no surrounding whitespace.
- **C6**: Each pending item prints `  Control : <control_id>` followed by `  Question: <question text>`, and items are separated by a blank line.
- **C7**: When `state.error is not None`, the line `Error: <message>` appears once, prefixed by a blank line.
- **C8**: No line contains a Python traceback substring (`Traceback (most recent call last):`).
- **C9**: No line contains characters outside the ASCII printable range (0x20-0x7E) plus `\n`. (Enforcement: the test asserts on ASCII-only for the entire captured stdout.)

## Status semantics pinned by count lines

- **C10**: `Total = len(audit_results)`.
- **C11**: `Passed = count of results where status == "PASS"`.
- **C12**: `Failed = count of results where status == "FAIL"`.
- **C13**: `Warned = count of results where status == "WARN"`.
- **C14**: Results with `status in ("N/A", "ERROR", "PENDING_LLM")` contribute to `Total` but not to any of the three named buckets. This is a known asymmetry in current behavior and is pinned as-is; a future harness driver that adds explicit buckets is a contract change requiring a coordinated test update.

## Feedback mode resolution

- **C15**: `--feedback interactive` -> `Feedback : interactive`.
- **C16**: `--feedback noninteractive` -> `Feedback : noninteractive`.
- **C17**: `--feedback auto` -> `Feedback : interactive` if stdin is a TTY, else `Feedback : noninteractive`.

## Error-path behavior

- **E1**: When `prepare_audit` returns an `error` (missing path, undetectable owner/repo), `state.error` is set and the run stops before printing `Run complete.`. Only the header + Error line is produced. Exit code 1.
- **E2**: When `audit()` raises an unexpected exception, the exception is logged and `cmd_run` returns 1. Exit code 1.
- **E3**: When plugin registry returns no matching implementation, `run_checks` raises; caught by the `try/except` at `cli.py:669-696`. Exit code 1, `Error:` line printed.

## Non-contract items (explicitly NOT pinned)

- Iteration count of the audit -> collect_context -> audit re-run loop. Bounded by `MAX_AGENT_ITERATIONS = 10`; the exact value has no user-observable consequence and is expected to change with the harness driver.
- Ordering of `Pending human feedback` entries beyond "one per unanswered question". Insertion order is preserved today but is not a contract.
- Log-line contents (`logger.info(...)`, `logger.warning(...)`). Log destination and format are configured elsewhere; tests do not pin log strings.
- Timing. No performance contract on `cmd_run`.
- Behavior when an in-process LLM backend IS wired up. That is Stage 1 territory; this contract covers only the deterministic (no-LLM-wiring) path.

## How to update this contract

If a maintainer PR intentionally changes any pinned item:
1. Update this file in the same PR.
2. Update the corresponding assertion in `tests/darnit/cli/test_cmd_run_e2e.py`.
3. Note the change in the PR description as "contract change" so reviewers see it.

If a test fails and the failure is *not* an intentional contract change, treat it as a regression and fix the code.
