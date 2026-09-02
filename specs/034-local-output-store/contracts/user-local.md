# Contract: `user-local` backend

**Backend name (TOML)**: `user-local`
**Registered under**: `darnit.stores.attestation`, `darnit.stores.report`, `darnit.stores.cache`
**NOT registered under**: `darnit.stores.project` (FR-009: `.project/` stays in-repo)
**Config surface**: `[stores.<kind>]` block in `.baseline.toml`

## TOML surface

```toml
[stores.<kind>]
backend = "user-local"
# No config keys are required or honored. Any `root = "..."` is ignored with a warning.
```

- No config knobs. The whole point of `user-local` is that the operator doesn't spell out paths.

## Root resolution

Computed at `__init__` from the platform via `platform_paths` (E-003):

| Platform | Data root (attestations, reports) | Cache root (audit cache) |
|---|---|---|
| Linux | `${XDG_DATA_HOME:-$HOME/.local/share}/darnit/` | `${XDG_CACHE_HOME:-$HOME/.cache}/darnit/` |
| macOS | `~/Library/Application Support/darnit/` | `~/Library/Caches/darnit/` |
| Windows | `%LOCALAPPDATA%\darnit\Data\` | `%LOCALAPPDATA%\darnit\Cache\` |
| Unknown platform | XDG fallback (same as Linux) | XDG fallback (same as Linux) |

Per artifact kind, the store appends its own subdirectory:

| Kind | Class | Resolved path |
|---|---|---|
| attestation | `UserLocalAttestationStore` | `<data-root>/attestations/` |
| report | `UserLocalReportStore` | `<data-root>/reports/` |
| cache | `UserLocalAuditCacheStore` | `<cache-root>/audit-cache/` |

## Extra `root` kwarg: warn-and-ignore (FR-004)

Per FR-004: "Passing `root` to `user-local` explicitly MUST either be ignored with a warning or rejected with a clear error; the plan phase picks between the two." **Decision: warn-and-ignore**, matching E-002.

Behavior:

- On `__init__`, if the incoming kwargs contain a non-empty `root` value, emit ONE warning-level log line to logger `darnit.stores.local`:
  ```
  WARNING user-local backend ignores `root = <value>`; using platform default: <resolved-platform-root>
  ```
- Then proceed with the platform-computed root as normal. The extraneous kwarg is dropped.

Rationale: less disruptive than a hard error for operators who copied a config example from a `local-fs` block. The warning is loud enough to correlate to the offending config line if the operator is watching logs.

## Delegation to `local-fs`

`UserLocal*Store` inherits from `LocalFs*Store`. Once platform resolution is done, `super().__init__(root=<resolved>)` runs the same chain: `_sanitize_filename`, delegate to `Filesystem*Store` for I/O, tempfile-then-rename for cache.

## Logging (FR-015 / SC-009)

Every successful write emits one info-level log line to logger `darnit.stores.local`:

```
INFO wrote <kind-tag> (user-local): <resolved-absolute-path>
```

- `<kind-tag>`: same values as `local-fs` -- `"attestation"`, `"report:markdown"` | `"report:json"` | `"report:sarif"`, or `"cache"`.
- `<resolved-absolute-path>`: the full absolute path computed via `platform_paths` + subdirectory.

## `_StoreBundle` lazy-instantiation guarantee (R-005)

`UserLocal*Store.__init__` reads `platform.system()`, environment variables (`$XDG_DATA_HOME` / `$LOCALAPPDATA`), and `Path.home()`. This work runs ONLY when the store is first accessed via a `_StoreBundle` property -- feature 033's factory closures defer construction. An audit that never touches attestations pays zero cost even if `[stores.attestation] backend = "user-local"` is configured.

## Test surface

- `tests/darnit/stores/test_user_local_backend.py`:
  - parametric per-kind write round-trip on the runtime platform;
  - explicit-root warn-and-ignore assertion;
  - assertion that `super().__init__(root=<resolved>)` is called with the expected computed path.
- `tests/darnit/stores/test_platform_paths.py`:
  - `xdg_data_home()` with `$XDG_DATA_HOME` set + unset;
  - `xdg_cache_home()` with `$XDG_CACHE_HOME` set + unset;
  - `user_data_root()` / `user_cache_root()` with `platform.system()` monkeypatched to `"Linux"`, `"Darwin"`, `"Windows"`, and `"FreeBSD"` (unknown fallback).
- `tests/darnit/stores/test_local_fs_isolation.py`: with `[stores.attestation] backend = "user-local"` + `[stores.project]` unset, `<repo>/.project/` is still used for project state.

## Interaction with `.project/` (FR-009)

There is no `UserLocalProjectStateStore` class. There is no entry-point registration under `darnit.stores.project`. An operator writing `[stores.project] backend = "user-local"` in TOML MUST get a `StoreNotInstalled` error at `resolve_stores()` time -- feature 033 raises before any control runs, satisfying SC-007's stronger interpretation ("`.project/` stays in-repo when other kinds are user-local").

## Non-scope

- No `root` config surface (the whole point of `user-local`).
- No `.project/` support.
- No mixed-mode (e.g., "user-local for data, XDG override for cache") -- the operator uses two separate `[stores.<kind>]` blocks if they want asymmetric config, one `user-local` and one `local-fs`.
