# Feature Specification: Local Output Data Store

**Feature Branch**: `034-local-output-store`

**Created**: 2026-09-01

**Status**: Draft

**Input**: User description: "I want to develop a local output data store of some kind. Something that can just store stuff like .project, but also output stuff outside the project directory if need be."

## Clarifications

### Session 2026-09-01

- Q: How does an OSPO leader avoid duplicating `[stores.*]` across every one of their 30 repos? → A: Stay per-repo `.baseline.toml`. Operators template the block via CI/CD, cookiecutter, or a copy-once repo-init tool; env-var interpolation (feature 033's `$VAR` support) makes `root = "$DARNIT_ATT_ROOT"` the escape hatch. No new org- or user-level config file is in scope for this feature.
- Q: Register `local-fs` and `user-local` as one backend with a mode, or as two independently-registered backends? → A: Two independent backends. Each ships its own entry-point registration per artifact kind; `user-local` extends `local-fs` internally to resolve `root` from platform conventions but presents as a distinct `backend = "user-local"` selector in TOML. Class hierarchy stays clean; tests exercise each backend by its published name.
- Q: When an artifact lands outside the repo, does darnit log the resolved absolute path? → A: Yes, at info level, one line per successful outside-repo write, naming the backend, the artifact kind, and the resolved path. Makes CI logs self-documenting and forecloses the "silent misconfiguration" failure mode where an operator can't tell where their attestations went.

## Context

Feature 033 (issue #394, PR #396) landed the pluggable per-artifact `Store` Protocols and their filesystem defaults. Every default writes INSIDE the audited repository:

- `ProjectStateStore` -> `<repo>/.project/project.yaml`, `<repo>/.project/maintainers.yaml`
- `AttestationStore` -> `<repo>/.darnit/attestations/`
- `ReportStore` -> `<repo>/.darnit/reports/`
- `AuditCacheStore` -> per-repo hash under system tempdir (already outside)

That constraint is intentional for `.project/project.yaml` -- it belongs in the repo because it's the maintainer-curated source of truth for project metadata (per the CNCF `.project/` spec). But it is a hard limit for everything else. Today an operator has no way to say:

- "Write all attestations to `~/.darnit/attestations/` so I can back them up together"
- "Aggregate reports for every repo in this org under `/var/log/darnit/<org>/`"
- "Send audit cache to XDG-standard `$XDG_CACHE_HOME/darnit/` instead of hashed system-tempdir paths"
- "Keep sensitive audit output outside the git tree so `git add` can't leak it"

This spec covers the local outside-repo destination story. It stays within the plugin surface feature 033 defined -- concretely, this becomes a new default backend (or a set of them) that ships in darnit-core alongside the existing in-repo defaults. Remote/network-backed storage (Postgres, S3, Archivista) remains out of scope and stays in issue #391 territory.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - OSPO leader points attestations at a shared local directory (Priority: P1)

An OSPO leader auditing 30 repos across their org wants every attestation to land in one place they can back up, sync to a paved-road location, or point their SBOM pipeline at. Today each attestation writes into its own repo's `.darnit/attestations/` -- 30 scattered destinations. They want:

```toml
# Per-repo .baseline.toml (this feature does NOT add an org- or user-level
# config file; see the Clarifications section for the rationale). To avoid
# duplicating this block across 30 repos, operators template it via CI/CD,
# cookiecutter, or a repo-init tool. Env-var interpolation is the escape
# hatch: `root = "$DARNIT_ATT_ROOT"` lets a single per-machine env var
# steer every repo's audits.
[stores.attestation]
backend = "local-fs"
root = "~/darnit-attestations"
```

...and have every audit's attestation land there instead of in the repo.

**Why this priority**: This is the concrete use case that motivated the request. Attestations are the highest-value output to consolidate because they're what an OSPO leader hands to a downstream consumer (regulator, customer, org compliance dashboard).

**Independent Test**: Configure `[stores.attestation] backend = "local-fs" root = "/tmp/agg"` on a repo, run an audit that emits an attestation, verify the bundle lands at `/tmp/agg/<bundle_id>.intoto.json` (or `.sigstore.json`) and NOT in `<repo>/.darnit/attestations/`.

**Acceptance Scenarios**:

1. **Given** `[stores.attestation] backend = "local-fs" root = "/tmp/attestations"` is set and `/tmp/attestations/` does not yet exist, **When** the audit runs and produces one attestation, **Then** `/tmp/attestations/<bundle_id>.<ext>` exists and contains the bundle, and the repo's `.darnit/attestations/` is not created.
2. **Given** the same config with an existing non-empty `/tmp/attestations/`, **When** two consecutive audits produce two attestations, **Then** both bundles coexist in the directory and neither overwrites the other.
3. **Given** `root = "~/darnit-attestations"` (tilde-expansion), **When** the audit runs, **Then** the bundle lands at the resolved home path, not literal `~/darnit-attestations`.
4. **Given** the configured `root` is unwritable (permission denied), **When** the audit runs, **Then** the operator sees a clear error naming the backend and the path, and the audit does not silently write to a fallback location.

---

### User Story 2 - Operator redirects reports and cache outside the repo (Priority: P2)

An operator running darnit on a CI runner (fresh repo checkout per job) wants:

- The audit-cache to live in a persistent per-runner location so cache hits work across jobs.
- The Markdown/JSON/SARIF reports to land in an artifact directory the runner already knows how to upload.

Neither destination is inside the repo checkout.

**Why this priority**: Reports and audit-cache are lower-value to consolidate than attestations (reports are per-run outputs, cache is a performance optimization), but the same abstraction that solves US1 solves both cleanly. Doing them together avoids a second round-trip on the design.

**Independent Test**: With `[stores.report] backend = "local-fs" root = "$RUNNER_ARTIFACTS/reports"` and `[stores.cache] backend = "local-fs" root = "$RUNNER_CACHE/darnit"`, run an audit twice back-to-back. Verify the Markdown/JSON reports land under the report root and the second run's audit-cache hit is served from the cache root.

**Acceptance Scenarios**:

1. **Given** the two configs above, **When** the audit produces a Markdown report, **Then** it lands at `<RUNNER_ARTIFACTS>/reports/<report_id>.md`, not `<repo>/.darnit/reports/`.
2. **Given** the same config with `$RUNNER_CACHE/darnit` seeded from a prior run, **When** a fresh audit runs against the same commit, **Then** the cache read hits and the audit skips the sieve loop.
3. **Given** the report `root` contains other files, **When** the audit runs, **Then** it does not delete or reorganize files it did not write.

---

### User Story 3 - Operator selects an XDG-standard location without spelling it out (Priority: P2)

An operator on Linux wants darnit's default outside-repo behavior to follow the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html): cache in `$XDG_CACHE_HOME/darnit`, data in `$XDG_DATA_HOME/darnit`. On macOS the equivalent is `~/Library/Caches/darnit` and `~/Library/Application Support/darnit`; on Windows it's `%LOCALAPPDATA%\darnit\Cache` and `%LOCALAPPDATA%\darnit\Data`. They want to type one thing:

```toml
[stores.attestation]
backend = "user-local"
```

...and have the backend do the right thing per platform.

**Why this priority**: Convenience layer on top of US1. Materially reduces the config an operator has to write for the "just put it somewhere sensible outside the repo" case. Not strictly necessary if US1 lands -- the operator can always spell out `$HOME/.local/share/darnit/attestations` explicitly.

**Independent Test**: On Linux with `XDG_DATA_HOME` unset, configure `[stores.attestation] backend = "user-local"`. Run an audit, verify the bundle lands at `~/.local/share/darnit/attestations/<bundle_id>.<ext>`. Repeat with `XDG_DATA_HOME=/tmp/xdg` set; verify the bundle now lands at `/tmp/xdg/darnit/attestations/`.

**Acceptance Scenarios**:

1. **Given** Linux, `XDG_DATA_HOME` unset, `[stores.attestation] backend = "user-local"`, **When** an audit produces an attestation, **Then** it lands under `~/.local/share/darnit/attestations/`.
2. **Given** Linux, `XDG_CACHE_HOME=/mnt/fast-cache/`, `[stores.cache] backend = "user-local"`, **When** an audit produces a cache write, **Then** the cache file lands under `/mnt/fast-cache/darnit/audit-cache/`.
3. **Given** macOS with the same config, **When** the audit runs, **Then** the destinations follow macOS conventions (`~/Library/Application Support/darnit/`, `~/Library/Caches/darnit/`).

---

### User Story 4 - Filesystem defaults are unchanged unless the operator opts in (Priority: P1)

An existing darnit user who has never configured `[stores.*]` and never edits their config sees no behavior change. Attestations still land in `<repo>/.darnit/attestations/`, reports in `<repo>/.darnit/reports/`, cache in the current per-repo tempdir hash.

**Why this priority**: Backward-compat and constitution I (darnit-core stays predictable). This is a US-shaped invariant, not a feature -- but it needs its own acceptance path so the fix for US1/US2/US3 doesn't accidentally re-home files for the 100% of users who never configured anything.

**Independent Test**: Run an audit on a repo with no `[stores.*]` config; assert every artifact lands at the exact same path it landed at before this feature. Test both a fresh repo and one with pre-existing `.darnit/attestations/` content.

**Acceptance Scenarios**:

1. **Given** no `[stores.*]` block anywhere in the effective config, **When** the audit runs, **Then** attestations, reports, and cache land at the pre-feature default paths.
2. **Given** a `[stores.attestation]` block set to `backend = "local-fs" root = "/tmp/x"`, **When** the audit runs, **Then** only attestations re-home; reports and cache still use the in-repo defaults.

---

### Edge Cases

- **Tilde (`~`) and `$VAR` in `root`**: users expect these to expand. If they don't, the operator gets a literal directory named `~` in cwd -- surprising and hard to notice until backup time.
- **Symlinks in `root`**: the operator points at `~/attestations` which is a symlink to a network mount. The store should honor the symlink target, not the link.
- **Path escape via `bundle_id`**: a malicious or malformed control emits `bundle_id = "../../etc/passwd"`. The store MUST sanitize so the write stays under `root`.
- **`root` on a different filesystem than the repo**: the store must not assume same-filesystem rename atomicity. `os.rename` across filesystems fails on Linux; write-then-rename in the cache backend needs to be same-filesystem OR degrade gracefully.
- **`root` is a file, not a directory**: distinct error from "does not exist" -- the operator misconfigured.
- **`root` grows unbounded**: no automatic pruning is in scope; the operator manages retention. But the docs should call this out.
- **Multiple concurrent audits sharing the same `root`**: two audit processes running against different repos both write to `~/darnit-attestations/`. Bundle IDs already carry repo/owner so filename collision is unlikely, but the store must not corrupt files on concurrent writes to different filenames. No inter-audit locking is in scope.
- **Windows path handling**: the `root` string may use forward or back slashes; the store should normalize.
- **`.project/` writes**: the CNCF spec says `.project/` belongs in the repo. This feature MUST NOT re-home `.project/` by default, even under `backend = "user-local"`. Explicit `[stores.project]` override remains available but is documented as unusual.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The framework MUST support two new filesystem-backed store families that write outside the audited repository, each independently selectable via `.baseline.toml`'s `[stores.<kind>] backend = "..."` selector. The two names are `local-fs` and `user-local`.
- **FR-002**: Both new backends MUST plug into the feature-033 `Store` Protocol surface with no new Protocol methods.
- **FR-003**: The `local-fs` backend MUST accept a `root` config field (absolute path, `~`-expanded home path, or `$VAR`-substituted environment variable) and write every artifact of its kind under that root.
- **FR-004**: The `user-local` backend MUST resolve `root` from platform conventions -- XDG on Linux, Apple support/cache dirs on macOS, LOCALAPPDATA on Windows -- without the operator spelling out a full path. Passing `root` to `user-local` explicitly MUST either be ignored with a warning or rejected with a clear error; the plan phase picks between the two.
- **FR-005**: When an operator configures `[stores.<kind>]` to a new outside-repo backend, artifacts of that kind MUST land at the configured location AND MUST NOT also be written to the in-repo default location.
- **FR-006**: When an operator does NOT configure `[stores.<kind>]`, behavior for that kind MUST be identical to pre-feature -- same paths, same file names, same on-disk shape.
- **FR-007**: The `root` MUST be created if it does not exist and the operator has permission; missing `root` MUST NOT be an audit failure IF the store's failure semantics per feature 033 are "best-effort" (audit-cache), and MUST surface a clear operator-facing error otherwise.
- **FR-008**: The new backend MUST sanitize identifiers passed as filename components (`bundle_id`, `report_id`, `cache_key`) so that a control cannot cause a write outside `root` via path traversal.
- **FR-009**: The `.project/` project-state store is DIFFERENT: it MUST default to the in-repo `<repo>/.project/` even when the operator selects `backend = "user-local"` for other kinds. Overriding `[stores.project]` explicitly remains possible but is documented as unusual.
- **FR-010**: Configuration precedence stays consistent with feature 033: framework-config `[stores.<kind>]` block is overridden per-kind by user-config `[stores.<kind>]` block; no partial merge within a kind.
- **FR-011**: The framework MUST document each new backend and its config knobs in the plugin-authoring guide (`docs/plugin-authoring/stores.md`) so operators can find them.
- **FR-012**: The framework MUST provide a way for tests and CI to override paths deterministically (e.g., a `DARNIT_STORE_ROOT` env-var interpolation, or per-kind env-var like `DARNIT_ATTESTATION_ROOT`) so parity tests and regression harnesses aren't tied to a real home directory.
- **FR-013**: When a new backend fails to write (permission denied, ENOSPC, etc.), the failure mode MUST match the Protocol's contract per feature 033: attestation/report writes surface as audit-run errors; cache writes are swallowed to a warning log; project-state reads/writes surface as WARN on the affected controls.
- **FR-014**: The new backend MUST NOT introduce any new runtime dependency into darnit-core.
- **FR-015**: After every successful write from `local-fs` or `user-local`, the backend MUST emit an info-level log line naming the backend, the artifact kind, and the resolved absolute path. This applies only to the outside-repo backends; the pre-existing in-repo filesystem defaults are unchanged.

### Key Entities

- **`local-fs` backend**: a filesystem-backed backend that writes to any configurable root path, honoring `~` and `$VAR` expansion. Same Protocol surface as the existing `Filesystem*Store` defaults from feature 033; the difference is where `root` gets resolved from. Registered under each `darnit.stores.<kind>` entry-point group as `local-fs`.
- **`user-local` backend**: a variant that resolves `root` from platform conventions instead of a config value. Internally extends `local-fs`'s open+write logic and delegates once the platform root is resolved. Registered under each `darnit.stores.<kind>` entry-point group as `user-local` so it's a first-class TOML selector, not a hidden mode of `local-fs`.
- **`root` config value**: a string in `.baseline.toml`'s `[stores.<kind>]` block. Absolute path, `~`-relative, or `$VAR`-templated. Interpolation MUST already exist per feature 033's shared `darnit.core.env_subst` helper -- confirm at plan time.
- **Path sanitizer**: shared logic that ensures `bundle_id`/`report_id`/`cache_key` cannot cause writes outside `root`. Reuses the sanitizer already in `packages/darnit/src/darnit/stores/defaults/` -- confirm at plan time.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can point attestations, reports, or cache at any local filesystem location outside the repo with a two-line `.baseline.toml` change (`backend = "..."` + `root = "..."`). No Python, no fork.
- **SC-002**: For every artifact kind configured to a new backend, ZERO writes land at the pre-feature in-repo default path. Verified by an audit-then-grep test that fails if the in-repo path was touched.
- **SC-003**: Zero-config audits (no `[stores.*]` block anywhere) write to the exact same on-disk paths as pre-feature. Verified by the feature-033 US2 zero-config test (`test_us2_zero_config.py`) continuing to pass unchanged.
- **SC-004**: A user-local audit on Linux writes to `$XDG_DATA_HOME/darnit/attestations/` (or `~/.local/share/darnit/attestations/` if `XDG_DATA_HOME` is unset), on macOS to `~/Library/Application Support/darnit/attestations/`, and on Windows to `%LOCALAPPDATA%\darnit\Data\attestations\`. Verified per-platform in CI or with a platform-parameterized unit test.
- **SC-005**: A path-traversal attempt via `bundle_id = "../../etc/foo"` produces a file named exactly `..__..__etc__foo.<ext>` (or equivalent sanitized form) under the configured root, and never a write outside root. Verified by fault-injection unit test.
- **SC-006**: The plugin-authoring guide includes a section titled "Writing artifacts outside the repo" with a copy-pasteable `.baseline.toml` snippet for the most-common cases (shared attestation dir, XDG cache, CI runner artifacts dir).
- **SC-007**: `.project/project.yaml` still lands in the audited repo when the operator sets `backend = "user-local"` on OTHER stores but leaves `[stores.project]` unset. Verified by an integration test that asserts `<repo>/.project/project.yaml` exists post-audit and no darnit-owned .project file exists under the user-local root.
- **SC-008**: An audit whose configured `root` is unwritable produces a single operator-facing error message that names the backend, the artifact kind, and the resolved path -- and does NOT silently fall back to the in-repo default (would violate feature 033 FR-012, no silent fallback).
- **SC-009**: An audit that writes at least one artifact to `local-fs` or `user-local` produces at least one info-level log line per artifact class, and each log line contains the backend name (`local-fs` or `user-local`), the artifact kind (`attestation`/`report`/`cache`), and the resolved absolute path. Verified by a capsys/caplog assertion on a fixture audit. Zero-config audits produce no such lines.

## Assumptions

- The feature-033 `Store` abstraction is the extension point. No new Protocol methods, no framework-level rewiring of the audit driver.
- `.baseline.toml`'s `[stores.<kind>]` block already accepts arbitrary backend-specific keys per the `StoreBlock` model (Pydantic `extra = "allow"`). `root` is one such key. No config schema change needed.
- `$VAR` substitution in TOML string values already exists per feature 033's `darnit.core.env_subst` helper. Interpolation applies here without change.
- The audited repo is not the same directory as the user's home. If they are, `user-local` still writes to a resolved home path which happens to be inside the repo -- that's the operator's problem, not a spec issue.
- Cross-filesystem writes (root on a network mount, tempdir on local disk) may lose atomic-rename guarantees on some platforms. This is a filesystem property, not a darnit contract; the store's write should degrade gracefully (e.g., regular write + rename inside the same directory as the target file, not a system tempdir).
- No retention / rotation / TTL logic is in scope. Operators manage their `root` directories themselves.
- `.project/` write-back stays in the repo per the CNCF `.project/` spec's implicit assumption that the file is committable. This is a hard rule, not a default.
- Windows platform coverage is a stretch goal for SC-004; if CI doesn't have a Windows runner, the Windows path resolution is unit-tested with a mocked `os.name` rather than integration-tested.

## Dependencies

- Feature 033 (PR #396, merged): the `Store` Protocol surface. This spec has no path forward without it.
- `darnit.core.env_subst` helper (added in 033): used for `$VAR` interpolation in `root` strings.
- Existing per-artifact filesystem defaults in `packages/darnit/src/darnit/stores/defaults/`: the new backends are variants of these, sharing the filename sanitizer and content-type mapping.

## Out of Scope

- **A new config layer**. This feature stays on per-repo `.baseline.toml`. No org-level, user-level, or machine-level TOML file, and no `--stores-config` CLI flag. The "one config, many repos" story is a separate feature; operators bridge it today via CI/CD templating, cookiecutter, or env-var interpolation on the existing `.baseline.toml`.
- Remote / network-backed storage (Postgres, S3, Archivista, in-toto-attestation-verifier, GCS, etc.). Those remain issue #391 and are separate backends shipped as plugin packages, not filesystem variants.
- Multi-tenant or org-wide storage patterns beyond "one operator points at one local root." Aggregating across multiple developer machines is out of scope.
- Retention, rotation, or TTL for outside-repo directories. Operators own their storage lifecycle.
- Automatic migration of existing in-repo `<repo>/.darnit/` content to a newly-configured outside-repo `root`. If an operator switches configs, old files stay where they were.
- Windows-native path shape testing beyond a unit test with mocked path convention lookup, unless a Windows CI runner is already available at plan time.
- Encryption-at-rest for outside-repo destinations. If sensitive attestation content is a concern the operator uses filesystem-level or LUKS-level encryption; darnit doesn't ship its own.
