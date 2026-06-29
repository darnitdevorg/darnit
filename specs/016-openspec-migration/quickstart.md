# Quickstart: Executing the openspec Removal

**Feature**: 016-openspec-migration | **Date**: 2026-06-21

Operational guide for the maintainer (or single-author session) performing the migration. The order below preserves `git log` history on rehomed files (rename detection works only when source still exists at the rename time) and leaves the tree in a buildable state at each commit boundary, defensive against bisect.

## Pre-flight

Before starting, on a clean checkout of `016-openspec-migration`:

1. Confirm starting state of the tooling: `uv run python scripts/validate_sync.py --verbose` exits 0 against the current openspec-based setup. If it doesn't, fix the underlying issue before beginning; otherwise the trim later will confuse "did I break it?" with "was it broken before?".
2. Confirm tests pass: `uv run pytest tests/ --ignore=tests/integration/ -q`.
3. Note your starting constitution version: should be `1.1.0`.

## Step 1 -- Rehome architectural specs

For each of the 26 entries in the data-model.md table (Entity 1), run:

```sh
mkdir -p docs/architecture
git mv "openspec/specs/<topic>/spec.md" "docs/architecture/<topic>.md"
rmdir "openspec/specs/<topic>"  # cleanup empty source directory
```

Then walk every rehomed file with a quick edit pass: rewrite any internal Markdown links of the form `[label](../other-topic/spec.md)` to `[label](./other-topic.md)` (data-model.md "Content adjustments per rehomed file"). A `grep -rln "openspec/specs/" docs/architecture/` should return empty after this pass.

Create `docs/architecture/README.md` using the schema in data-model.md Entity 1.

**Commit boundary**: "docs: rehome 26 architectural specs from openspec to docs/architecture/" -- the tree at this commit has both the new docs/architecture/ AND a still-present openspec/. Buildable.

## Step 2 -- Migrate the active proposal

```sh
mkdir -p specs/017-org-wide-audit-pipeline
git mv openspec/changes/org-wide-audit-pipeline/proposal.md specs/017-org-wide-audit-pipeline/spec.md
git mv openspec/changes/org-wide-audit-pipeline/design.md specs/017-org-wide-audit-pipeline/plan.md
git mv openspec/changes/org-wide-audit-pipeline/tasks.md specs/017-org-wide-audit-pipeline/tasks.md
git rm openspec/changes/org-wide-audit-pipeline/.openspec.yaml
rmdir openspec/changes/org-wide-audit-pipeline
```

Then edit `specs/017-org-wide-audit-pipeline/spec.md` to prepend the speckit spec header (data-model.md Entity 2 "Header injection"). Verify with `head -10 specs/017-org-wide-audit-pipeline/spec.md`.

**Commit boundary**: "specs: migrate org-wide-audit-pipeline proposal from openspec to speckit". Buildable.

## Step 3 -- Delete the openspec directory and its artifacts

At this point `openspec/specs/` and `openspec/changes/` are empty of meaningful content (the rehomed files moved; only `openspec/changes/archive/` and `openspec/config.yaml` remain). Drop everything:

```sh
git rm -r openspec/
git rm scripts/generate_docs.py
git rm -r docs/generated/ 2>/dev/null || true  # ok if absent
```

**Pre-check on `docs/generated/`**: before the `git rm -r`, list its contents (`ls docs/generated/` if it exists). If anything in there looks hand-written rather than auto-generated, stop and surface in code review -- the data-model assumed all content was generate_docs.py output.

**Commit boundary**: "build: delete openspec/, generate_docs.py, and docs/generated/". Tree is now missing openspec but tooling still references it; `validate_sync.py` will fail.

## Step 4 -- Rewire `validate_sync.py`

Edit `scripts/validate_sync.py`:

1. Change `SPEC_PATH` from `PROJECT_ROOT / "openspec" / "specs" / "framework-design" / "spec.md"` to `PROJECT_ROOT / "docs" / "architecture" / "framework-design.md"`.
2. Delete the `validate_spec_exists()` function (and any call to it in the main entrypoint).
3. Delete the `validate_docs_freshness()` function (and any call to it).
4. Update the module docstring's check enumeration to list exactly three checks: TOML Schema, Pass Types Sync, SARIF Source.
5. Update the `--changed-files` flag's behavior to drop any docs-freshness branch.

Verify:

```sh
uv run python scripts/validate_sync.py --verbose
# Expected: All 3 checks pass; no mention of "Spec Exists" or "Docs Freshness".
```

**Commit boundary**: "scripts: trim validate_sync.py to openspec-independent checks". Validate sync now passes.

## Step 5 -- Update reference files

Walk each of these files and rewrite openspec references to point at `docs/architecture/<topic>.md` (or remove entirely for the generate_docs / docs/generated references):

