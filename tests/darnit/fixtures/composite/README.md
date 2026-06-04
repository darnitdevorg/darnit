# Composite-implementation test fixtures

This directory holds the hand-authored TOML fixtures used by
`tests/darnit/test_composition.py`. The fixture-driven approach follows
research decision R-010 in `specs/013-plugin-composition/research.md`:

- Tests load each fixture through the **production** loader
  (`darnit.config.merger.load_framework_config` for end-to-end coverage,
  or `darnit.config.merger._parse_framework_only` for resolver-isolated
  tests via the `fixture_source_loader` conftest helper). Catching
  schema-binding bugs is part of the test surface, not just resolver
  correctness.
- Hand-authored TOML matches the actual composite-author experience and
  doubles as concrete documentation for the contract.
- Each scenario gets its own fixture; we avoid mega-fixtures with toggles.

Subdirectories:

- `_sources/` — non-composite framework TOMLs that composites pull from
  (`mock-source-a.toml`, `mock-source-b.toml`, leaf/middle layers for
  recursive scenarios, cycle pairs for the F-1 regression test, etc.).
- The composite fixtures themselves live at the root of this directory
  (e.g., `basic-include-all.toml`, `strict-conflict.toml`, ...).
