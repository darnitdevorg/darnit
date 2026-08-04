# Vendored OSPS Baseline (source-of-truth for the per-level regression test)

This directory contains an exact copy of the `baseline/OSPS-*.yaml` files from
[ossf/security-baseline](https://github.com/ossf/security-baseline) at tag
`v2026.02.19`.

The per-level regression test at
`tests/darnit_baseline/test_level_counts.py` parses these files as the
authoritative applicability map for the `spec_version` pinned in the
darnit-baseline implementation.

## Bumping the pinned version

1. Fetch new files: for each `OSPS-XX.yaml`, replace with the version at the
   target upstream tag (`raw.githubusercontent.com/ossf/security-baseline/<TAG>/baseline/OSPS-XX.yaml`).
2. Update `spec_version` in `packages/darnit-baseline/src/darnit_baseline/implementation.py`.
3. Update the tag reference in this README.
4. Run `uv run pytest tests/darnit_baseline/test_level_counts.py -v`. If it
   fails, the diff will list the specific control-level drift; reconcile
   `packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml` accordingly.
5. Update the counts in `docs/USAGE_GUIDE.md`.

## Vendored at

- Upstream repo: https://github.com/ossf/security-baseline
- Upstream tag: `v2026.02.19`
- Vendored on: 2026-07-31
- Files copied verbatim (no reformatting) so future bumps produce a
  reviewable diff.
