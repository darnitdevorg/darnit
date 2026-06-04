# Phase 1 Data Model: Packaging & Distribution

The packaging feature does not introduce database records or persisted application state. The entities below describe the **release-engineering data flow** — the conceptual objects the release pipeline reads, produces, and asserts invariants over. They map directly to GitHub Actions inputs/outputs, workflow artifacts, and external channel state.

---

## Entity overview

```text
                       Tag (Git)
                          │
                          ▼
                       Release ──────► Attestation*
                          │              (signature, SBOM)
        ┌─────────┬───────┼──────────┬─────────────┐
        ▼         ▼       ▼          ▼             ▼
    PyPIWheel  Image  Binary*   FormulaBump   PluginPackage
       (×4)   (×2)    (×4)         (×1)         (×1)
                          │
                       Channel
                       (per artifact)
```

`×N` indicates fan-out (e.g., 3 binaries per release: macOS arm64 + Linux arm64 + Linux amd64; macOS amd64 is out of scope).

---

## Entities

### Release

The unit of work for the release pipeline. One git tag produces exactly one Release.

| Field | Type | Source | Constraints |
|---|---|---|---|
| `version` | `str` | Git tag (with `v` prefix stripped) | Must match SemVer 2.0.0. Must equal `version` in every public `pyproject.toml` at the tagged commit. |
| `tag` | `str` | Git tag literal | Must match `^v\d+\.\d+\.\d+(rc\d+)?$`. The release workflow rejects any tag outside this pattern. |
| `commit_sha` | `str` | Git | Immutable; the resolved SHA of the tagged commit. |
| `kind` | `enum` | Derived from `tag` | `stable` if no `rc` suffix; `prerelease` if `rcN` suffix present. |
| `triggered_at` | `datetime` | Workflow start | Used in release-notes generation. |
| `triggered_by` | `str` (GitHub identity) | OIDC token claim | Used in the cosign certificate identity. |
| `state` | `enum` | Workflow runtime | One of `pending`, `gates_passed`, `publishing`, `complete`, `partial_failure`. Surfaced to the GitHub Actions UI. |

**Lifecycle**:
```
pending → gates_passed → publishing → complete
                                    └→ partial_failure
```

- `pending`: workflow started, pre-release gates not yet run.
- `gates_passed`: lint, tests, spec sync, doc gen — all green on the tagged commit.
- `publishing`: at least one per-channel job has started.
- `complete`: every in-scope channel for this release's `kind` published successfully.
- `partial_failure`: at least one in-scope channel job failed; a `release-failure` GitHub issue exists.

**Invariants**:
- Once a `Release` reaches `complete` or `partial_failure`, its `version` cannot be reused. Tagging `v0.1.0` a second time is a hard error (the release workflow checks the tag against existing GitHub Releases on entry and aborts on collision). Spec edge case: "releases are not silently retracted or rewritten."
- `prerelease` Releases skip publication to FormulaBump and PluginPackage (per spec FR-008, clarified in session).

---

### Channel

A user-facing distribution surface. Static set, defined at design time. Not all channels publish for every Release `kind`.

| Channel | `kind=stable` | `kind=prerelease` | Notes |
|---|---|---|---|
| `pypi` | publishes to PyPI | publishes to TestPyPI | Different indexes. |
| `container` | publishes `:vX.Y.Z` and `:latest` | publishes `:vX.Y.Zrc1` only | No `:latest` movement on rc. |
| `binary` | attaches to GH Release as final asset | attaches to GH Release marked pre-release | Same artifact name shape. |
| `homebrew` | bumps formula in tap repo | skipped | Per clarification Q2. |
| `claude_plugin` | publishes plugin artifact | skipped | Per clarification Q2. |

Each `Channel` exposes:
- A **publish operation** (workflow job).
- A **smoke-test operation** (subsequent workflow job in `release-smoke.yml`).
- A **rollback documentation entry** in `packaging/RECOVERY.md` keyed by channel name.

---

### Artifact

A single signed, versioned output emitted by exactly one per-channel publish job. Artifacts are the unit of fan-out.

