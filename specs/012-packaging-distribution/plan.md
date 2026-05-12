# Implementation Plan: Packaging & Distribution Channels

**Branch**: `012-packaging-distribution` | **Date**: 2026-05-11 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/012-packaging-distribution/spec.md`

## Summary

Stand up a tag-driven release pipeline that publishes every darnit release to five user-facing channels from a single commit: the Python Package Index (and TestPyPI for pre-releases), a multi-arch container image on GitHub's Container Registry, standalone single-file binaries for macOS/Linux on arm64/amd64, a Homebrew formula in a project-owned tap, and a Claude Code plugin manifest. All artifacts are signed (Sigstore for wheels, cosign for the image, attached attestations for binaries) and accompanied by SBOMs where the channel supports them.

The implementation adds a new top-level `packaging/` directory containing per-channel configuration (Dockerfile, shiv binary configs, plugin manifest source, Homebrew formula template), a single `.github/workflows/release.yml` GitHub Actions workflow that orchestrates the fan-out, a separate `kusari-oss/homebrew-tap` repository for the formula, and a `docs/install/` documentation tree. No changes are required in the framework (`packages/darnit/`) or any existing implementation package — packaging sits orthogonal to the audit pipeline.

## Technical Context

**Language/Version**: Python 3.11/3.12 (workspace targets) plus bash for release scripts and GitHub Actions YAML
**Primary Dependencies**: `shiv` (binary builder), `cosign` (image + binary signing), `syft` (SBOM generation), `docker buildx` (multi-arch images), `gh` CLI (release creation), Sigstore-action (PyPI wheel signing via `pypa/gh-action-pypi-publish`). No new runtime dependencies in any darnit Python package.
**Storage**: External release surfaces only — PyPI, TestPyPI, GHCR, GitHub Releases (binary assets + attestations), `kusari-oss/homebrew-tap` repo (formula). Repo itself stores only build configs and workflow definitions.
**Testing**: Per-channel smoke tests in CI (`pip install` from TestPyPI; `docker run` from GHCR pre-release tag; `darnit --version` from each binary; `brew install` from the tap; Claude Code plugin install in a hermetic Claude Code test env). End-to-end test exercises a pre-release tag and asserts all in-scope channels publish artifacts.
**Target Platform**: macOS (arm64 + amd64) and Linux (arm64 + amd64). Windows explicitly out of scope per spec Assumptions.
**Project Type**: Multi-package Python workspace + release infrastructure. Adds a release-engineering layer; does not modify the audit-pipeline architecture.
**Performance Goals**: From spec — `pip install` completes in <60s; container audit of small reference repo <90s end-to-end (image-pull <20% of budget); brew install <60s; channel propagation within 30 minutes of tag push; partial-failure surfacing within 5 minutes.
**Constraints**: Lockstep versioning across all public packages (single tag drives a single version everywhere). Signing required for every artifact. Container image compressed-size target 300 MB (soft). No long-lived publishing credentials — OIDC keyless / Trusted Publishing only. Pre-release tags must not touch the Homebrew formula or plugin manifest.
**Scale/Scope**: Per release: 4 PyPI packages × (sdist + wheel) = 8 wheels; 1 container image × 2 architectures; 4 standalone binaries (2 OS × 2 arch); 1 brew formula bump; 1 plugin manifest bump. Approximately one release every 2–6 weeks in steady state; pre-releases roughly twice that. ~20 artifacts × 2 attestations each per release.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Rationale |
|-----------|--------|-----------|
| I. Plugin Separation | PASS | Release infrastructure lives in `packaging/`, `.github/workflows/`, and a separate `homebrew-tap` repo. No new imports between `packages/darnit/` and any implementation package. Plugin entry-point mechanism is unchanged; the third-party packaging guide (FR-018) documents what is already there. |
| II. Conservative-by-Default | PASS | Releases are tag-driven and explicit. No auto-detection or heuristic publishing. A failed release is marked incomplete and recovery is per-channel; nothing is published "best guess." Pre-release artifacts carry explicit `-rc` markers so they cannot be mistaken for stable. |
| III. TOML-First | N/A | No control changes. The third-party packaging guide reinforces TOML-first by showing how to declare controls in the plugin's TOML, not in Python. |
| IV. Never Guess User Values | PASS | Versioning is derived from the explicit git tag — never inferred. The "public package set" is enumerated in `packaging/release.yml` (or equivalent config), not auto-detected. Signing identity is the GitHub OIDC identity of the release workflow — no implicit local credentials. |
| V. Sieve Pipeline Integrity | N/A | Audit pipeline untouched. |
| Architecture Constraints (three layers) | PASS | Packaging sits orthogonal to all three audit layers (checking, remediation, MCP tools). The container image bundles `git` and `gh` because Layer-1 sieve handlers shell out to them — this is a packaging concern, not a layer change. |
| Development Workflow gates (lint, tests, spec sync, doc gen, upstream rebase) | PASS | The release workflow itself runs these gates as preconditions on the tagged commit before any channel publishes. Failing any gate aborts the release for that tag. |

No violations. Complexity Tracking table omitted.

## Project Structure

### Documentation (this feature)

```text
specs/012-packaging-distribution/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── release-workflow-contract.md      # Tag → fan-out behavior; secrets; gates
│   ├── pypi-publish-contract.md          # Package set, signing, TestPyPI vs PyPI
│   ├── container-image-contract.md       # Tags, arches, signing, SBOM, entrypoint
│   ├── binary-artifact-contract.md       # Naming, platform matrix, attestation
│   ├── homebrew-formula-contract.md      # Formula shape, auto-bump trigger, tap repo
│   └── claude-plugin-contract.md         # Manifest shape, MCP server invocation, skill bundling
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
.github/workflows/
├── release.yml                              # NEW: tag-triggered release orchestrator (fan-out to channels)
├── release-smoke.yml                        # NEW: per-channel post-publish smoke tests
└── homebrew-bump.yml                        # NEW: cross-repo dispatch → kusari-oss/homebrew-tap (stable tags only)

