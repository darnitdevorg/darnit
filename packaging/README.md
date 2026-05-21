# Packaging & Release Runbook

Maintainer-facing documentation for the darnit release pipeline. End-user install instructions live in [`docs/install/`](../docs/install/).

> **Canonical repository home**: `https://github.com/kusari-oss/darnit`
>
> Earlier metadata referenced `kusaridev/darnit-mcp` and `kusaridev/baseline-mcp`. Those names are deprecated. All package URLs, workflow identities, and Sigstore signing certificates resolve against `kusari-oss/darnit`.

## Overview

darnit is released through five user-facing channels from a single tag-driven pipeline:

| Channel | Surface | Stable | Pre-release | Contract |
|---|---|---|---|---|
| PyPI | `pypi.org/project/darnit-*` | ✅ | TestPyPI | [pypi-publish-contract.md](../specs/012-packaging-distribution/contracts/pypi-publish-contract.md) |
| Container | `ghcr.io/kusari-oss/darnit` | ✅ | ✅ (`-rc` tags) | [container-image-contract.md](../specs/012-packaging-distribution/contracts/container-image-contract.md) |
| Binary | GitHub Release assets | ✅ | ✅ (marked pre-release) | [binary-artifact-contract.md](../specs/012-packaging-distribution/contracts/binary-artifact-contract.md) |
| Homebrew | `kusari-oss/homebrew-tap` | ✅ | ❌ (stable only) | [homebrew-formula-contract.md](../specs/012-packaging-distribution/contracts/homebrew-formula-contract.md) |
| Claude Code plugin | GitHub Release asset | ✅ | ❌ (stable only) | [claude-plugin-contract.md](../specs/012-packaging-distribution/contracts/claude-plugin-contract.md) |

All releases are tag-driven. Tag patterns: `v<X.Y.Z>` (stable) or `v<X.Y.Z>rc<N>` (pre-release).

## Public package set

Authoritative list: [`packaging/pypi/public-packages.txt`](pypi/public-packages.txt). The release workflow refuses to publish anything not in that list. Internal packages (`darnit-example`, `darnit-testchecks`, `darnit-plugins`) live in `packages/` but are never published to PyPI.

## External setup (one-time)

Before the first release works end-to-end, a maintainer with admin access must:

### PyPI Trusted Publishing (T004)

For each public package (`darnit`, `darnit-baseline`, `darnit-gittuf`, `darnit-mcp`):

1. Reserve the project name on pypi.org by uploading a `0.0.0` placeholder release manually, OR claim the name through PyPI's project-reservation process.
2. On the project's "Publishing" settings page, add a Trusted Publisher:
   - Owner: `kusari-oss`
   - Repository: `darnit`
   - Workflow: `release.yml`
   - Environment: `release`

### TestPyPI Trusted Publishing (T005)

Mirror the four configurations above on `test.pypi.org`. Used for pre-release (`-rc`) tags only.

### Homebrew tap (T040–T041)

1. Create `kusari-oss/homebrew-tap` as a public repo with the default branch `main` and a stub README. Copy `packaging/homebrew/tap-workflows/{bump-formula.yml,ci.yml}` into the tap repo's `.github/workflows/`.
2. Provide a credential the release pipeline can use to fire a `repository_dispatch` against the tap repo. Two options, simplest first:
   - **Fine-grained PAT** (recommended for low-cadence projects). Create at https://github.com/settings/personal-access-tokens/new with **Repository access → Only select repositories → `kusari-oss/homebrew-tap`** and **Repository permissions → Contents: Read and write**. Trade-off: tied to your user account; rotates when you re-issue the PAT.
   - **GitHub App** (recommended once release cadence justifies the polish). Create an App with `contents: write` on `kusari-oss/homebrew-tap` only; install on the tap repo; store the App-issued installation token (or app-id + private-key pair the workflow exchanges for one) as the secret. Trade-off: more setup; rotatable; not tied to a user account.

   The dispatch step in `release.yml` uses bearer auth (`Authorization: Bearer ${HOMEBREW_TAP_TOKEN}`), which works identically for both options. Swap between them at any time without touching the workflow.

3. Store the credential as the `HOMEBREW_TAP_TOKEN` secret on the `release` environment of `kusari-oss/darnit`:
   ```bash
   gh secret set HOMEBREW_TAP_TOKEN --repo kusari-oss/darnit --env release
   ```

## Doing a release

### Pre-flight (before tagging)

1. **Sync `main` from upstream and confirm CI is green.**
   ```bash
   git checkout main
   git fetch upstream && git merge --ff-only upstream/main
   gh run list --branch main --limit 5
   ```
2. **Decide the version.** Stable releases are `vX.Y.Z`; pre-releases are `vX.Y.ZrcN` (no hyphen — PEP 440 canonical). Use a pre-release tag if this is the first run after a non-trivial release-pipeline change.
3. **Bump `version` in every public `pyproject.toml`.** The four public packages must agree exactly with the tag (preflight enforces this):
   - `pyproject.toml` (the root `darnit-mcp` package)
   - `packages/darnit/pyproject.toml`
   - `packages/darnit-baseline/pyproject.toml`
   - `packages/darnit-gittuf/pyproject.toml`
4. **Sync and verify locally:**
   ```bash
   uv sync --all-extras
   uv run ruff check .
   uv run pytest tests/ --ignore=tests/integration/ -q
   uv run python scripts/validate_sync.py --verbose
   uv run python scripts/generate_docs.py
   git diff --exit-code docs/generated/   # no diff allowed
   ```
5. **Commit and push the version bump:**
   ```bash
   git add -p   # review carefully
   git commit -m "release: vX.Y.Z"
   git push upstream main
   ```

### Cut the tag