| Field | Type | Constraints |
|---|---|---|
| `release_version` | `str` | FK → `Release.version`. |
| `channel` | `str` | FK → `Channel.name`. |
| `kind` | `enum` | `pypi_wheel`, `pypi_sdist`, `container_image`, `standalone_binary`, `homebrew_formula`, `plugin_zip`. |
| `name` | `str` | Channel-specific (see below). |
| `platform` | `str?` | Present for `standalone_binary` and `container_image` (e.g., `macos-arm64`, `linux/amd64`). |
| `published_uri` | `str` | URL or registry coordinate (e.g., `https://pypi.org/project/darnit/0.1.0/`, `ghcr.io/kusari-oss/darnit@sha256:...`). |
| `digest` | `str` | SHA-256 of the artifact content. |
| `attestation` | `Attestation` | One-to-one, embedded below. |

**Naming conventions** (enforced in CI):
- PyPI wheel: standard PEP 427 (`darnit_mcp-0.1.0-py3-none-any.whl`).
- Container image: `ghcr.io/kusari-oss/darnit:<tag>` plus immutable digest reference.
- Standalone binary: `darnit-<version>-<os>-<arch>` (e.g., `darnit-0.1.0-macos-arm64`).
- Homebrew formula: `Formula/darnit.rb` in `kusari-oss/homebrew-tap` at HEAD.
- Plugin: `darnit-claude-plugin-<version>.zip`.

**Per-release counts** (used to validate "complete" state):
- `pypi_wheel`: 4 (one per public package).
- `pypi_sdist`: 4.
- `container_image`: 1 multi-arch manifest (2 platform manifests beneath).
- `standalone_binary`: 3 (macOS arm64, Linux arm64, Linux amd64). macOS amd64 is out of scope.
- `homebrew_formula`: 1 (stable only).
- `plugin_zip`: 1 (stable only).

A `Release` is `complete` iff every expected `Artifact` for its `kind` is present and signed.

---

### Attestation

Verifiable metadata bound to exactly one `Artifact`.

| Field | Type | Notes |
|---|---|---|
| `artifact_digest` | `str` | SHA-256 of the parent artifact. |
| `signature_bundle` | `bytes` | Sigstore bundle for PyPI wheels; cosign signature + cert for images/binaries. |
| `signing_identity` | `str` | OIDC identity of the GitHub Actions workflow that produced the artifact. Always of the form `https://github.com/kusari-oss/darnit/.github/workflows/release.yml@refs/tags/v<version>`. |
| `sbom` | `bytes?` | SPDX-JSON SBOM. Present for `container_image` and `standalone_binary`; absent for PyPI wheels (Sigstore bundle stands alone) and FormulaBump (not an artifact). |
| `verification_command` | `str` (template) | Documented in `docs/install/`; consumable by users without source access. |

**Validity rules**:
- `signing_identity` must match the GitHub repo + workflow + tag of the parent `Release`. CI verifies this assertion on smoke-test.
- An `Artifact` without a verified `Attestation` cannot transition its `Channel` to `published`.

---

### FormulaBump

A specialization of `Artifact` for the Homebrew channel. Modeled separately because the artifact is a PR in a different repository, not a binary blob.

| Field | Type | Constraints |
|---|---|---|
| `dispatch_payload` | `JSON` | Carries `version` + four `sha256_<platform>` keys; signed implicitly by the workflow's OIDC identity. |
| `tap_repo` | `str` | Always `kusari-oss/homebrew-tap`. |
| `pr_url` | `str` | Populated when the tap repo's workflow opens the bump PR. |
| `merged_at` | `datetime?` | Populated when CI auto-merges; null on partial-failure. |

**Lifecycle**:
```
dispatched → pr_opened → ci_passing → merged
                       └→ ci_failing (manual intervention required)
```

A FormulaBump that does not reach `merged` within 30 minutes (SC-007) is considered failed and surfaces a `release-failure` issue.

---

### PluginPackage

A specialization for the Claude Code plugin channel.

