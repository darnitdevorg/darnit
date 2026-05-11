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

1. Create `kusari-oss/homebrew-tap` as a public repo with the default branch `main` and a stub README.
2. Create a GitHub App (or reuse the org's release App) with `contents: write` on `kusari-oss/homebrew-tap` only.
3. Store the App's installation token as the `HOMEBREW_TAP_TOKEN` secret on `kusari-oss/darnit`.

## Doing a release

1. Confirm the working tree is on `main`, up to date with `origin`, and all CI is green.
2. Bump `version` in every public `pyproject.toml` to the new version. Lockstep — every public package's version must match the tag (preflight enforces this).
3. Push the tag: `git tag v0.1.0 && git push origin v0.1.0`.
4. Watch `.github/workflows/release.yml` in the Actions tab. The workflow runs `preflight` first; if any gate fails, fix and re-tag.
5. After all channel jobs complete, the `finalize` job posts a per-channel timing table to the release notes. If any channel fails or exceeds the 30-min SC-007 budget, a `release-failure` issue is created.

## Recovery from partial failures

See [`RECOVERY.md`](RECOVERY.md). Each channel has a documented recovery path. Reruns of the release workflow on an already-published tag are rejected by design — recovery uses per-channel repair, not workflow retry.

## Workflow files

| File | Purpose |
|---|---|
| `.github/workflows/release.yml` | Tag-triggered orchestrator; fans out per-channel publish jobs |
| `.github/workflows/release-smoke.yml` | Per-channel post-publish smoke tests |
| `.github/workflows/release-yml-lint.yml` | `actionlint` over `release.yml` + `release-smoke.yml` on every PR |
| `.github/workflows/container-edge.yml` | `main`-branch builds tagged `:edge` (unsigned, non-release) |
| `.github/workflows/homebrew-bump.yml` | Cross-repo dispatch to `kusari-oss/homebrew-tap` (stable tags only) |

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
