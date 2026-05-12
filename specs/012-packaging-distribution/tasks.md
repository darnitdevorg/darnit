---
description: "Task list for 012-packaging-distribution"
---

# Tasks: Packaging & Distribution Channels

**Input**: Design documents from `/specs/012-packaging-distribution/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: This feature does not include a TDD test-first workflow because the deliverables are external release artifacts. Per-channel **smoke tests** (which exercise the published artifact end-to-end) are part of implementation and live in `.github/workflows/release-smoke.yml`. They are listed as implementation tasks, not as separate test-first tasks.

**Organization**: Tasks grouped by user story. Each user story maps to one implementation phase in `plan.md` and is independently shippable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story label (US1–US5) for traceability
- Each task names exact file paths

## Path Conventions

- `packaging/` — new top-level directory (release infrastructure)
- `.github/workflows/` — GitHub Actions workflows
- `docs/install/` — user-facing install documentation
- `packages/darnit-hello/` — worked example for the third-party plugin guide
- `kusari-oss/homebrew-tap` — separate repository (created in Phase 5)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project directories, runbook skeleton, external publisher configuration.

- [X] T001 Create new top-level directory tree: `packaging/{pypi,container,binary,homebrew,claude-plugin}/` and `docs/install/` with empty `.gitkeep` files (so git tracks the empty dirs)
- [X] T002 [P] Author `packaging/README.md` skeleton — maintainer-facing release runbook with stub sections per channel; will be amended per phase
- [X] T003 [P] Reconcile `pyproject.toml` URLs: in `/Users/mlieberman/Projects/baseline-mcp/pyproject.toml` change `Homepage`/`Repository`/`Issues` from `kusaridev/darnit-mcp` to `kusari-oss/darnit`; document the canonical repo home in `packaging/README.md`
- [ ] T004 **External — PyPI**: Configure Trusted Publisher on `pypi.org` for project `darnit-mcp` (and each public package) — repo `kusari-oss/darnit`, workflow `release.yml`, environment `release`. Record the configuration steps in `packaging/README.md`
- [ ] T005 **External — TestPyPI**: Configure Trusted Publisher on `test.pypi.org` mirroring T004 for pre-release flow

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The single-tag-drives-everything release pipeline scaffolding. No channel work can begin until this is in place.

**⚠️ CRITICAL**: No user story (US1–US5) tasks may start until Phase 2 is complete.

- [X] T006 Create `packaging/pypi/public-packages.txt` enumerating the four public packages (`darnit`, `darnit-baseline`, `darnit-gittuf`, `darnit-mcp`) one per line; treat any package not listed as internal-only
- [X] T007 For each public package, audit `packages/<pkg>/pyproject.toml` for required release metadata (name, version, license="Apache-2.0", description, classifiers, README inclusion, dependency pins) and fix gaps; ensure the `version` fields are uniform across all four packages
- [X] T008 Create `.github/workflows/release.yml` with the `on.push.tags` filter from `contracts/release-workflow-contract.md`, the documented `permissions:` block, and a single `preflight` job that runs the version-consistency check, the existing `ruff` + `pytest` + `validate_sync.py` + `generate_docs.py` gates, and aborts on any failure. No channel jobs yet.
- [X] T008a Extend `preflight` to enforce FR-002 ("no out-of-band inputs"): assert there are no uncommitted changes against the tagged commit (`git diff --exit-code` and `git diff --cached --exit-code`), and run `actionlint` over `.github/workflows/release.yml` to verify no secrets are referenced outside the documented `permissions:` block.
- [X] T009 [P] Create `.github/workflows/release-smoke.yml` skeleton with no jobs — placeholder for per-channel smoke jobs added in subsequent phases
- [X] T010 [P] Add a `release-yml-lint` CI job (in an existing PR-validation workflow, or a new tiny workflow) that runs `actionlint` against `.github/workflows/release.yml` and `.github/workflows/release-smoke.yml` on every PR
- [X] T011 [P] Add `packaging/RECOVERY.md` skeleton with one empty section per channel (`pypi`, `container`, `binary`, `homebrew`, `claude_plugin`); each phase fills its own section
- [ ] T012 Tag the repository with a no-op release candidate `v0.0.0rc0` to dry-run the preflight job; confirm the workflow runs, gates pass on a clean tree, and no channel job executes (because none exist yet). Delete the tag after.

**Checkpoint**: Foundation ready — channel work can begin per user story.

---

## Phase 3: User Story 1 — Python user installs from a package index (P1) 🎯 MVP

**Goal**: `pip install darnit-mcp==<version>` and `pipx install darnit-mcp==<version>` succeed against PyPI; pre-releases work against TestPyPI. Sigstore signatures attached.

**Independent Test**: Tag `v0.0.0rc1` from a clean branch → workflow publishes 4 sdist+wheel pairs to TestPyPI → on a clean container, `pip install --index-url https://test.pypi.org/simple/ --pre darnit-mcp==0.0.0rc1` succeeds → `darnit --version` returns `0.0.0rc1` → `python -m sigstore verify identity --bundle ... darnit_mcp-0.0.0rc1-...whl` verifies.

