# Quickstart: verdict correctness (issues #342 and #343)

Two independent verifications, one per user story. Both should be reproducible from a clean checkout.

## US1: per-level counts match upstream OSPS Baseline

**Setup:** none. Uses vendored upstream fixture.

**Command:**

```sh
uv run pytest tests/darnit_baseline/test_level_counts.py -v
```

**Expected:**

- Test passes.
- Assertion output shows Level 1 = 24, Level 2 = 18, Level 3 = 20 controls.
- `OSPS-LE-01.01` appears in the Level 2 set, not Level 1.

**Manual cross-check:**

```sh
uv run python -c "
from darnit.core.discovery import get_implementation
impl = get_implementation('openssf-baseline')
for lvl in (1, 2, 3):
    controls = impl.get_controls_by_level(lvl)
    print(f'Level {lvl}: {len(controls)} controls')
    if lvl == 1:
        assert 'OSPS-LE-01.01' not in {c.id for c in controls}, 'LE-01.01 leaked into L1'
    if lvl == 2:
        assert 'OSPS-LE-01.01' in {c.id for c in controls}, 'LE-01.01 missing from L2'
print('OK')
"
```

## US2: branch-protection controls report FAIL on definitive 404

**Setup:** requires either (a) a test repository with no branch protection and authenticated `gh`, or (b) the integration test's stubbed `gh api` command. Path (b) runs offline.

**Command (path b, unit-marked integration test):**

```sh
uv run pytest tests/darnit_baseline/controls/test_branch_protection.py -v
```

**Expected:**

- Test passes.
- For each of `OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`: given a stubbed exec response with `exit_code=1` and `stdout` containing the `{"message": "Branch not protected", ...}` body, the pass resolves to FAIL.
- No pass resolves to WARN or INCONCLUSIVE.

**Manual live-repo check (path a, requires authenticated `gh`):**

Point at any repository whose default branch has no branch protection:

```sh
uv run darnit audit /path/to/unprotected-repo --output json | jq '.controls[] | select(.id | test("AC-03|QA-03.01|QA-07.01")) | {id, status}'
```

**Expected output:**

```json
{"id": "OSPS-AC-03.01", "status": "FAIL"}
{"id": "OSPS-AC-03.02", "status": "FAIL"}
{"id": "OSPS-QA-03.01", "status": "FAIL"}
{"id": "OSPS-QA-07.01", "status": "FAIL"}
```

All four MUST be FAIL, not WARN.

## Orchestrator unit tests

**Command:**

```sh
uv run pytest tests/darnit/sieve/test_orchestrator_cel.py -v
```

**Expected:** all eight cases from the transition table in `contracts/cel-post-step.md` pass, including the two new-behavior rows (Handler FAIL + CEL true -> INCONCLUSIVE; Handler FAIL + CEL false -> FAIL).

## Regression sweep

**Command:**

```sh
uv run pytest tests/ --ignore=tests/integration/ -m "not upstream" -q
```

**Expected:** no test that was previously passing regresses. Any test relying on the old CEL post-step behavior for `fail_exit_codes` + `expr` combinations (i.e., asserting PASS from a handler-FAIL + CEL-true state) is documented in `research.md` R5 as testing buggy behavior and must be updated or removed.