packaging/                                   # NEW top-level directory
├── README.md                                # Maintainer-facing release runbook
├── pypi/
│   └── public-packages.txt                  # Enumerated list of packages published publicly (single source of truth)
├── container/
│   ├── Dockerfile                           # Multi-stage build over python:3.12-slim
│   ├── entrypoint.sh                        # Default audit entry; falls through to other subcommands
│   └── README.md                            # Image documentation auto-pushed to GHCR
├── binary/
│   ├── shiv.toml                            # shiv config for the standalone binary
│   └── platform-matrix.yml                  # Build matrix (macOS-13/14, ubuntu-22.04, arm64/amd64)
├── homebrew/
│   ├── darnit.rb.tmpl                       # Formula template; rendered by release workflow
│   └── tap-readme.md                        # README pushed to the tap repo
└── claude-plugin/
    ├── manifest.json                        # Claude Code plugin manifest (skill bundling + MCP server config)
    ├── skills/                              # Symlink or copy of repo-root skills/ for plugin packaging
    └── README.md                            # Plugin install docs

docs/install/                                # NEW: user-facing install documentation tree
├── README.md                                # Decision tree mapping situation → channel
├── pypi.md                                  # pip / pipx install path
├── container.md                             # docker / podman invocation
├── homebrew.md                              # brew install + tap setup
├── binary.md                                # Direct GH release binary download + verification
└── claude-code-plugin.md                    # Claude Code plugin install

docs/packaging-plugins.md                    # NEW: third-party implementation packaging guide (FR-018)
packages/darnit-hello/                       # NEW: tiny worked example for the packaging guide (FR-019)
├── pyproject.toml
├── README.md
└── src/darnit_hello/
    ├── __init__.py
    ├── implementation.py                    # Minimal ComplianceImplementation
    └── hello.toml                           # One control demonstrating TOML-first