### Implementation for User Story 1

- [X] T013 [US1] Add a `pypi_publish` job to `.github/workflows/release.yml` that runs after `preflight`. For each package in `packaging/pypi/public-packages.txt`: `uv build --package <pkg> --out-dir dist/<pkg>/`. Assert that the package name appears in `public-packages.txt` before any upload (refuse to publish unlisted packages).
- [X] T014 [US1] In the `pypi_publish` job, use `pypa/gh-action-pypi-publish@release/v1` with `attestations: true`. Target `https://upload.pypi.org/legacy/` for stable tags and `https://test.pypi.org/legacy/` for pre-release tags (detected via the `rc` suffix in `github.ref_name`).
- [X] T015 [US1] Add a `pypi_smoke` job to `.github/workflows/release-smoke.yml` that triggers after the release workflow's `pypi_publish` completes. In a clean Python container, `pip install --index-url <selected> --pre <pkg>==<version>` for each public package and run a per-package smoke (for `darnit-mcp`: `darnit --version` matches `<version>`; for others: import smoke).
- [X] T016 [US1] Extend `pypi_smoke` to verify the Sigstore bundle for `darnit_mcp` via `python -m sigstore verify identity --cert-identity-regexp '^https://github\\.com/kusari-oss/darnit/' --cert-oidc-issuer https://token.actions.githubusercontent.com`. Fail the smoke if the signature does not verify.
- [X] T017 [P] [US1] Write `docs/install/pypi.md` per the PyPI section of `quickstart.md`, including the Sigstore verification command
- [X] T018 [P] [US1] Populate the `pypi` section of `packaging/RECOVERY.md` with the manual yank-and-retry recipe when an upload fails mid-flight
- [ ] T019 [US1] Run the end-to-end test from the Independent Test above against a real `v0.0.0rc1` tag; confirm all assertions hold

**Checkpoint US1**: PyPI/pipx install path is live; pre-release flow validated against TestPyPI.

---

## Phase 4: User Story 2 — CI/CD pipeline runs darnit from a container image (P2)

**Goal**: `ghcr.io/kusari-oss/darnit:<tag>` is published per release for `linux/amd64` and `linux/arm64`, cosign-signed, with an SBOM attestation, and small enough to pull quickly.

**Independent Test**: After a `v0.0.0rc2` tag publishes successfully → on a clean machine with only Docker, `docker pull ghcr.io/kusari-oss/darnit:v0.0.0rc2 && docker run --rm ghcr.io/kusari-oss/darnit:v0.0.0rc2 --version` returns `0.0.0rc2` → `cosign verify ghcr.io/kusari-oss/darnit:v0.0.0rc2 --certificate-identity-regexp ... --certificate-oidc-issuer ...` verifies.

### Implementation for User Story 2

