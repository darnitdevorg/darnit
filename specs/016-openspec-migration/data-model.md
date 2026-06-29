# Phase 1 Data Model: openspec Removal Deliverables

**Feature**: 016-openspec-migration | **Date**: 2026-06-21

No runtime data is added or removed. The "data model" here is the file-level shape of the deliverables: what gets created, what gets moved, what gets deleted, and what each new/modified file must contain.

## Entity 1 -- `docs/architecture/` directory

New top-level documentation directory. Hosts the 26 rehomed architectural specs as flat Markdown files plus a one-screen README index.

### Required contents

| File | Source | Notes |
|---|---|---|
| `README.md` | new | One-screen index. Lists all 26 docs with one-line descriptions. Replaces the implicit "openspec/specs/ as a folder of folders" navigation. |
| `framework-design.md` | `git mv openspec/specs/framework-design/spec.md` | Constitutional reference target. Must remain the path named by the constitution post-amendment. |
| `audit-pipeline.md` | `git mv openspec/specs/audit-pipeline/spec.md` | |
| `audit-context-collection.md` | `git mv openspec/specs/audit-context-collection/spec.md` | |
| `cel-expressions.md` | `git mv openspec/specs/cel-expressions/spec.md` | |
| `ci-workflow-templates.md` | `git mv openspec/specs/ci-workflow-templates/spec.md` | |
| `conditional-controls.md` | `git mv openspec/specs/conditional-controls/spec.md` | |
| `context-collection.md` | `git mv openspec/specs/context-collection/spec.md` | |
| `context-documentation.md` | `git mv openspec/specs/context-documentation/spec.md` | |
| `control-dependencies.md` | `git mv openspec/specs/control-dependencies/spec.md` | |
| `declarative-file-templates.md` | `git mv openspec/specs/declarative-file-templates/spec.md` | |
| `dot-project-integration.md` | `git mv openspec/specs/dot-project-integration/spec.md` | |
| `example-plugin.md` | `git mv openspec/specs/example-plugin/spec.md` | |
| `external-templates.md` | `git mv openspec/specs/external-templates/spec.md` | |
| `framework-agnostic-reporting.md` | `git mv openspec/specs/framework-agnostic-reporting/spec.md` | |
| `github-api-remediation.md` | `git mv openspec/specs/github-api-remediation/spec.md` | |
| `handler-pipeline.md` | `git mv openspec/specs/handler-pipeline/spec.md` | |
| `implementation-provided-tools.md` | `git mv openspec/specs/implementation-provided-tools/spec.md` | |
| `org-project-resolution.md` | `git mv openspec/specs/org-project-resolution/spec.md` | |
| `plugin-registry.md` | `git mv openspec/specs/plugin-registry/spec.md` | |
| `policy-doc-templates.md` | `git mv openspec/specs/policy-doc-templates/spec.md` | |
| `remediation-audit-filtering.md` | `git mv openspec/specs/remediation-audit-filtering/spec.md` | |
| `remediation-manual-guidance.md` | `git mv openspec/specs/remediation-manual-guidance/spec.md` | |
| `repo-identity-resolution.md` | `git mv openspec/specs/repo-identity-resolution/spec.md` | |
| `shared-handlers.md` | `git mv openspec/specs/shared-handlers/spec.md` | |
| `sieve-handler-authoring.md` | `git mv openspec/specs/sieve-handler-authoring/spec.md` | |

Count: 26 source files + 1 new index = 27 files in `docs/architecture/`.

### Content adjustments per rehomed file

For each rehomed file: light edits only. Specifically:

- The H1 title is preserved as-is.
- Any internal Markdown links of the form `[label](../other-topic/spec.md)` are rewritten to `[label](./other-topic.md)` to match the flat layout.
- Any internal references to `openspec/specs/` paths in prose are rewritten to `docs/architecture/`.
- No new content is added. No paragraphs are deleted. The migration is a relocation, not a rewrite.

### `README.md` schema

```markdown
# Architecture Documentation

Reference documentation describing how darnit's framework, sieve pipeline,
plugin system, and remediation engine are organized. These are static
reference docs, not in-flight feature specs (those live in `specs/`).

## Framework foundations

- [Framework design](./framework-design.md) -- authoritative framework specification
- [Plugin registry](./plugin-registry.md)
- [Handler pipeline](./handler-pipeline.md)
- ...

## Audit lifecycle

- [Audit pipeline](./audit-pipeline.md)
- [Audit context collection](./audit-context-collection.md)
- ...

(remaining sections grouped by domain)
```

### Validation rules

| Rule | Check |
|---|---|
| All 26 architectural specs present | `ls docs/architecture/*.md \| wc -l` -> 27 (26 specs + README.md) |
| `framework-design.md` exists at the canonical path | `test -f docs/architecture/framework-design.md` |
| No internal openspec/ link survives | `grep -rln "openspec/" docs/architecture/` -> empty |
| Each former openspec spec is represented | For each topic in the 26-row table above, `test -f docs/architecture/<topic>.md` |

