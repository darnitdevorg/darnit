# Quickstart: reconciling darnit's `.project/` reader with a CNCF upstream drift

## When to use this runbook

Run through this document when `tests/darnit/context/test_dot_project_upstream.py::TestUpstreamSpecSync::test_upstream_spec_unchanged` starts failing on CI. That failure means the SHA-256 of the current upstream `types.go` no longer matches `.github/dot-project-spec-hash.txt`; the runbook re-syncs darnit with the new upstream state.

The runbook is written for a maintainer with a working darnit checkout, `gh` and `uv` installed, and network access to `github.com/cncf/automation`.

## Step 1: Snapshot both upstream states

```sh
# Current upstream tip
curl -sfL https://raw.githubusercontent.com/cncf/automation/main/utilities/dot-project/types.go \
  > /tmp/cncf-current.go
CURRENT_HASH=$(shasum -a 256 /tmp/cncf-current.go | awk '{print $1}')
echo "Current upstream: $CURRENT_HASH"

# Tracked upstream (the last state darnit reconciled against)
TRACKED_HASH=$(cat .github/dot-project-spec-hash.txt)
echo "Tracked: $TRACKED_HASH"

# Find which upstream commit produced the tracked hash. `gh` lists at most
# 100 commits per page; the file has few commits so one page usually covers.
for sha in $(gh api "repos/cncf/automation/commits?path=utilities/dot-project/types.go&per_page=100" --jq '.[].sha'); do
  candidate=$(curl -sfL "https://raw.githubusercontent.com/cncf/automation/$sha/utilities/dot-project/types.go" | shasum -a 256 | awk '{print $1}')
  if [ "$candidate" = "$TRACKED_HASH" ]; then
    echo "Tracked SHA: $sha"
    curl -sfL "https://raw.githubusercontent.com/cncf/automation/$sha/utilities/dot-project/types.go" \
      > /tmp/cncf-tracked.go
    break
  fi
done
```

## Step 2: Diff and classify

```sh
diff -u /tmp/cncf-tracked.go /tmp/cncf-current.go > /tmp/cncf-diff.patch
less /tmp/cncf-diff.patch
```

Walk the diff and classify each change per the vocabulary in [data-model.md](./data-model.md):

- `KEPT` — no reader change needed.
- `KEPT-WITH-RESHAPE` — same YAML key, new value shape (typically scalar-or-list). Reader must accept both shapes; consumers see the old shape (usually collapsed-to-first).
- `KEPT-WITH-ALIAS` — YAML key changed OR field was renamed/removed but darnit consumes the old semantics. Reader accepts the old key with a `DeprecationWarning`; next reconciliation removes the alias.
- `NEW-IGNORED` — upstream added a field; reader parses without exposing. Lands in `_extra`.

Cross-check each field against darnit's consumers (`packages/darnit/src/darnit/context/dot_project_merger.py`, `dot_project_mapper.py`, and any test under `tests/darnit/context/`). A field darnit does not consume today reclassifies from a code change to a documentation-only note in the maintenance record.

## Step 3: Edit `dot_project.py`

Apply changes in this order to keep review-diffs coherent:

1. Add new dataclasses required by RESHAPE handling (if any).
2. Add new YAML-parsing helpers required by RESHAPE handling (typically a "scalar-or-list" coercer that returns the first element).
3. Update per-field parsing at the relevant `data.get(...)` call sites in `DotProjectReader._parse_project(...)`.
4. Add `warnings.warn(msg, DeprecationWarning, stacklevel=2)` calls for each `KEPT-WITH-ALIAS` field, at the point the old key is first observed.
5. Bump `DOT_PROJECT_SPEC_VERSION` per the Q3 rule (1:1 with the tracked-hash file — every drift, no exceptions).
6. Update the module docstring's maintenance note to summarize the diff:
   ```
   # Reconciliation history
   #  - 1.1.0 -> 1.2.0 (feature 030-dot-project-spec-sync, 2026-08-14):
   #      * project_lead: accepts scalar or list; collapses to first.
   #      * package_managers[*]: accepts scalar or list; collapses to first.
   #      * cncf_slack_channel: deprecated upstream, alias with warning until 1.3.0.
   #      * slack_channels: parsed and ignored (NEW-IGNORED).
   ```

## Step 4: Refresh the tracked-hash file

Do this AFTER the reader is reconciled, so that `test_upstream_spec_unchanged` passes without the `--update-hash` override on the next run.

```sh
uv run pytest tests/darnit/context/test_dot_project_upstream.py -v --update-hash
```

## Step 5: Run the full-field-coverage fixture test

If this reconciliation added a new `KEPT-WITH-RESHAPE` or `KEPT-WITH-ALIAS`, update the fixture at `tests/darnit/context/fixtures/full_field_coverage.yaml` and the golden dict in `tests/darnit/context/test_full_field_coverage.py` to reflect the reconciled values:

```sh
uv run pytest tests/darnit/context/test_full_field_coverage.py -v
```

The golden dict must match the reconciled reader's output for every attribute the reader exposes. If a value changed intentionally (e.g., `project_lead` now sourced from a list's first element instead of a scalar), update the golden dict too.

## Step 6: Full workspace sweep

```sh
uv run pytest tests/ -q --deselect tests/darnit/context/test_dot_project_upstream.py::TestUpstreamSpecSync::test_upstream_spec_unchanged
uv run pytest tests/darnit/context/test_dot_project_upstream.py::TestUpstreamSpecSync -v
```

The deselect on the first line runs everything except the upstream-sync test (which the second line runs alone with fresh output).

## Step 7: PR checklist

Before opening the PR:

- [ ] `.github/dot-project-spec-hash.txt` matches the current CNCF upstream tip.
- [ ] `DOT_PROJECT_SPEC_VERSION` was bumped.
- [ ] Every renamed / removed upstream field emits `DeprecationWarning`; every warning message names the release the alias is removed in.
- [ ] `tests/darnit/context/test_full_field_coverage.py` passes with no golden-dict update needed (unless a `KEPT-WITH-RESHAPE` intentionally shifted a value; in that case the golden update is part of the PR).
- [ ] The module docstring's reconciliation-history note lists the fields touched.
- [ ] No `packages/darnit-baseline/` file was touched (this feature is core-only per plan §Project Structure).

## Non-goals for the reconciliation PR

- Do NOT expose newly added upstream fields as new `ProjectConfig` attributes (Q1: parse-only). Wiring a new field to a control is a separate feature.
- Do NOT extend `DotProjectWriter` to emit new-shape output. The writer stays scalar-only.
- Do NOT change any `.baseline.toml` or any framework TOML; the reader is orthogonal to control definitions.