- [X] T020 [US2] Author `packaging/container/Dockerfile` with the multi-stage build per `contracts/container-image-contract.md`: builder stage installs `darnit-mcp==<version>` (version passed as `ARG VERSION`) into a venv; runtime stage based on `python:3.12-slim`, installs `git` + `gh` via apt with caches purged, copies the venv, creates non-root user `darnit` (uid 10001), sets `WORKDIR /repo`, sets `ENTRYPOINT`/`CMD`
- [X] T021 [US2] Write `packaging/container/entrypoint.sh` per the contract — dispatch on first positional arg (`audit`/`remediate`/`list-controls`/`--version`/`--help` → `darnit`; `mcp` → `darnit-mcp`; anything else → exec direct)
- [X] T022 [US2] [P] Write `packaging/container/README.md` describing the image's contents, supported architectures, and entry-point usage (this README is mirrored to the GHCR overview page)
- [X] T023 [US2] Add a `container_build_push` job to `.github/workflows/release.yml`, gated on `pypi_publish` success. Use `docker/setup-qemu-action` + `docker/setup-buildx-action` + `docker/build-push-action` with `platforms: linux/amd64,linux/arm64`. Tag policy from the contract (stable: `:vX.Y.Z` + `:latest`; pre-release: `:vX.Y.Zrc<N>` only). Pass `--build-arg VERSION=<version>`.
- [X] T024 [US2] In the same job, after push, run `cosign sign --yes ghcr.io/kusari-oss/darnit@${DIGEST}` using OIDC keyless signing
- [X] T025 [US2] After signing, run `syft ghcr.io/kusari-oss/darnit@${DIGEST} -o spdx-json > sbom.spdx.json` and attach via `cosign attest --yes --predicate sbom.spdx.json --type spdx ghcr.io/kusari-oss/darnit@${DIGEST}`
- [X] T026 [US2] Add compressed-size reporting: capture `docker manifest inspect` JSON, sum compressed sizes per arch, post to job summary; emit a `::warning::` (not failure) if growth >15% vs the previous release (look up previous size via `gh release view`)
- [X] T027 [US2] Create a separate `.github/workflows/container-edge.yml` triggered on `push` to `main` that builds and pushes `:edge` (no signing, no SBOM); record this is non-release in the README
- [X] T028 [US2] Add a `container_smoke` job to `release-smoke.yml`: pull the published tag, run `darnit --version`, then run the `cosign verify` command from the contract
- [X] T029 [P] [US2] Write `docs/install/container.md` per the quickstart's container section, including the SBOM download command
- [X] T030 [P] [US2] Populate the `container` section of `packaging/RECOVERY.md` with the digest-pinning + re-push recipe for partial failures
- [ ] T031 [US2] Run the end-to-end test from the Independent Test above against a real `v0.0.0rc2` tag

**Checkpoint US2**: Container image is live on GHCR, signed, multi-arch.

---

## Phase 5: User Story 3 — Engineer installs via the platform's native package manager (P3)

**Goal**: Four signed standalone binaries (macOS arm64/amd64, Linux arm64/amd64) attached to each GitHub Release; `brew install kusari-oss/tap/darnit` works on macOS and Linux.

**Independent Test**: After a `v0.0.0rc3` tag → binaries appear on the GH Release; `cosign verify-blob` succeeds for each; the Homebrew tap PR auto-merges within 30 min for the stable follow-up tag; `brew tap kusari-oss/tap && brew install darnit && darnit --version` succeeds on macOS arm64 and Linux amd64.

### Implementation for User Story 3 — binary side

- [X] T032 [US3] Author `packaging/binary/shiv.toml` with `console-script = "darnit"`, `python = "/usr/bin/env python3.11"`, `compressed = true`. Test locally first to confirm the resulting zipapp runs.  _(Delivered as `packaging/binary/build-binary.sh` — shiv has no native TOML config format; script captures the canonical invocation.)_
- [X] T033 [US3] Add a `binary_matrix` job to `.github/workflows/release.yml` with strategy matrix `os ∈ {macos-14, macos-13, ubuntu-22.04, ubuntu-22.04-arm}` mapping to four `(os, arch)` artifact filenames. Run `shiv` per matrix entry; output `darnit-<version>-<os>-<arch>` in `dist/binary/`.
- [X] T034 [US3] In `binary_matrix`, sign each output: `cosign sign-blob --yes --bundle darnit-<version>-<os>-<arch>.sigstore darnit-<version>-<os>-<arch>`
- [X] T035 [US3] In `binary_matrix`, generate SBOM via `syft <binary> -o spdx-json > <binary>.sbom.spdx.json` and attest via `gh attestation create --predicate-type https://spdx.dev/Document --predicate <sbom> <binary>`
- [X] T036 [US3] After all four matrix entries complete, run `gh release create v<version> --title "v<version>"` (use `--prerelease` for `rc` tags, `--latest` for stable) with all eight files attached: `darnit-<version>-<os>-<arch>` + `.sigstore` for each `(os, arch)`
- [X] T037 [US3] Add a `binary_smoke` job to `release-smoke.yml` with the same matrix; each runner downloads its matching binary, runs `--version`, and runs `cosign verify-blob` per the contract
- [X] T038 [P] [US3] Write `docs/install/binary.md` per the quickstart's binary section, including the Python 3.11+ prerequisite and the `cosign verify-blob` command
- [X] T039 [P] [US3] Populate the `binary` section of `packaging/RECOVERY.md`

