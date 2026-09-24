# Quickstart: Wire detect_filter Into Context Detection

**Feature**: 039 | **Date**: 2026-09-23

## What changed, in one paragraph

A context key can declare `detect_filter`, a CEL expression that rejects unwanted auto-detected values. One is shipped, on `security_contact`, to keep `security@example.com` out of projects whose `SECURITY.md` came from a template. It has never run. It does now, on both detection routes, before the auto-accept threshold, and on values stored before this fix.

## Why it mattered

`security_contact` carries `auto_detect = true`, so a detected value at or above confidence 0.8 is written to `.project/` with no prompt (`context_storage.py:556`). A detect-pipeline result with no explicit confidence normalizes to exactly 0.8. So the placeholder could land in the audit record unseen, and then feed `OSPS-VM-01.01`, `OSPS-VM-02.01` and `OSPS-VM-03.01`.

## Try it

```bash
d=$(mktemp -d) && cd "$d" && git init -q .
printf 'Report vulnerabilities to security@example.com\n' > SECURITY.md
uv run darnit audit "$d" --no-fail
```

Before: `security.contact` is set to `security@example.com` in `.project/`.
After: nothing is stored, and the rejection is reported.

Swap in a real address and the value is stored exactly as before.

## Running the tests

```bash
uv run pytest tests/darnit/context/test_detect_filter.py tests/darnit/config/ -v
uv run ruff check .
uv run pytest tests/ --ignore=tests/integration/ --ignore=tests/darnit/parity/tier2 -q
uv run python scripts/validate_sync.py --verbose
```

Note the test-ignore spelling: `--ignore=tests/darnit/parity/tier2`, not `--ignore=tests/darnit/parity`. The broader form skips parity tier 1, which CI runs.

## The trap worth knowing about

Binding a list to the filter does not error -- it silently passes:

```python
evaluate_cel("!value.contains('example.com')", {"value": ["a@example.com"]})
# success=True, value=True   <- the filter KEEPS it
```

CEL's `contains` on a list is membership, not substring, so `["a@example.com"].contains("example.com")` is false and the negation is true. A whole-list binding keeps a list containing the exact value the filter was written to reject.

That is why list-valued keys are filtered element-wise. It is also the reason this feature is careful about the difference between "the filter said no" and "the filter could not run" -- the original bug was a guard that failed open, and the obvious fix has its own way of doing the same thing.

## Writing a filter

```toml
[context.some_key]
auto_detect = true
detect_filter = "!value.contains('example.com')"
```

- The candidate is bound as `value`. Nothing else is bound.
- True keeps, false discards.
- For a list-valued key the expression sees one element at a time.
- If the expression cannot compile or errors on a value, the value is discarded and the failure is reported. It is never kept by default.

## What did not change

- Keys with no `detect_filter`: identical stored context.
- The auto-accept threshold, and which keys carry `auto_detect = true`.
- `.project/` is never rewritten by this feature, including when a stored value now fails its filter.
- Third-party plugin TOMLs still load with undeclared keys; only TOMLs shipped in this repository are checked in CI.
