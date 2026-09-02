# Implementation Plan: Local Output Data Store

**Branch**: `034-local-output-store` | **Date**: 2026-09-01 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/034-local-output-store/spec.md`

## Summary

Two new filesystem-backed `Store` backends, `local-fs` and `user-local`, that let operators write attestations / reports / audit-cache OUTSIDE the audited repository via `.baseline.toml`'s `[stores.<kind>] backend = "..."` selector. Extends feature 033's plugin surface with no Protocol changes; every backend ships inside `packages/darnit/src/darnit/stores/defaults/` alongside the existing in-repo `Filesystem*Store` defaults. Zero-config audits are byte-for-byte unchanged.

Technical approach in three moves:

1. **`LocalFsAttestationStore` / `LocalFsReportStore` / `LocalFsAuditCacheStore`** wrap the existing `Filesystem*Store` classes and swap the default in-repo root for a config-driven `root` (absolute path, `~`-expanded, or `$VAR`-substituted via `darnit.core.env_subst`).
2. **`UserLocalAttestationStore` / `UserLocalReportStore` / `UserLocalAuditCacheStore`** compute a platform-appropriate root at construction time (XDG on Linux, `~/Library/{Application Support,Caches}/darnit` on macOS, `%LOCALAPPDATA%\darnit\{Data,Cache}` on Windows) and delegate to the `LocalFs*` layer.
3. **Entry-point registrations** under `darnit.stores.{attestation,report,cache}` for both backend names. `.project/` gets `local-fs` too for completeness, but `user-local` is deliberately NOT registered for `stores.project` (per FR-009: `.project/` stays in-repo).

Every outside-repo write emits one info-level log line per artifact naming the backend, kind, and resolved path (FR-015 / SC-009). All feature 033 constitutional guarantees hold: no new runtime dep, no framework-side wiring changes, no `Store` Protocol methods added.

## Technical Context

**Language/Version**: Python 3.11 / 3.12 (workspace targets from CLAUDE.md)

**Primary Dependencies**: stdlib only. `pathlib.Path`, `os.path.expanduser`, `os.environ` for `$VAR` (already fronted by `darnit.core.env_subst` from feature 033). No new packages.

**Storage**: Filesystem. Local. Outside the audited repo when configured; per-repo `.darnit/` when not.

**Testing**: pytest (workspace default). Existing feature-033 test surface at `tests/darnit/stores/` is the template for the new tests. Some tests parametrize by platform.

**Target Platform**: macOS + Linux fully supported. Windows is stretch goal per spec assumption; unit-tested with a mocked platform-name lookup, integration-tested only if a Windows CI runner exists at implement time.

**Project Type**: Library extension inside an existing workspace member (`packages/darnit/`). No new package.

**Performance Goals**: N/A. Filesystem I/O bounded by disk speed. One additional info-log per artifact per audit is trivial overhead.

**Constraints**:
- No new runtime dependency (FR-014).
- No changes to `Store` Protocol methods.
- `.project/` MUST stay in-repo even when `user-local` is selected for other kinds (FR-009).
- Feature 033's `test_us2_zero_config.py` MUST continue to pass unchanged (SC-003).
- Path-traversal sanitizer reused from `packages/darnit/src/darnit/stores/defaults/` (spec Key Entities note).

**Scale/Scope**: 3 artifact kinds (attestation, report, cache) x 2 backends = 6 concrete classes + up to 7 entry-point registrations. Estimated ~150 lines of implementation code, ~250 lines of tests, ~1 docs section.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| I. Plugin Separation | PASS | New backends live in `packages/darnit/src/darnit/stores/defaults/` inside darnit-core. Constitution I forbids darnit-core importing implementation packages; adding built-in filesystem behaviors is explicitly compatible (matches feature 033's precedent). |
| II. Conservative-by-Default | PASS | FR-013 preserves feature 033's per-Protocol failure semantics: no silent fallback (SC-008), attestation write errors surface, cache is best-effort. No new "compliant" claim path opens up. |
| III. TOML-First Architecture | PASS | Everything configured through `[stores.<kind>] backend = "..." root = "..."` in TOML. Zero Python for operators. |
| IV. Never Guess User Values | N/A | Storage backends don't produce or consume user-judgment values. `.project/` stays in-repo (FR-009) so no user-judgment value is silently relocated. |
| V. Sieve Pipeline Integrity | N/A | Backends are not sieve passes; they don't participate in the 4-phase pipeline. |

**Initial gate: PASS.** No violations. Re-check after Phase 1 design.

## Project Structure

### Documentation (this feature)

```text
specs/034-local-output-store/
├── plan.md              # this file (/speckit-plan output)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── local-fs.md
│   └── user-local.md
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
packages/darnit/src/darnit/stores/defaults/
├── __init__.py                       # add new re-exports
├── attestation.py                    # FilesystemAttestationStore (existing) -- untouched
├── cache.py                          # FilesystemAuditCacheStore (existing) -- untouched
├── project.py                        # FilesystemProjectStateStore (existing) -- untouched
├── report.py                         # FilesystemReportStore (existing) -- untouched
├── local_fs.py                       # NEW: LocalFs{Attestation,Report,Cache,Project}Store
├── user_local.py                     # NEW: UserLocal{Attestation,Report,Cache}Store
└── platform_paths.py                 # NEW: Linux/macOS/Windows XDG-style path resolution