### Implementation for User Story 3 — Homebrew side

- [ ] T040 **External** [US3]: Create the `kusari-oss/homebrew-tap` repository with a public README, default branch `main`, no other content yet
- [ ] T041 **External** [US3]: Create a GitHub App (or use an existing org App) with `contents: write` on `kusari-oss/homebrew-tap`; configure the resulting token as the secret `HOMEBREW_TAP_TOKEN` in `kusari-oss/darnit`; document the steps in `packaging/README.md`
- [X] T042 [US3] Write `packaging/homebrew/darnit.rb.tmpl` per the formula template in `contracts/homebrew-formula-contract.md` (Jinja-style placeholders: `{{ version }}`, `{{ sha256_<os>_<arch> }}`, `{{ binary_url_template }}`)
- [X] T043 [US3] Add a `homebrew_dispatch` job to `release.yml` (stable tags only — gate on absence of `rc` in `github.ref_name`). The job depends on `binary_matrix` success, computes SHA-256 of each of the four binaries, and dispatches a `repository_dispatch` event to `kusari-oss/homebrew-tap` with the payload schema from the contract.
- [X] T044 [US3] In `kusari-oss/homebrew-tap`, author `.github/workflows/bump-formula.yml` triggered on `repository_dispatch` with type `darnit-release`. The workflow validates the payload, renders `Formula/darnit.rb` from the vendored `darnit.rb.tmpl` (copied into the tap on dispatch), runs `brew style` + `brew install --build-from-source`, opens a PR titled `darnit <version>`, and `gh pr merge --auto --squash`s it.  _(Reference copy delivered in `packaging/homebrew/tap-workflows/bump-formula.yml`; maintainer copies into the tap repo on T040.)_
- [X] T045 [US3] In `kusari-oss/homebrew-tap`, author a tiny `.github/workflows/ci.yml` that runs `brew style Formula/*.rb` and `brew install --build-from-source Formula/darnit.rb` on every PR (this is what gates the auto-merge in T044)  _(Reference copy delivered in `packaging/homebrew/tap-workflows/ci.yml`.)_
- [X] T046 [US3] Add a `homebrew_smoke` job to `release-smoke.yml` (stable tags only) that polls `gh pr list --repo kusari-oss/homebrew-tap` for the bump PR, waits up to 30 min for merge, then on macOS-14 and ubuntu-22.04 runners runs `brew tap kusari-oss/tap && brew install darnit && darnit --version | grep "<version>"`
- [X] T047 [P] [US3] Write `docs/install/homebrew.md` per the quickstart's Homebrew section
- [X] T048 [P] [US3] Populate the `homebrew` section of `packaging/RECOVERY.md` (manual formula revert recipe)
- [ ] T049 [US3] Run the end-to-end test: tag `v0.0.0rc3`, confirm binaries publish; then tag `v0.0.0` (the first real stable) and confirm Homebrew formula auto-merges + smoke passes within 30 min

**Checkpoint US3**: Standalone binaries + Homebrew tap are live for end users.

---

## Phase 6: User Story 4 — Coding-agent user installs darnit as a plugin (P4)

**Goal**: `darnit-claude-plugin-<version>.zip` is attached to each stable GH Release; structural smoke passes; behavioral smoke passes if Claude Code plugin tooling is available.

**Independent Test**: After a stable tag → the zip artifact exists on the release; unzipping it reveals manifest + skills/ as specified; `jq -e '.version == "<version>"'` passes; the MCP-invocation shell snippet runs `darnit --version` correctly when `uvx` is installed in a clean container.

### Implementation for User Story 4

