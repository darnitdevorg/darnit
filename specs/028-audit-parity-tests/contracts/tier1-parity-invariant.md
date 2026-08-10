# Contract: Tier 1 Parity Invariant

**Feature**: 028-audit-parity-tests | **Consumers**: any maintainer opening a PR that touches the harness or MCP-tool code path.

Tier 1 is a mechanical assertion about the darnit audit: two consumers of the same audit -- the MCP tool and the harness -- must produce the same per-control status modulo one documented drift class. If they don't, one of them has a bug.

## 1. What Tier 1 asserts

- **T1-1**: For every fixture in `tests/darnit/parity/fixtures/`, Tier 1 invokes the audit via BOTH paths (direct Python call to `darnit_baseline.tools.audit_openssf_baseline` AND `darnit.harness.driver.HarnessRun.run()` with `MockLLMStep`), normalizes both outputs to `AuditResult`, and compares per-control status.
- **T1-2**: Statuses that agree produce no drift entry.
- **T1-3**: A control that appears in one path's result but not the other is a HARD failure (test fails with a "missing control" diagnostic).
- **T1-4**: A control whose statuses differ produces a `DriftEntry`. The comparator classifies it via the allowed-drift table.
- **T1-5**: The test PASSES iff every `DriftEntry` in every fixture's comparison satisfies `is_allowed_drift == True`.
- **T1-6**: On PASS, each fixture's summary line is emitted to the pytest report per FR-013.
- **T1-7**: On FAIL, the assertion message includes a fixed-width Markdown table (no ANSI escapes) listing every disallowed drift with columns `control_id`, `mcp_status`, `harness_status`.

## 2. Allowed drift table (canonical)

| MCP tool status | Harness status | Verdict |
|-----------------|----------------|---------|
| Any X           | Same X         | agree; no drift entry produced |
| PENDING_LLM     | Any non-PENDING_LLM (PASS, FAIL, WARN, N/A, ERROR) | ALLOWED DRIFT (harness's LLM continuation loop resolved) |
| PENDING_LLM     | PENDING_LLM    | agree; no drift entry produced |
| Any X (not PENDING_LLM) | PENDING_LLM | DISALLOWED (harness must resolve; not the other way around) |
| X               | Y (X != Y; neither PENDING_LLM) | DISALLOWED |

- **T1-8**: The table is the SOLE definition of allowed drift. Adding another row is a spec change to feature 028 (or a follow-up feature with its own spec).
- **T1-9**: The comparator implementation MUST mirror this table exactly. A unit test on the comparator enumerates every (mcp, harness) pair from the six possible statuses and asserts the correct classification.

## 3. Runtime constraints

- **T1-10**: The full Tier 1 suite MUST complete in under 60 seconds on a standard developer laptop (SC-002).
- **T1-11**: Each individual fixture's parity check SHOULD complete in under 10 seconds. A fixture that consistently exceeds 10s is a bug against this contract; the fixture is either too large or triggers a slow control.
- **T1-12**: Tier 1 MUST NOT make any network call, live LLM API call, or subprocess spawn. `MockLLMStep` is the sole LLM-side seam. Any test that observes a network call in Tier 1 is a bug against this contract.
- **T1-13**: Tier 1 MUST be deterministic. Repeated runs against an unchanged fixture MUST produce identical drift verdicts. If a Tier 1 test is flaky, the flake is a bug (either in the test or in an audit path that has time-of-day sensitivity).

## 4. Adversarial-test coverage

- **T1-14**: A test in `test_comparator_adversarial.py` seeds a hand-built diverging `AuditResult` pair (PASS vs FAIL on the same control) and asserts the comparator flags it as a disallowed drift. This is SC-001's mechanical verification.
- **T1-15**: A test in `test_comparator_adversarial.py` seeds N (>=3) divergences in one comparison and asserts the failure message contains exactly N rows in its drift table. This is SC-003's mechanical verification.

## 5. What Tier 1 does NOT assert

- **T1-16**: Does not check that the audit is "correct" in any absolute sense. Only that the two paths agree.
- **T1-17**: Does not exercise interactive answer collection (feature 027 territory).
- **T1-18**: Does not exercise re-audit-on-fresh-answer behavior (deferred; feature 026's MVP no-reaudit policy still holds).
- **T1-19**: Does not compare authority-level values across paths beyond the status field. Authority is verified elsewhere (feature 025 T005/T014/T016).