packages/darnit/pyproject.toml         # ADD up to 7 entry-point registrations under
                                       # darnit.stores.{project,attestation,report,cache}
                                       # (project gets local-fs only, not user-local; FR-009)

tests/darnit/stores/
├── test_local_fs_backend.py           # NEW: parametric per-kind coverage of local-fs
├── test_user_local_backend.py         # NEW: same, plus platform-parameterized root resolution
├── test_platform_paths.py             # NEW: unit tests for the resolver
├── test_local_fs_logging.py           # NEW: caplog assertions for FR-015 / SC-009
├── test_local_fs_isolation.py         # NEW: attest -> local-fs, others stay in-repo (SC-007)
└── (existing tests unchanged;
   test_us2_zero_config.py is the SC-003 witness)

docs/plugin-authoring/
└── stores.md                          # ADD a "Writing artifacts outside the repo" section
                                       # (SC-006)
```

**Structure decision**: single-package extension inside `packages/darnit/`. No new workspace member, no new test dir. The two new backend files and one platform-paths helper each live next to their existing siblings under `stores/defaults/`, matching the shape feature 033 established. Tests mirror the module split so failures point at one file.

## Phase 0: Outline & Research

No NEEDS CLARIFICATION markers survived the clarify pass (spec's Clarifications section, session 2026-09-01). The five items in `research.md` are all dependencies already-existing in the feature 033 surface; research consolidates the API contracts and edge cases:

1. What platform-path conventions should `user-local` follow, cross-referenced against `platformdirs`-style community norms without introducing that dependency?
2. What exact filename sanitizer does feature 033's `FilesystemAttestationStore` use, and can `LocalFs*` reuse it verbatim?
3. What does the existing `darnit.core.env_subst` interface look like -- is `missing="leave"` the right mode for `root`, or should we prefer `"raise"` to fail fast on typos?
4. What tempfile-then-rename semantics does `FilesystemAuditCacheStore` use, and do they hold when `root` is on a different filesystem than the system tempdir?
5. Does feature 033's `_StoreBundle` lazy-instantiation still work correctly when a `user-local` backend's `__init__` does platform-path resolution?

All five resolvable from source. See `research.md` for the resolutions.

## Phase 1: Design & Contracts

### Data model

See [data-model.md](data-model.md). Five entities:

- **`LocalFs*Store`**: three concrete classes (attestation, report, cache) that wrap the existing `Filesystem*Store` with a `root` computed from config. A fourth `LocalFsProjectStateStore` is defined but its use is documented as unusual.
- **`UserLocal*Store`**: three concrete classes (attestation, report, cache) that resolve `root` from platform conventions and delegate to `LocalFs*Store`.
- **`platform_paths`**: functions `xdg_data_home()`, `xdg_cache_home()`, `user_data_root()`, `user_cache_root()` -- OS-dispatching path resolution.
- **`root` config field**: TOML string on the `[stores.<kind>]` block. Absolute, `~`-relative, or `$VAR`-templated. Interpolated at store construction, not lazily on write.
- **Info-log format**: single `logger.info("wrote %s (%s): %s", kind, backend, resolved_path)` per artifact write. Shared logger name `darnit.stores.local`.

### Contracts

See `contracts/local-fs.md` and `contracts/user-local.md`. Each contract enumerates the config keys accepted, the resolved-root computation, error modes (per Protocol), logging obligations, and the interaction with `.project/` (`local-fs` may be selected for `stores.project`; `user-local` is NOT registered for `stores.project`).

### Quickstart

See [quickstart.md](quickstart.md). Three worked examples:

1. **Consolidate attestations for an OSPO leader**: `[stores.attestation] backend = "local-fs" root = "$DARNIT_ATT_ROOT"` + explanation of env-var-driven multi-repo templating (the Q1 answer).
2. **CI runner cache + reports**: two `[stores.<kind>]` blocks pointing at runner-provided paths.
3. **XDG defaults on Linux / macOS conventions**: `backend = "user-local"` per kind; explain the resolved roots per platform.

### Agent context update

CLAUDE.md's `<!-- SPECKIT START -->` marker currently points at feature 033's plan. Update to point at this feature's plan (done at end of Phase 1).

## Constitution re-check (post-design)

| Principle | Status |
|---|---|
| I. Plugin Separation | PASS -- design only touches `packages/darnit/src/darnit/stores/defaults/`, adds no cross-package imports |
| II. Conservative-by-Default | PASS -- per-Protocol failure semantics preserved verbatim; no new "compliant" claim path opens up |
| III. TOML-First Architecture | PASS -- config surface stays TOML; backend names are first-class selectors |
| IV. Never Guess User Values | N/A |
| V. Sieve Pipeline Integrity | N/A |

**Final gate: PASS.** Ready for `/speckit-tasks`.