- [ ] T050 [US4] Write `packaging/claude-plugin/manifest.json` per the schema in `contracts/claude-plugin-contract.md`, with `<version>` as a placeholder. Pin the manifest schema version (`mcpServers`, `skills`) and document the pinned version inline.
- [ ] T051 [US4] Write a small `packaging/claude-plugin/build.sh` (or inline in the workflow) that copies `skills/` from the repo root into `packaging/claude-plugin/skills/`, substitutes `<version>` in `manifest.json`, and produces `darnit-claude-plugin-<version>.zip`
- [ ] T052 [US4] Write `packaging/claude-plugin/README.md` documenting install steps, the `uvx`/`pipx` prerequisite, and the schema-version pin
- [ ] T053 [US4] Add a `plugin_package` job to `.github/workflows/release.yml` (stable tags only). The job depends on `pypi_publish`, runs `build.sh`, asserts skill count == 4 and skill paths match `skills/` contents, then uploads the zip to the GitHub Release via `gh release upload`
- [ ] T054 [US4] Add a `plugin_structural_smoke` job to `release-smoke.yml`: download the zip, run the structural assertions from the contract (`unzip -t`, `jq` on manifest, skill-path diff)
- [ ] T055 [US4] Add a `plugin_behavioral_smoke` job to `release-smoke.yml` that runs the FR-017 fallback chain shell snippet directly in a container with `uvx` available, asserting `uvx --from darnit-mcp@<version> darnit-mcp --help` succeeds. If Anthropic publishes a Claude Code plugin test harness in time for v1, extend this job to install the plugin and assert all four skills are exposed.
- [ ] T056 [P] [US4] Write `docs/install/claude-code-plugin.md` per the quickstart's plugin section
- [ ] T057 [P] [US4] Populate the `claude_plugin` section of `packaging/RECOVERY.md`
- [ ] T058 [US4] Tag a stable release and confirm the plugin smoke passes end-to-end

**Checkpoint US4**: Claude Code plugin artifact ships with every stable release.

---

## Phase 7: User Story 5 — Third-party team ships their own implementation plugin (P5)

**Goal**: An external developer can read `docs/packaging-plugins.md`, copy the `darnit-hello` example, and publish a working darnit implementation that darnit auto-discovers.

**Independent Test**: A test team unfamiliar with darnit's source follows `docs/packaging-plugins.md`, ends up with a new package `<their-pkg>` that registers via the `darnit.implementations` entry point; after `pip install <their-pkg>`, darnit's `list_controls` MCP tool shows their controls and an audit runs.

### Implementation for User Story 5

- [ ] T059 [US5] Write `docs/packaging-plugins.md` covering: minimum `pyproject.toml`, entry-point declaration (`darnit.implementations`), `register()` callable contract, `ComplianceImplementation` protocol surface (cross-link to `CLAUDE.md` and `openspec/specs/framework-design/spec.md`), TOML control layout, `register_handlers()`, testing with `darnit-testchecks` patterns, Sigstore signing of plugin wheels, `[plugins].trusted_publishers` config in `.baseline.toml`, distribution paths (PyPI / private indexes / git)
- [ ] T060 [P] [US5] Create `packages/darnit-hello/pyproject.toml` declaring the package, entry point `darnit-hello = "darnit_hello:register"`, dependency on `darnit`, Python `>=3.11`
- [ ] T061 [P] [US5] Create `packages/darnit-hello/src/darnit_hello/__init__.py` with the `register()` function returning an instance of `DarnitHelloImplementation`
- [ ] T062 [US5] Create `packages/darnit-hello/src/darnit_hello/implementation.py` with a minimal `DarnitHelloImplementation` exposing one control via `get_framework_config_path()` pointing at `hello.toml`
- [ ] T063 [US5] Create `packages/darnit-hello/src/darnit_hello/hello.toml` with one control (e.g., "README.md exists") using the `file_must_exist` handler — single source of truth, TOML-first
- [ ] T064 [P] [US5] Create `packages/darnit-hello/README.md` mirroring the structure new third parties would write
- [ ] T065 [US5] Add an `integration_plugin_discovery` CI job to the existing PR-validation workflow that `pip install -e packages/darnit-hello`, then `uv run darnit list-controls` (or equivalent) and asserts the hello control appears in the output. Asserts an end-to-end audit of the control passes.
- [ ] T066 [P] [US5] Cross-link `docs/packaging-plugins.md` from `README.md` and `openspec/specs/framework-design/spec.md`
- [ ] T067 [US5] Run the Independent Test: have a non-author follow the guide top-to-bottom and report whether they can ship a discoverable plugin in <1 engineering day

