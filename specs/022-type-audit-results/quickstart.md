# Quickstart: Verifying the AuditState typing fix

**Feature**: 022-type-audit-results
**Audience**: Maintainer confirming the fix locally before or after review.

## Establish the baseline (before-fix, from `main`)

```bash
git checkout main
uv sync
uv run mypy packages/darnit/src/darnit/agent/state.py \
              packages/darnit/src/darnit/agent/graph.py \
              packages/darnit/src/darnit/sieve/models.py \
              packages/darnit/src/darnit/tools/audit.py \
              packages/darnit/src/darnit/cli.py 2>&1 | tail -25
```

Expected (approximate; exact counts may shift as unrelated code changes):

- `agent/graph.py`: 4 errors (`arg-type` on `owner`/`repo` at lines 74/75, missing return annotation at line 318, `attr-defined` for `load_framework_config` at line 321).
- `sieve/models.py`: 1 error (missing return annotation at line 171).
- `tools/audit.py`: 8 errors (missing return annotation at line 28; two `no-any-return`; one `no-untyped-call`; six `dict-item` at lines 1124-1141).
- `cli.py`: 4 errors (three `var-annotated` on `by_status`/`by_level`; one `no-any-return`).

None of these are related to `audit_results` access. Record the exact counts as the baseline in the PR description.

## Verify the fix (after-fix, on this branch)

```bash
git checkout 022-type-audit-results
uv sync
uv run mypy packages/darnit/src/darnit/agent/state.py \
              packages/darnit/src/darnit/agent/graph.py \
              packages/darnit/src/darnit/sieve/models.py \
              packages/darnit/src/darnit/tools/audit.py \
              packages/darnit/src/darnit/cli.py 2>&1 | tail -25
```

Expected: same count of errors as baseline (or fewer -- the annotation change may fix a preexisting error incidentally). Zero NEW errors mentioning `audit_results`.

## Negative verification (SC-002)

Confirm the annotation is being enforced by introducing a deliberate typo:

```bash
# Edit packages/darnit/src/darnit/agent/state.py:86 and change:
#   return [r["id"] for r in self.audit_results if r.get("status") == "FAIL"]
# to (typo `idd`):
#   return [r["idd"] for r in self.audit_results if r.get("status") == "FAIL"]

uv run mypy packages/darnit/src/darnit/agent/state.py 2>&1 | tail -5
```

Expected: mypy prints an error like:

```
packages/darnit/src/darnit/agent/state.py:86: error: TypedDict "CheckResult" has no key "idd"  [typeddict-item]
```

Revert the typo. Type-check returns to the clean-relative-to-baseline state.

## Runtime regression check (SC-003)

```bash
uv run pytest tests/ --ignore=tests/integration/ -m "not slow" -q
```

Expected: same pass/fail counts as `main`. As of feature 021 landing, that is 2276 pass, 1 preexisting failure (`test_upstream_spec_unchanged`, unrelated CNCF `.project` spec drift). No test needs modification for feature 022.

## Wheel-install regression check (bonus; SC-003 supporting)

The feature 021 test still MUST pass:

```bash
uv run pytest tests/packaging/test_wheel_install_config.py -m slow -v
```

Expected: 3 pass. This is a paranoia check; feature 022 does not touch any packaging or import paths, so failures here would be surprising.

## Lint gate

```bash
uv run ruff check .
```

Expected: clean.

## Constitution dev-workflow gate: spec sync

```bash
uv run python scripts/validate_sync.py --verbose
```

Expected: `TOML Schema`, `Pass Types Sync`, `SARIF Source` all pass.