## Entity 2 -- `specs/017-org-wide-audit-pipeline/` directory

New speckit feature directory hosting the migrated in-flight proposal.

### Required contents

| File | Source | Notes |
|---|---|---|
| `spec.md` | `git mv openspec/changes/org-wide-audit-pipeline/proposal.md` | Add speckit spec header; body content preserved |
| `plan.md` | `git mv openspec/changes/org-wide-audit-pipeline/design.md` | Add speckit plan header; body content preserved |
| `tasks.md` | `git mv openspec/changes/org-wide-audit-pipeline/tasks.md` | No rename needed; speckit and openspec both use `tasks.md` |
| (dropped) | `openspec/changes/org-wide-audit-pipeline/.openspec.yaml` | Openspec-specific metadata; no speckit equivalent |

### Header injection (spec.md)

At the top of the new `spec.md`, prepend (before the existing proposal body):

```markdown
# Feature Specification: Org-Wide Audit Pipeline

**Feature Branch**: `017-org-wide-audit-pipeline` (not yet created)

**Created**: <original creation date if known from openspec, else "migrated from openspec, original date in git log">

**Status**: Migrated from openspec on 2026-06-21; not yet started

**Input**: (preserve the original openspec proposal's framing here)

---

<original proposal.md body follows>
```

### Validation rules

| Rule | Check |
|---|---|
| All three speckit files present | `ls specs/017-org-wide-audit-pipeline/{spec,plan,tasks}.md` succeeds |
| `.openspec.yaml` not migrated | `test ! -f specs/017-org-wide-audit-pipeline/.openspec.yaml` |
| Content preserved | For each migrated file, `wc -l` is >= the original openspec file's line count (header was added, not removed) |

## Entity 3 -- `CHANGELOG.md`

New top-level changelog file. Created by this feature.

### Required content

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Removed

- Top-level `openspec/` directory (specs and proposals previously tracked here).
- `scripts/generate_docs.py` and the `docs/generated/` directory.
- The "Generated docs freshness" gate from the Development Workflow.

### Added

- `docs/architecture/` directory containing 26 architectural reference specs
  rehomed from `openspec/specs/`.
- `specs/017-org-wide-audit-pipeline/` containing the previously in-flight
  proposal from `openspec/changes/org-wide-audit-pipeline/`.
- This `CHANGELOG.md` file.

### Changed

- The authoritative location of the framework-design specification has moved
  from `openspec/specs/framework-design/spec.md` to
  `docs/architecture/framework-design.md`. The constitution, PR template,
  pre-commit hook, and `scripts/validate_sync.py` are updated accordingly.
- The project constitution is bumped to v1.2.0.