**Checkpoint US5**: Third-party packaging guide is live with a working example and a CI check that keeps it working.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Stitch the channels together with cross-cutting docs and finalize the partial-failure observability.

- [ ] T068 [P] Write `docs/install/README.md` with the decision-tree table from `quickstart.md` (situation → channel) plus links to each per-channel doc
- [ ] T069 [P] Update root `README.md` install section: replace clone+uv prose with a one-paragraph summary and a link to `docs/install/README.md`
- [ ] T070 Finalize `packaging/RECOVERY.md` — confirm each channel section is filled, add a generic "how to file a release-failure issue" section
- [ ] T071 Add a `finalize` job at the end of `.github/workflows/release.yml` with `if: always()`. The job MUST: (a) capture each per-channel job's `completed_at - workflow_started_at` elapsed time; (b) aggregate per-channel pass/fail + elapsed into a job-summary markdown table; (c) compute `homebrew_dispatch_to_merge_seconds` from the tap-repo PR (when applicable); (d) flag any channel exceeding 30 minutes from tag push (SC-007 budget); (e) on any failure OR over-budget channel for a stable tag, create a GitHub issue tagged `release-failure` containing channel name, tag, workflow-run URL, measured elapsed times, the SC-007 budget, and a quoted recovery snippet from `packaging/RECOVERY.md`; (f) embed the timing table in the auto-generated GitHub Release notes.
- [ ] T071a Add `timeout-minutes: 30` to the `.github/workflows/release.yml` workflow at the workflow level for stable tags only (pre-release tags are not bound by SC-007). If any per-channel job exceeds this budget, the workflow is cancelled and `finalize` (T071) records the timeout as a `release-failure`.
- [ ] T072 [P] Finalize `packaging/README.md` runbook with the full end-to-end release ceremony (verify branch state → bump versions → push tag → monitor → triage failures)
- [ ] T073 End-to-end quickstart validation: run every command in `quickstart.md` against the most recent stable release on a fresh macOS arm64 host and a fresh Linux amd64 host; record outcomes in `packaging/README.md`
- [ ] T074 Confirm that none of the changes regressed existing tests: `uv run ruff check . && uv run pytest tests/ --ignore=tests/integration/ -q && uv run python scripts/validate_sync.py --verbose && uv run python scripts/generate_docs.py && git diff --exit-code docs/generated/`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001–T005 — no internal dependencies; T004/T005 are external maintainer actions
- **Foundational (Phase 2)**: depends on Phase 1; T012 (no-op dry-run) is the gate that proves the foundation works
- **User Stories (Phase 3+)**: all depend on Phase 2 completion; some channels have cross-story dependencies:
  - **US2 (container)** depends on **US1 (PyPI)** because the Dockerfile installs from PyPI
  - **US3 (binary + Homebrew)** depends on **US1 (PyPI)** for `darnit-mcp` source and on **Phase 2** for the workflow scaffolding; the Homebrew side depends on the binary side
  - **US4 (Claude plugin)** depends on **US1 (PyPI)** for the runtime invocation
  - **US5 (third-party guide)** depends only on Phase 2; no cross-story coupling
- **Polish (Phase 8)**: depends on all user stories being complete

### User Story Dependencies (visualized)

```
            Phase 1 ─► Phase 2
                          │
                          ▼
                       US1 (P1) — PyPI
                       │   │   │
              ┌────────┘   │   └──────────┐
              ▼            ▼              ▼
         US2 (P2)     US4 (P4)       US3 (P3) binary ──► US3 Homebrew
        Container    Claude plug    Standalone
                                     binary
                       
            US5 (P5) — Third-party guide ──┐
                                            ▼
                                          Phase 8
```

### Within Each User Story

- Local Dockerfile/manifest authoring before workflow jobs
- Build job before signing before SBOM before smoke
- Documentation [P] tasks can run any time within the story (parallel with implementation)
- Recovery-doc [P] tasks can run any time within the story

### Parallel Opportunities

- **All [P] docs tasks** can be written by the same or different contributor in parallel with implementation
- **Within US2**: T022 (README) is [P] with T020–T021 (Dockerfile authoring)
- **Within US3**: binary and Homebrew sides are sequentially coupled (Homebrew depends on binaries); within each side, docs/recovery tasks are [P]
- **Within US4**: T056/T057 docs are [P] with T050–T053 implementation
- **Within US5**: T060, T061, T064, T066 are [P] with each other and with T059 (guide writing)
- **Phase 8**: T068, T069, T072 are [P]
- **Across stories** (once Phase 2 is in): US2, US3-binary, US4, US5 can all proceed in parallel with US1, gated only on US1's PyPI publish for the cross-story dependencies named above