# Existing files modified:
pyproject.toml                               # Add packaging metadata (URLs reconciliation), classifier updates if needed
packages/*/pyproject.toml                    # Verify wheel metadata (name, version pin, README inclusion); no API changes
README.md                                    # Replace "clone + uv" prose with link to docs/install/
```

A **separate repository** `kusari-oss/homebrew-tap` is created outside this tree to host the rendered Homebrew formula. The release workflow dispatches a `repository_dispatch` event to that repo with the new release's SHA-256 and version; a workflow in the tap repo renders the formula and opens a PR (auto-mergeable).

**Structure Decision**: Packaging configuration lives in a new top-level `packaging/` directory, parallel to `packages/`. This keeps release engineering visibly separate from the Python source tree and lets the directory be excluded from `pytest` collection and `ruff` formatting paths if needed. The GitHub Actions workflows live in `.github/workflows/` as standard. The `kusari-oss/homebrew-tap` repo is governed by this plan but lives outside the tree.

## Implementation Phases

The five user stories from the spec map onto five implementation phases that can ship sequentially. Each phase is **independently shippable** — at the end of each phase the codebase is in a coherent state and the channel exercised in that phase is live.

### Phase A — Foundation: PyPI + release workflow skeleton (User Story 1, P1)

The foundation everything else depends on. After Phase A, `pip install darnit-mcp` works.

1. Add `packaging/pypi/public-packages.txt` enumerating `darnit`, `darnit-baseline`, `darnit-gittuf`, `darnit-mcp` (the four public packages per Assumptions).
2. Verify each public `pyproject.toml` has correct metadata (name, license, classifiers, README inclusion, dependency pins). Reconcile the `kusaridev/darnit-mcp` URLs with the canonical `kusari-oss/darnit` repo.
3. Configure PyPI Trusted Publishing for the project; configure TestPyPI Trusted Publishing for pre-releases.
4. Author `.github/workflows/release.yml` with a tag trigger (`v*.*.*` and `v*.*.*rc*` patterns). Initial implementation:
   - Run pre-release gates: lint, tests, spec sync, doc generation diff check (all from constitution §Development Workflow).
   - Build sdist + wheel for each package in `public-packages.txt`.
   - For stable tags: publish to PyPI via `pypa/gh-action-pypi-publish` with Sigstore signing enabled.
   - For pre-release tags (`rc`/`rcN` suffix): publish to TestPyPI.
   - Create a draft GitHub release attached to the tag.
5. Add `.github/workflows/release-smoke.yml`: after a publish, install the published version in a clean container and run `darnit --version`. Fail the workflow on mismatch.
6. Document the path in `docs/install/pypi.md`.

**Deliverables**: A real `v0.1.0rc1` published to TestPyPI; a real `v0.1.0` published to PyPI; Sigstore signatures verifiable; smoke tests green.

### Phase B — Container image (User Story 2, P2)

Adds the container image, gated on Phase A's foundation (the image installs from PyPI).

1. Write `packaging/container/Dockerfile`: multi-stage build, `python:3.12-slim` base, install `git` and `gh` via apt, install darnit from PyPI by exact version (passed as build-arg from the release workflow), run as a non-root user, set entrypoint to a shell script that dispatches `audit`/`remediate`/etc.
2. Add a Docker build job to `release.yml`:
   - Use `docker/setup-buildx-action` + `docker/build-push-action`.
   - Build for `linux/amd64` and `linux/arm64`.
   - Tag as `ghcr.io/kusari-oss/darnit:vX.Y.Z` and `ghcr.io/kusari-oss/darnit:latest` for stable tags.
   - Tag as `ghcr.io/kusari-oss/darnit:vX.Y.Zrc1` for pre-releases (no `:latest` for `rc`).
   - Sign each digest with cosign (keyless).
   - Generate SBOM via `syft` and attach as a cosign attestation.
3. Add an `:edge` build on every push to `main` (separate job, no signing).
4. Smoke test: `docker run --rm ghcr.io/kusari-oss/darnit:<tag> --version` in `release-smoke.yml`.
5. Measure compressed size in the workflow; surface it in the release summary; fail the soft-target check (warn-only) if size grows >15% release-over-release.
6. Document at `docs/install/container.md`.

**Deliverables**: Multi-arch images on GHCR for `v0.1.0rc1` and `v0.1.0`; signed; SBOMs verifiable.

### Phase C — Standalone binary + Homebrew (User Story 3, P3)

Adds the binary distribution and the Homebrew tap that consumes it. Sequenced together because the formula is a thin wrapper over the binary.

1. Choose binary builder: **`shiv`** (decision in research.md). Author `packaging/binary/shiv.toml`.
2. Add a binary build matrix to `release.yml`:
   - Runners: `macos-14` (arm64), `ubuntu-22.04` (amd64), `ubuntu-22.04-arm` (arm64). macOS amd64 (Intel) is out of scope per the spec — see `Out of Scope`.
   - Build artifact name: `darnit-<version>-<os>-<arch>` (one file per combo).
   - Sign each binary with cosign (keyless, blob signature attached as `darnit-<...>.sig` + `darnit-<...>.pem`).
   - Attach to the GitHub release as draft assets.
3. For stable tags only: dispatch a `repository_dispatch` to `kusari-oss/homebrew-tap` with the version + per-arch SHA-256s.
4. Create the `kusari-oss/homebrew-tap` repository with a workflow (`.github/workflows/bump-formula.yml` in that repo) that:
   - Receives the dispatch payload.
   - Renders `Formula/darnit.rb` from `packaging/homebrew/darnit.rb.tmpl` (cross-repo'd into the tap as a vendored copy on each release) substituting URL/SHA per platform.
   - Opens an auto-mergeable PR; auto-merges on green CI.
5. Smoke test: `brew install kusari-oss/tap/darnit && darnit --version` in `release-smoke.yml` on macOS and Linux runners.
6. Document at `docs/install/binary.md` and `docs/install/homebrew.md`.

**Deliverables**: Four signed binaries per release; `brew install kusari-oss/tap/darnit` works on a fresh Mac and a fresh Linux brew install.

### Phase D — Claude Code plugin (User Story 4, P4)

Adds the agent plugin. Depends on Phase A (the plugin invokes `uvx darnit-mcp`).

1. Author `packaging/claude-plugin/manifest.json` declaring:
   - Plugin name, version (tracks darnit version), description.
   - MCP server config: command tries `uvx --from darnit-mcp@<version> darnit-mcp`; on failure, retries with `pipx run darnit-mcp==<version>`; on second failure, emits the FR-017 actionable error.
   - Skill bundling: copy `darnit-audit`, `darnit-comply`, `darnit-data`, `darnit-remediate` from `packages/darnit/src/darnit/skills/` verbatim into the plugin's `skills/` directory. No rename — the [Agent Skills standard](https://agentskills.io/specification) requires the parent directory name and frontmatter `name:` field to match, and the `darnit-` prefix keeps the skills namespace-safe outside the plugin wrapper. Plugin-namespaced invocation form: `/darnit:darnit-audit` etc. The Claude Code docs state both user-typed (`/skill-name`) and model-autoload paths are first-class — neither is "primary".
2. Add a plugin packaging job to `release.yml` for **stable tags only**:
   - Substitute the `<version>` placeholder in the manifest.
   - Bundle the manifest + skills into a `darnit-claude-plugin-<version>.zip` attached to the GitHub release.
   - Update a `:stable` pointer in `packaging/claude-plugin/` for marketplace consumption (mechanism TBD in research.md per Claude Code marketplace conventions).
3. Smoke test: on a hermetic Claude Code install, install the plugin from the published artifact and assert all four skills are listed and the MCP server responds to a `tools/list` request.
4. Document at `docs/install/claude-code-plugin.md`.

**Deliverables**: A versioned, installable Claude Code plugin attached to each stable GitHub release; smoke test green.

### Phase E — Third-party plugin packaging guide + worked example (User Story 5, P5)

Documentation and example work — no new release infrastructure.

1. Write `docs/packaging-plugins.md` covering: `pyproject.toml` minimum, entry-point declaration, TOML control layout, `register()` and `ComplianceImplementation` protocol contract, `register_handlers()`, testing patterns using `darnit-testchecks`, Sigstore signing of plugin wheels, `[plugins]` trust configuration in `.baseline.toml`, distribution paths.
2. Create `packages/darnit-hello/` — a minimal worked example with one control. Independently installable (e.g., from the repo or a published TestPyPI wheel).
3. Cross-link from `README.md`, `openspec/specs/framework-design/spec.md`, and `docs/install/README.md`.
4. Add a CI job that installs `darnit-hello` into the test env, runs an audit, and asserts the control is discovered and reports a result.

**Deliverables**: A new doc, a new package, and a CI check that the example stays working release-over-release.

### Cross-phase work

- **Decision-tree install doc** (`docs/install/README.md`) is written incrementally, one channel at a time, as each phase lands.
- **Release runbook** (`packaging/README.md`) is written in Phase A and amended in each subsequent phase.
- **Partial-failure observability** (SC-008): each per-channel job in `release.yml` posts to a single GitHub Actions job summary; failures also create a GitHub issue tagged `release-failure` (see research.md for choice rationale). Slack/email integration is explicitly out of scope for v1.

## Post-Design Constitution Re-Check

After Phase 1 artifacts (`research.md`, `data-model.md`, `contracts/*`, `quickstart.md`), re-evaluated against the constitution:

| Principle | Status | Notes from Phase 1 |
|-----------|--------|--------------------|
| I. Plugin Separation | PASS | Confirmed: `packaging/` is a new top-level dir parallel to `packages/`. No code in `packages/darnit/` is modified. The third-party packaging contract (`docs/packaging-plugins.md`) and worked example (`packages/darnit-hello/`) exercise the existing entry-point mechanism — no new framework code. |
| II. Conservative-by-Default | PASS | Release workflow contract makes every gate explicit (preflight rejects on missing GH Release, version mismatch, failing lint/tests/sync/doc-gen). `partial_failure` state surfaces a `release-failure` issue rather than silently retrying or downgrading. Pre-release artifacts carry explicit `-rc` markers. |
| III. TOML-First | N/A → PASS-by-reference | No control changes; the hello-world plugin enforces TOML-first as a teaching example. |
| IV. Never Guess User Values | PASS | Versioning is fully tag-derived, validated against `pyproject.toml`. Public package set is enumerated in `packaging/pypi/public-packages.txt` and CI-enforced. Signing identity is OIDC-derived, not configured. No heuristic is used anywhere in the release pipeline. |
| V. Sieve Pipeline Integrity | N/A | No audit pipeline changes. |
| Architecture Constraints | PASS | Packaging is orthogonal to all three audit layers. The container image's bundled `git`/`gh` is a packaging concern (Layer 1 controls invoke those tools) — does not change layer boundaries. |
| Development Workflow gates | PASS | All five workflow gates (lint, tests, spec sync, doc gen, upstream rebase) are checked in the release workflow's `preflight` job per the release-workflow contract; a failing gate aborts the release before any channel publishes. |

**Result**: No new violations introduced by the Phase 1 design. Plan is ready for `/speckit.tasks`.

## Complexity Tracking

> No Constitution violations. Table omitted.