- `ARCHITECTURE.md` -- drop the openspec/ tree from the directory diagram; update the "Authoritative framework specification" row to point at `docs/architecture/framework-design.md`.
- `CLAUDE.md` -- five locations (lines ~186, ~225, ~229, ~241, ~244 in the pre-removal file). Rewrite each: validate_sync.py references stay (now narrower scope), generate_docs.py references are removed entirely.
- `docs/IMPLEMENTATION_GUIDE.md` -- two locations. Path-only rewrites.
- `docs/getting-started/troubleshooting.md` -- two locations. Path-only rewrites.
- `docs/getting-started/development-workflow.md` -- one location. Path-only rewrite.
- `docs/getting-started/framework-development.md` -- two locations. Path-only rewrites.
- `packaging/README.md` -- two lines. Drop the generate_docs.py line; keep the validate_sync.py line with narrower scope.
- `.pre-commit-config.yaml` -- the validate_sync hook's `files:` regex changes from `^(packages/darnit/|openspec/specs/framework-design/)` to `^(packages/darnit/|docs/architecture/framework-design\.md)`.
- `.github/pull_request_template.md` -- the framework-spec checkbox row updates path: `openspec/specs/framework-design/spec.md` -> `docs/architecture/framework-design.md`.
- `packages/darnit-baseline/src/darnit_baseline/remediation/scanner.py` -- remove the `"openspec"` string from the `_PRUNE_DIRS` set (line ~211 in current file).

After this step: `grep -rln openspec --exclude-dir=.git --exclude-dir=specs --exclude=CHANGELOG.md .` should return empty.

**Commit boundary**: "docs/config: rewrite openspec references to docs/architecture/". Buildable.

## Step 6 -- Amend the constitution

Edit `.specify/memory/constitution.md` per data-model.md Entity 4:

1. Bump `**Version**` from `1.1.0` to `1.2.0`.
2. Update `**Last Amended**` to today's date.
3. Add a new Sync Impact Report block at the top (after the existing 1.0.0->1.1.0 block, before the "Darnit Constitution" H1) describing this amendment.
4. Replace the openspec/ path in the "Spec-Implementation Synchronization" section with `docs/architecture/framework-design.md`.
5. Edit the Development Workflow section: rewrite item 3 (Spec sync) with the narrower scope; delete item 4 (Generated docs) entirely; renumber subsequent items if applicable.
6. Edit the Sync Enforcement Rules section: rewrite item 2 (TOML is Source of Truth -- only the closing reference to the spec path); delete item 3 (Generated Docs Must Stay Fresh).
7. Edit the CI Enforces Sync block to remove the "Generated docs would change" bullet.
8. Edit the Validation Commands code block to drop the `uv run python scripts/generate_docs.py` line and any subsequent `git diff docs/generated/` commands.

Verify the constitution validates:

```sh
grep -n openspec .specify/memory/constitution.md   # expect empty
grep -n "1.2.0" .specify/memory/constitution.md    # expect at least one match
grep -n "docs/architecture/framework-design.md" .specify/memory/constitution.md  # expect at least one
```

**Commit boundary**: "constitution: bump to 1.2.0; replace openspec references with docs/architecture/". Buildable.

## Step 7 -- Create CHANGELOG.md

Create `CHANGELOG.md` at the repo root using the template in data-model.md Entity 3. Fill the `[Unreleased]` section with the migration entry. Include the downstream-integrator callout.

**Commit boundary**: "docs: add CHANGELOG.md with openspec migration entry".

## Step 8 -- Final verification

Run every Workflow gate from the post-amendment constitution:

```sh
uv run ruff check .                                 # zero errors
uv run pytest tests/ --ignore=tests/integration/ -q # all pass, no new failures
uv run python scripts/validate_sync.py --verbose    # 3 checks pass; no "Spec Exists" / "Docs Freshness" mentions
```

Then run the spec's success-criteria checks directly:

```sh
find . -type d -name openspec -not -path "*/.git/*"  # SC-001: empty
grep -rln openspec --exclude-dir=.git --exclude-dir=specs --exclude=CHANGELOG.md . 
                                                       # SC-002: empty
ls docs/architecture/*.md | wc -l                     # SC-005: 27 (26 specs + README)
ls specs/017-org-wide-audit-pipeline/                 # SC-004: spec.md, plan.md, tasks.md
```

If any of the above fail, do NOT proceed to PR -- the failure indicates a step was missed.

## Sanity check before opening PR

- [ ] Single PR contains all of steps 1-7; no follow-up PR needed.
- [ ] Commit history shows renames (`git log --follow docs/architecture/framework-design.md` traces back into `openspec/specs/framework-design/spec.md`).
- [ ] PR description names the new framework-design path and links to the CHANGELOG entry.
- [ ] PR description includes the downstream-integrator notice.
- [ ] Pre-commit hook passes (`pre-commit run --all-files`).
- [ ] No `openspec` string in the working tree outside `CHANGELOG.md`, `specs/` (historical task records), and `.git/`.