---

## Parallel Example: User Story 2

```bash
# After Phase 2 + US1 are complete:

# Contributor A picks up Dockerfile + entrypoint:
Task: "Write packaging/container/Dockerfile per contract" (T020)
Task: "Write packaging/container/entrypoint.sh per contract" (T021)

# Contributor B simultaneously writes user-facing docs:
Task: "Write packaging/container/README.md" (T022)
Task: "Write docs/install/container.md" (T029)
Task: "Write container section of packaging/RECOVERY.md" (T030)

# Then jointly:
Task: "Wire up container_build_push job in release.yml" (T023)
```

---

## Parallel Example: User Story 5 (mostly parallelizable)

```bash
# After Phase 2 is complete (no other stories needed):

# Four contributors can split:
Contributor A: T059 (docs/packaging-plugins.md)
Contributor B: T060, T061 (darnit-hello scaffolding)
Contributor C: T062, T063 (darnit-hello implementation + TOML)
Contributor D: T064, T066 (README + cross-links)

# Then sequentially:
T065 (CI integration check) — depends on B + C
T067 (third-party usability test) — depends on A + all the above
```

---

## Implementation Strategy

### MVP scope — ship User Story 1 first

The MVP is **Phase 1 → Phase 2 → User Story 1**. After T019, darnit is installable via `pip install darnit-mcp` and `pipx install darnit-mcp` with verifiable Sigstore signatures. That alone is a step change from today's "clone the repo and use uv" reality. Stop here and demo before starting US2.

### Incremental delivery — channel by channel

1. **MVP** (T001–T019): PyPI install path live with pre-release flow.
2. **+ US2** (T020–T031): Container image live for CI users.
3. **+ US3** (T032–T049): Binary + Homebrew live for native-package users.
4. **+ US4** (T050–T058): Claude Code plugin live for agent users.
5. **+ US5** (T059–T067): Third-party plugin guide + worked example live.
6. **+ Polish** (T068–T074): Decision-tree doc, finalized recovery doc, partial-failure issue automation, end-to-end validation.

Each step is shippable on its own. Each step can be tagged as a real release (`v0.1.0`, `v0.2.0`, ...) so users adopt one new channel per release rather than waiting for everything.

### Parallel team strategy

With multiple contributors, after Phase 2 completes:

- **Lead contributor** owns US1 + the cross-cutting workflow infrastructure (Phase 2 is theirs).
- **Once US1 lands**, branch out:
  - Container person picks up US2.
  - Binary/brew person picks up US3 (longest stretch — most coupling).
  - Plugin person picks up US4.
  - Docs person picks up US5 + Phase 8.
- The release-engineering choices in `research.md` are all upfront, so contributors don't get blocked on architectural decisions mid-stream.

---

## Notes

- Tag patterns used in tasks above:
  - `v0.0.0rc0` (T012): no-op dry-run of preflight only
  - `v0.0.0rc1` (T019): US1 validation
  - `v0.0.0rc2` (T031): US2 validation
  - `v0.0.0rc3` (T049): US3 binary side validation
  - `v0.0.0` (T049): first real stable for the Homebrew side smoke
  - Real `v0.1.0`: first user-facing release (after at least US1 + US2 are landed; recommended after US3 too)
- The Homebrew tap repo (`kusari-oss/homebrew-tap`) is created in T040 and is **outside this repository tree**. Tasks T044–T045 land in that repo; everything else is in `kusari-oss/darnit`.
- The third-party packaging guide example (`packages/darnit-hello/`) is **not** published to PyPI from this repo. It is in-tree only as a copy-paste source for external developers.
- Smoke tests live alongside their channels in `release-smoke.yml`; they exercise the **published artifact**, not pre-publish builds. A smoke failure does not unpublish.
- Pre-release tags (`rcN` suffix) skip Homebrew (T043) and Claude plugin (T053) jobs by design; this is a hard rule enforced in the workflow `if:` conditions, not a soft guideline.
- Commit after each task or each logical group. Each [P] doc task is independently committable.
