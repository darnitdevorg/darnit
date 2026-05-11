# Contract: Release Workflow

The contract between a git tag and the release pipeline.

## Trigger

The workflow `.github/workflows/release.yml` triggers on:

```yaml
on:
  push:
    tags:
      - 'v[0-9]+.[0-9]+.[0-9]+'        # stable
      - 'v[0-9]+.[0-9]+.[0-9]+rc[0-9]+' # pre-release
```

Tags outside these patterns are ignored. Manual `workflow_dispatch` is not exposed for releases — every release is tag-driven.

## Inputs (implicit)

- `github.ref_name`: the tag literal (e.g., `v0.1.0` or `v0.1.0rc1`).
- `github.sha`: the resolved commit SHA.
- `secrets.GITHUB_TOKEN`: with `contents: write`, `packages: write`, `id-token: write`, `attestations: write` permissions.

Externally-configured Trusted Publishers (PyPI + TestPyPI) keyed by the repo + workflow path are required. Configuration is documented in `packaging/README.md`.

## Pre-flight gates

The workflow runs the following in sequence as the first job (`preflight`). Any failure aborts the workflow before any channel publishes.

| Step | Pass condition |
|---|---|
| Tag pattern matches `^v\d+\.\d+\.\d+(rc\d+)?$` | Regex match |
| Tag has no existing GitHub Release | `gh release view $TAG` returns 404 |
| Every public `pyproject.toml` has `version = <tag-stripped>` | Per-file grep |
| `uv run ruff check .` | Exit 0 |
| `uv run pytest tests/ --ignore=tests/integration/ -q` | Exit 0 |
| `uv run python scripts/validate_sync.py --verbose` | Exit 0 |
| `uv run python scripts/generate_docs.py` produces no diff | `git diff --exit-code docs/generated/` |

## Job graph

```
preflight
   │
   ├─► pypi_publish ─► pypi_smoke
   │
   ├─► container_build_push ─► container_smoke
   │       (depends on pypi_publish: image installs from PyPI)
   │
   ├─► binary_matrix (×4) ─► binary_smoke
   │
   ├─► [stable] homebrew_dispatch ─► homebrew_smoke (poll-until-merged)
   │       (depends on binary_matrix: formula points at binaries)
   │
   ├─► [stable] plugin_package ─► plugin_smoke
   │       (depends on pypi_publish: plugin invokes uvx darnit-mcp@<version>)
   │
   └─► finalize (always; aggregates state, posts summary, creates issue on partial failure)
```

`if: failure()` is used only on `finalize` to ensure it runs regardless of upstream job status. Sibling jobs do **not** cancel each other.

## Outputs

For each successful per-channel job, the workflow exposes:

- `artifact_uri` (string): canonical published URI.
- `digest` (string): SHA-256 of the artifact body.
- `attestation_uri` (string): location of the verifiable attestation.

These are surfaced in the GitHub Actions job summary and consumed by the `finalize` job for the release summary.

## Failure semantics

| Failure point | Effect |
|---|---|
| Preflight gate fails | Workflow stops; `Release.state = pending`; no channel publishes; **no** `release-failure` issue (the maintainer's tag was invalid). |
| Workflow exceeds 30-min timeout (stable tags) | All in-flight per-channel jobs are cancelled; `Release.state = partial_failure`; `finalize` creates a `release-failure` issue naming the channel(s) that did not complete. (SC-007 enforcement.) |
| One channel job fails, others succeed | Successful channels remain published. `finalize` sets `Release.state = partial_failure` and creates a `release-failure` GitHub issue naming the failing channel(s). |
| One channel exceeds its SC-007 budget but completes | Channel artifact is published, but `finalize` flags the channel in the release notes and creates a `release-failure` issue if total tag-to-publish time >30 min. |
| All channel jobs fail | `Release.state = partial_failure` with all channels listed in the issue. |
| Smoke test fails for a channel that successfully published | The channel artifact stays published (already user-visible), but the issue is created and the smoke failure is named. Spec edge case: pre-release artifacts are immutable. |

## Permissions

The release workflow requests the **minimum** permissions needed:

```yaml
permissions:
  contents: write          # create GH releases, upload assets
  packages: write          # push to GHCR
  id-token: write          # OIDC for Trusted Publishing + cosign keyless
  attestations: write      # GitHub Artifact Attestations for SBOMs
  issues: write            # create release-failure issues
```

No other repo-level secrets are referenced. The workflow refuses to run if it detects any long-lived publishing token in its environment.

## Idempotency

Re-running the workflow on the same tag (manual rerun) is **rejected**: the preflight gate "no existing GitHub Release for this tag" fails. Recovery is per-channel and uses dedicated repair scripts in `packaging/RECOVERY.md`, not workflow rerun.