| Field | Type | Constraints |
|---|---|---|
| `manifest_version` | `str` | Matches the spec version of the Claude Code plugin schema in use (pinned per `packaging/claude-plugin/README.md`). |
| `bundled_skills` | `List[str]` | Always `["darnit-audit", "darnit-context", "darnit-comply", "darnit-remediate"]`. CI asserts equality with `skills/` directory contents at the tagged commit. |
| `mcp_server_command` | `str` | Rendered shell snippet implementing FR-017 (uvx → pipx run → actionable error). |
| `target_darnit_version` | `str` | Equals `Release.version`. Pin enforced in manifest. |

---

### PluginRegistration (third-party — out of release-engineering scope)

The User Story 5 / FR-018 plugin registration story has its own data shape, separate from this release pipeline. Modeling it here for completeness:

| Field | Type | Notes |
|---|---|---|
| `package_name` | `str` | The third-party package name on its chosen index. |
| `entry_point_group` | `str` | Always `darnit.implementations`. |
| `register_callable` | `str` | Dotted path to the `register()` function. |
| `signing_identity` | `str?` | Optional; checked against `.baseline.toml` `[plugins].trusted_publishers` at install time. |

This entity is documented in `docs/packaging-plugins.md` and instantiated for real by `packages/darnit-hello/`. It does not flow through `release.yml`.

---

## State transitions in the release workflow

The pipeline's state machine (encoded in `release.yml`):

```
[tag push v*.*.*]
   │
   ├─ Pre-flight: version-consistency check across pyproject.toml + tag
   │   └─► fail → workflow stops; Release.state = pending; no Channel published
   │
   ├─ Gates: lint + tests + spec sync + doc gen
   │   └─► fail → Release.state = pending; no Channel published; issue created
   │
   ▼ gates_passed
   │
   ├─ PyPI publish ──► Smoke ──► attestation verified
   ├─ Container build + push ──► Smoke ──► cosign verify
   ├─ Binary matrix (×4) ──► Smoke ──► cosign verify-blob
   │                                                       │
   ▼ publishing                                            │
   │                                                       │
   ├─ [stable only] FormulaBump dispatch ──► poll merge ──┤
   ├─ [stable only] PluginPackage build + upload ──► Smoke ┤
   │                                                       │
   ▼                                                       │
   complete  ◄────────────────────────────────────────────┘
   ▲
   │
   └── partial_failure (any channel job failed)
        └─► creates GitHub issue, leaves state for human triage
```

---

## Validation rules

These rules are encoded as CI checks (not runtime checks in any Python package):

1. **Version consistency**: `tag` (stripped of `v`) equals `version` in every public `pyproject.toml` at the tagged commit. Enforced in pre-flight.
2. **Public package set**: only packages listed in `packaging/pypi/public-packages.txt` are eligible for PyPI publishing. Enforced in the PyPI job before any upload.
3. **Architecture coverage**: the standalone-binary job's matrix must produce all four expected `(os, arch)` combos. A missing combo fails the Release.
4. **Signing required**: every `Artifact` must produce a matching `Attestation` with a `signing_identity` derived from the same workflow. Smoke jobs verify this and fail if the assertion does not hold.
5. **Pre-release scope**: `Release.kind=prerelease` skips `FormulaBump` and `PluginPackage` jobs. A pre-release with either job present is a workflow misconfiguration; CI lints `release.yml` against this rule.
6. **Tag immutability**: pre-flight asserts no existing GitHub Release exists for the tag. Re-tagging is rejected.

---

## What this model deliberately does not include

- **A release-history database**: GitHub Releases is the source of truth for "what shipped when." No internal store.
- **Channel-state persistence**: each Channel's state lives in its native registry (PyPI listing, GHCR tags, GitHub Release assets, tap repo HEAD). No shadow copy.
- **Cross-release dependency tracking**: each `Release` is independent; the model does not encode "v0.2.0 supersedes v0.1.0" beyond what SemVer already implies.
- **Third-party plugin discovery state**: handled by darnit's existing entry-point mechanism at install time, not by this pipeline.
