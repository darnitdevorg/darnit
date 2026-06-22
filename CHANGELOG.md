# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Removed

- Top-level `openspec/` directory. The 25 architectural specs that lived under
  `openspec/specs/<topic>/spec.md` were rehomed; the 12 archived proposals
  under `openspec/changes/archive/` were dropped (history preserved in `git log`).
- `scripts/generate_docs.py` and the `docs/generated/` output directory.
- The `doc-generation` job in `.github/workflows/ci.yml` and the
  "Generated docs are up to date" step in `.github/workflows/release.yml`.
- The "Generated docs" gate (item 4) from the Development Workflow in the
  project constitution.
- Pre-commit hook patterns referencing the openspec path.

### Added

- `docs/architecture/` directory containing the 25 rehomed architectural reference
  specs (including the authoritative `framework-design.md`), plus a one-screen
  `README.md` index. These are static reference documentation, not in-flight
  feature specs (those live in `specs/`).
- `specs/017-org-wide-audit-pipeline/` containing the previously in-flight
  openspec proposal, migrated to the speckit spec/plan/tasks layout, with the
  two openspec spec-delta files preserved under `specs/017-org-wide-audit-pipeline/deltas/`.
- This `CHANGELOG.md` file.

### Changed

- The authoritative location of the framework-design specification has moved
  from `openspec/specs/framework-design/spec.md` to
  `docs/architecture/framework-design.md`. The project constitution,
  PR template, `.pre-commit-config.yaml`, `scripts/validate_sync.py`, and
  every reference in `ARCHITECTURE.md`, `CLAUDE.md`, the `docs/` tree, and
  `packaging/README.md` are updated accordingly.
- `scripts/validate_sync.py` was trimmed: the two openspec-dependent checks
  ("Spec Exists" and "Docs Freshness") were removed; the three
  openspec-independent checks (TOML Schema, Pass Types Sync against
  `docs/architecture/framework-design.md`, SARIF Source) are retained.
- The project constitution is bumped to v1.2.0 with a Sync Impact Report
  block documenting the Workflow gate changes and the spec relocation.
- The `_PRUNE_DIRS` set in `packages/darnit-baseline/src/darnit_baseline/remediation/scanner.py`
  no longer lists `"openspec"`.

> **For downstream integrators:** Any tooling that referenced `openspec/...`
> paths will need to update. The constitution's "spec sync" Workflow gate
> continues to apply but is now scoped to TOML schema, handler-name registry,
> and SARIF-from-TOML invariants only -- the openspec-specific "Spec Exists"
> and "Docs Freshness" checks have been removed. See the feature documents
> under `specs/016-openspec-migration/` for the full migration record.