> **For downstream integrators:** Any tooling that referenced
> `openspec/...` paths will need to update. The constitution's "spec sync"
> Workflow gate continues to apply but is now scoped to TOML schema,
> handler-name registry, and SARIF-from-TOML invariants only -- the
> openspec-specific "Spec Exists" and "Docs Freshness" checks have been
> removed. See PR #<N> for details.
```

### Validation rules

| Rule | Check |
|---|---|
| Top-level file exists | `test -f CHANGELOG.md` |
| Contains the migration entry under `[Unreleased]` | `grep -A1 "## \[Unreleased\]" CHANGELOG.md` returns the new section |
| Mentions the new framework-design path | `grep -q "docs/architecture/framework-design.md" CHANGELOG.md` |
| Mentions the constitution bump | `grep -q "1.2.0" CHANGELOG.md` |

## Entity 4 -- Constitution amendment (`.specify/memory/constitution.md`)

Existing file; this feature modifies it in three places.

### Required edits

| Location | Before | After |
|---|---|---|
| Header version | `**Version**: 1.1.0` | `**Version**: 1.2.0` |
| Header last-amended | `**Last Amended**: 2026-03-08` | `**Last Amended**: 2026-06-21` |
| Sync Impact Report block at top | (none -- existing block describes the 1.0.0->1.1.0 bump) | Append a new block describing the 1.1.0->1.2.0 bump |
| "Spec-Implementation Synchronization" intro | `governed by the authoritative specification at: openspec/specs/framework-design/spec.md` | `governed by the authoritative specification at: docs/architecture/framework-design.md` |
| Development Workflow item 3 | `Spec sync: uv run python scripts/validate_sync.py --verbose -- framework-design spec matches implementation.` | `Spec sync: uv run python scripts/validate_sync.py --verbose -- TOML schema validity, handler-name registry consistency, SARIF-from-TOML invariant.` |
| Development Workflow item 4 | `Generated docs: uv run python scripts/generate_docs.py then check git diff docs/generated/ -- commit any changes.` | (deleted; subsequent items renumbered) |
| Sync Enforcement Rules item 2 (closing parenthetical) | `Run uv run python scripts/validate_sync.py --verbose; Ensure pass types in code match spec definitions.` | `Run uv run python scripts/validate_sync.py --verbose; ensure handler names in code match docs/architecture/framework-design.md.` |
| Sync Enforcement Rules item 3 (Generated Docs Must Stay Fresh) | (entire item present) | (entire item deleted) |
| CI Enforces Sync bullet 3 ("Generated docs would change") | (bullet present) | (bullet deleted) |
| Validation Commands section | (includes `uv run python scripts/generate_docs.py` command) | (that command removed; the remaining commands kept) |

### Validation rules

| Rule | Check |
|---|---|
| Version header reflects bump | `grep "Version.*1\.2\.0" .specify/memory/constitution.md` returns a match |
| No openspec paths remain | `grep -n "openspec" .specify/memory/constitution.md` returns empty |
| New canonical path is referenced | `grep -n "docs/architecture/framework-design.md" .specify/memory/constitution.md` returns at least one match |
| Sync Impact Report block present | `grep -B1 "1.1.0 -> 1.2.0" .specify/memory/constitution.md` returns the new block |

## Entity 5 -- Trimmed `scripts/validate_sync.py`

Existing file; modified by this feature.

### Required edits

- Remove `SPEC_PATH = PROJECT_ROOT / "openspec" / ...` -- replace with `SPEC_PATH = PROJECT_ROOT / "docs" / "architecture" / "framework-design.md"`.
- Delete `validate_spec_exists()` function and its registration in the main validator list.
- Delete `validate_docs_freshness()` function and its registration in the main validator list.
- `validate_pass_types_sync()` is retained as-is; its `SPEC_PATH.read_text()` call now reads the rehomed file.
- Update module docstring to enumerate the three surviving checks.
- Update `--changed-files` flag's effect to drop docs-freshness logic if any.

### Validation rules

| Rule | Check |
|---|---|
| No openspec import / constant remains | `grep -n openspec scripts/validate_sync.py` returns empty |
| `SPEC_PATH` points to the new location | `grep "SPEC_PATH" scripts/validate_sync.py` matches `docs/architecture/framework-design.md` |
| Script exits zero on clean checkout | `uv run python scripts/validate_sync.py --verbose` exits 0 |
| Three checks reported | Script output mentions exactly three check categories (TOML Schema, Pass Types Sync, SARIF Source) |

## Entity 6 -- Removals

These are not "entities" so much as "tree state" -- the absences that the validation rules of FR-001 and SC-001 / SC-002 require.

| Path | Action |
|---|---|
| `openspec/` (entire dir) | `git rm -r openspec/` (after rehome step) |
| `scripts/generate_docs.py` | `git rm scripts/generate_docs.py` |
| `docs/generated/` (if present) | `git rm -r docs/generated/` |

### Validation rules

| Rule | Check |
|---|---|
| No `openspec/` directory in working tree | `find . -type d -name openspec -not -path "*/.git/*"` returns empty |
| `generate_docs.py` deleted | `test ! -f scripts/generate_docs.py` |
| `docs/generated/` absent | `test ! -d docs/generated` |
| Repo-wide grep for openspec returns no current-tree hits | `grep -rln openspec --exclude-dir=.git --exclude-dir=specs --exclude=CHANGELOG.md .` returns empty |

(Note on the grep exclusions in SC-002: `specs/` is excluded because historical speckit feature dirs -- e.g. `specs/010-threat-model-ast/tasks.md` -- legitimately contain "ran validate_sync.py against openspec" notes as part of their task completion records; rewriting them would be falsifying history. `CHANGELOG.md` is excluded because the migration entry itself names openspec.)

## Cross-document invariants

| Invariant | Documents involved | Check |
|---|---|---|
| Constitution names a real path | constitution.md, docs/architecture/framework-design.md | The path the constitution cites resolves to an existing file |
| validate_sync.py reads the same path the constitution cites | constitution.md, scripts/validate_sync.py | `grep SPEC_PATH scripts/validate_sync.py` matches the path string in constitution's Spec-Implementation Synchronization section |
| Pre-commit hook scopes match the constitution's gates | .pre-commit-config.yaml, constitution.md | The hook's `files:` pattern includes `docs/architecture/framework-design.md` (the file the constitution cites) and not `openspec/` |
| PR template's framework-spec checkbox points at the canonical location | .github/pull_request_template.md, constitution.md | Checkbox row in PR template names the same path as the constitution |
| README files don't contradict | docs/architecture/README.md, ARCHITECTURE.md, CLAUDE.md | None of them reference `openspec/` paths after the change |
