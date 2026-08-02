# Research: preserve handler-conclusive FAIL through the CEL post-step

This feature inherits R1-R5 from feature 019's [`research.md`](../019-verdict-correctness/research.md). Rather than duplicate, the entries below reference back and add only the delta relevant to shipping US2 on its own.

## R1: Current CEL post-step semantics (root cause)

**See:** feature 019 `research.md` R1.

**Summary:** `packages/darnit/src/darnit/sieve/orchestrator.py:60-75` maps CEL true -> PASS and CEL false -> INCONCLUSIVE regardless of the handler's original status. When the exec handler returns FAIL via `fail_exit_codes` and the CEL expression evaluates false against an incomplete evidence dict (e.g., `has(output.json.required_pull_request_reviews)` on a 404 body), the handler's FAIL is demoted to INCONCLUSIVE. The pipeline falls through to the manual handler and yields WARN. This is the root cause of issue #343.

## R2: exec handler exit-code classification

**See:** feature 019 `research.md` R2.

**Summary:** confirmed at `packages/darnit/src/darnit/sieve/builtin_handlers.py:247-266`. `pass_exit_codes` -> PASS, `fail_exit_codes` -> FAIL, else INCONCLUSIVE. No change required to the exec handler; the downstream CEL post-step is what corrupts the verdict.

## R3: `gh api` 404 response shape

**See:** feature 019 `research.md` R3.

**Summary:** for a branch with no protection, `gh api /repos/{owner}/{repo}/branches/{branch}/protection` returns HTTP 404 with body `{"message": "Branch not protected", "documentation_url": "...", "status": "404"}` and exit code 1. The exec handler's `output_format = "json"` parses this into `output.json`. Tests should stub the subprocess call with exactly this shape.

## R4: Test source of truth

Not applicable for this feature (no vendored external fixture required). The two test files needed:

- `tests/darnit/sieve/test_orchestrator_cel.py`: unit tests for the 8-cell transition table.
- `tests/darnit_baseline/controls/test_branch_protection.py`: integration tests for the 4 named branch-protection controls with patched subprocess return values.

Both are `pytest.mark.unit` (offline, no network).

## R5: Regression audit for the 12 affected controls

**See:** feature 019 `research.md` R5.

**Summary:** twelve controls combine `fail_exit_codes` + `expr` in the same pass and are affected by the orchestrator change:

```
OSPS-AC-01.01, OSPS-AC-02.01, OSPS-AC-03.01, OSPS-AC-03.02, OSPS-BR-03.01,
OSPS-GV-02.01, OSPS-LE-02.01, OSPS-QA-01.01, OSPS-QA-03.01, OSPS-QA-07.01,
OSPS-VM-03.01, OSPS-VM-04.01
```

New behavior for all twelve:
- H=FAIL + CEL=true -> INCONCLUSIVE (handler and CEL disagree; safer to be inconclusive). Was PASS today.
- H=FAIL + CEL=false -> FAIL (both agree; conclusive). Was INCONCLUSIVE today.

**Regression risk:** low. A test that expected PASS from H=FAIL + CEL=true would be exercising an ambiguous state that is not a coherent PASS signal. Any such test is asserting buggy behavior. The tasks phase includes an audit pass (grep the existing test suite) before applying the orchestrator change.

## R6: Nondeterministic verification path (new for this feature)

**Decision:** verification of this feature includes a mandatory `/darnit-audit` run against a repository whose default branch has no protection, or against `/tmp/darnit-test-repo` (the scratch repo created during feature 019 verification), to observe the four named controls report FAIL through the full MCP pipeline including any LLM eval steps that may consume the verdict downstream.

**Rationale:** feature 019 US1 shipped after passing 2258 unit tests but had a real bug (TOML `spec_version` not updated) that was only surfaced by running the audit skill and reading the report. Deterministic tests cover the transition table; only the audit skill exercises the product path a user actually sees. Lesson recorded in memory as `feedback_darnit_testing_framing`.

**Alternatives considered:** rely on unit tests alone (rejected: does not cover the audit-report-rendering path or any LLM-consumed follow-up steps); require a live repo with real API responses (rejected: too flaky for CI, still worthwhile for maintainer verification).

## R7: Test discovery — existing controls that combine `fail_exit_codes` + `expr`

Before applying the orchestrator change, run the following grep to identify existing tests that assert behavior for the 12 affected controls. Any hit that asserts PASS from a `fail_exit_codes` + `expr` handler needs an assertion update.

```sh
grep -rn "fail_exit_codes\|HandlerResultStatus.FAIL" tests/ | grep -E "(orchestrator|cel|branch_protection|AC-0[123]|BR-0[13]|GV-02|LE-02|QA-0[137]|VM-0[34])"
```

Findings from this grep are recorded in the tasks-phase task T-audit (see `tasks.md`).