```bash
git tag vX.Y.Z          # or vX.Y.ZrcN for pre-release
git push upstream vX.Y.Z
```

The `release.yml` workflow triggers automatically. **No `--force` or amend** — once a tag is pushed and `release.yml` starts, the only way out of a bad release is roll-forward to a new tag.

### Monitor

1. Open the [Actions tab](https://github.com/kusari-oss/darnit/actions). The `Release` workflow should appear within a few seconds of tag push.
2. Watch `preflight` first. If it fails:
   - Most common: version mismatch between tag and `pyproject.toml`. Delete the tag (`git push upstream --delete vX.Y.Z`), fix the bump commit, push a new tag.
   - Other gates (lint/tests/sync/doc-gen) should have been caught in pre-flight above. If they fire here, you skipped step 4.
3. Once preflight is green, channel jobs run in parallel: `pypi_publish` → `container_build_push` + `binary_matrix`; then `release_attach_binaries`, `homebrew_dispatch` (stable only), `plugin_package` (stable only); then `finalize`.
4. **SC-007 budget**: stable releases are wall-clocked at 30 minutes (workflow-level timeout). Pre-releases are uncapped.

### After the workflow completes

- `finalize` posts a per-channel timing table to the GitHub Release notes.
- For stable tags only: if any channel failed OR exceeded its budget, `finalize` opens a `release-failure` issue tagged with the channel name(s).
- Run smoke tests (`Release Smoke Tests` workflow) — they trigger automatically on workflow_run.
- Verify the user-facing surfaces:
  ```bash
  pip install darnit-mcp==X.Y.Z
  docker pull ghcr.io/kusari-oss/darnit:vX.Y.Z
  # stable only:
  brew tap kusari-oss/tap && brew install darnit
  ```

### If something goes wrong mid-release

- **A single channel job failed**: see [`RECOVERY.md`](RECOVERY.md). Per-channel repair, never re-run the workflow.
- **The workflow hit the 30-minute timeout**: all in-flight jobs are cancelled. The `finalize` job (with `if: always()`) still runs and surfaces the timeout in a `release-failure` issue. Recovery: roll forward to `vX.Y.Z+1`.
- **`preflight` failed AFTER the tag was created on a remote runner** (e.g., a transient PyPI auth issue): delete the tag from the remote, fix the underlying cause, re-tag with the SAME version (no GH Release exists yet so the immutability gate doesn't fire). This is the ONLY case where re-tagging the same version is safe.

### Post-release housekeeping

1. Announce the release internally / on the project's communication channels.
2. Bump the version in `main` to the next `0.0.0-dev` placeholder if the project uses that convention (we don't currently — versions stay at the just-released value until the next bump).
3. Close any release-blocker issues; open follow-ups for any deferred work.

## Recovery from partial failures

See [`RECOVERY.md`](RECOVERY.md). Each channel has a documented recovery path. Reruns of the release workflow on an already-published tag are rejected by design — recovery uses per-channel repair, not workflow retry.

## Workflow files

| File | Purpose |
|---|---|
| `.github/workflows/release.yml` | Tag-triggered orchestrator; fans out per-channel publish jobs |
| `.github/workflows/release-smoke.yml` | Per-channel post-publish smoke tests |
| `.github/workflows/release-yml-lint.yml` | `actionlint` over `release.yml` + `release-smoke.yml` on every PR |
| `.github/workflows/container-edge.yml` | `main`-branch builds tagged `:edge` (unsigned, non-release) |
| `.github/workflows/release.yml::homebrew_dispatch` job | Cross-repo dispatch to `kusari-oss/homebrew-tap` (stable tags only) |
| `packaging/homebrew/tap-workflows/` | Reference copies of the workflows that live in `kusari-oss/homebrew-tap` (`bump-formula.yml`, `ci.yml`) — copy into the tap repo on initial setup |

### Pinned tool versions

These tools are pinned in the release workflows. **Local installations must match** so contributors catch issues before CI does. If you bump one, update all three sites (the two workflow files and this table) in the same PR.

| Tool | Pinned version | Where |
|---|---|---|
| `actionlint` | `v1.7.12` (linux/amd64 sha256 `8aca8db9...349a3d8`) | `release.yml` preflight + `release-yml-lint.yml` |

#### Local install (macOS via Homebrew)

```bash
brew install actionlint
# Verify the version matches the CI pin
actionlint -version
# Expected first line: 1.7.12
```

If `brew install actionlint` gives you an older version, force the pinned version with `brew install rhysd/tap/actionlint` or download the binary directly from the [releases page](https://github.com/rhysd/actionlint/releases/tag/v1.7.12).

Why bumping matters: the runner-label database is built into actionlint, so an older local copy will miss newer GitHub-hosted runners (e.g., `ubuntu-24.04-arm`). A workflow that lints clean locally on an older `actionlint` may still fail CI's pinned version, or vice-versa.

## Where things live

- `packaging/pypi/` — public package list
- `packaging/container/` — Dockerfile + entrypoint
- `packaging/binary/` — shiv config + platform matrix
- `packaging/homebrew/` — formula template + tap README
- `packaging/claude-plugin/` — manifest + build script
- `packaging/RECOVERY.md` — partial-failure recovery procedures
- `docs/install/` — end-user install documentation (one file per channel + a decision tree)
- `docs/packaging-plugins.md` — third-party plugin packaging guide (separate concern from this runbook)

## See also

- [`specs/012-packaging-distribution/spec.md`](../specs/012-packaging-distribution/spec.md) — feature spec
- [`specs/012-packaging-distribution/plan.md`](../specs/012-packaging-distribution/plan.md) — implementation plan
- [`specs/012-packaging-distribution/tasks.md`](../specs/012-packaging-distribution/tasks.md) — task list
