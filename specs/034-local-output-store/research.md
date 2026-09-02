# Research: Local Output Data Store (Phase 0)

**Feature**: 034-local-output-store
**Date**: 2026-09-01

All items resolvable from source. No NEEDS CLARIFICATION markers.

---

## R-001: Platform-path conventions for `user-local`

**Decision**: hand-roll three platform-specific resolvers inside `platform_paths.py`, matching the XDG spec on Linux, Apple support/cache conventions on macOS, and `LOCALAPPDATA` on Windows. Do NOT introduce `platformdirs`.

**Resolutions per platform**:

| Kind | Linux | macOS | Windows |
|---|---|---|---|
| data (attestations, reports) | `${XDG_DATA_HOME:-$HOME/.local/share}/darnit/` | `~/Library/Application Support/darnit/` | `%LOCALAPPDATA%\darnit\Data\` |
| cache (audit cache) | `${XDG_CACHE_HOME:-$HOME/.cache}/darnit/` | `~/Library/Caches/darnit/` | `%LOCALAPPDATA%\darnit\Cache\` |

Per artifact kind: `<data-or-cache-root>/attestations/`, `<data-or-cache-root>/reports/`, `<cache-root>/audit-cache/`.

**Rationale**: The XDG defaults and Apple conventions are stable enough that hand-rolling three ~5-line resolvers is cheaper than pulling in `platformdirs` (which would violate FR-014's no-new-runtime-dependency constraint). The three implementations fit in ~40 lines total including the OS-dispatch. `platform.system()` returns `"Linux"` / `"Darwin"` / `"Windows"`; unknown platforms fall through to the Linux XDG path as the safest heuristic.

**Alternatives considered**:
- Introduce `platformdirs`. Cleaner code but violates FR-014.
- Use `pathlib.Path.home() / ".darnit" / <kind>` uniformly. Simpler but ignores Windows LOCALAPPDATA convention (`~/.darnit` on Windows is a home-dir dotfile, not the OS-idiomatic location).

---

## R-002: Filename sanitizer reuse

**Decision**: Import `_sanitize_filename` from `darnit.stores.defaults.attestation` in `local_fs.py`. Do NOT copy-paste. `FilesystemAuditCacheStore` (`stores/defaults/cache.py:22`) already sets this precedent.

**Source of truth** (`stores/defaults/attestation.py:48-53`):

```python
_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9._+@-]")

def _sanitize_filename(name: str) -> str:
    """Replace filesystem-unsafe characters with `_` for cross-platform safety."""
    return _FILENAME_UNSAFE.sub("_", name) or "unnamed"
```

**Rationale**: Regex handles path-traversal sanitization (SC-005) at the leaf-name level -- `/`, `..`, and shell metachars all map to `_`. Empty-string safety via the `or "unnamed"` fallback. Since attestation, report, and cache all pass their identifier through this function today, the new backends inherit the property automatically when they delegate to the existing classes.

**Consequence for path-traversal test (SC-005)**: `bundle_id = "../../etc/foo"` will produce a filename like `.._.._etc_foo.intoto.json` (each of `/` and space-adjacent chars replaced with `_`). Test asserts on the sanitized filename directly, not on a "no directory traversal escaped" absence check, because the file cannot escape by construction.

---

## R-003: `env_subst` mode for `root` interpolation

**Decision**: Use `missing="raise"` (fail-fast) for `root`, matching the operator-facing failure surface the spec wants for typos.

**API** (`packages/darnit/src/darnit/core/env_subst.py`):

```python
MissingMode = Literal["empty", "raise", "leave"]

def substitute_dollar_vars(
    template: str,
    env: Mapping[str, str] | None = None,
    *,
    missing: MissingMode = "empty",
) -> str: ...
```

Modes: `"empty"` replaces missing vars with `""` (default; correct for MCP arg templates where a missing token is common). `"raise"` raises `KeyError` naming the missing variable. `"leave"` keeps the literal `$FOO` token unchanged.

**Rationale for `"raise"`**: `root` is a configuration value the operator wrote down. A typo (`$DARNIT_ATT_ROT` instead of `$DARNIT_ATT_ROOT`) should be a loud audit-time error, not a silent expansion to `""` (which would then either error later in a confusing way, or worse, resolve `""` as the current directory). Fail-fast surfaces the misconfiguration where the operator can see it and correlate to the config line.

**Interaction with tildes**: `os.path.expanduser` (called AFTER `substitute_dollar_vars`) handles `~`. Order matters: substitute vars first, then expand `~`, then resolve to absolute. This preserves the semantics of e.g. `root = "$MY_HOME/darnit"` where `MY_HOME` might itself be `~/.local`.

**Alternatives considered**:
- `missing="empty"` (matches MCP arg default). Rejected because a silent-empty `root` is a data-integrity risk for attestations.
- `missing="leave"` (keeps `$FOO` literal). Rejected because a literal `$FOO/attestations/` directory landing in someone's tree is worse than a hard error.

---

## R-004: Atomic-write semantics on cross-filesystem `root`

**Decision**: No change needed. `FilesystemAuditCacheStore` already writes the tempfile into the SAME directory as the target (`stores/defaults/cache.py:53-56`), so a cross-filesystem `root` does not break the rename:

```python
fd, tmp_path = tempfile.mkstemp(
    dir=str(target.parent),   # same dir as target -> same filesystem
    suffix=".tmp",
    prefix="audit-cache-",
)
```

`LocalFsAuditCacheStore` inherits this by delegating to `FilesystemAuditCacheStore` with a different `root`. Same-filesystem rename atomicity is preserved even when `root` is on a network mount or a different device than `/tmp`.

**Rationale**: The pre-feature `darnit.core.audit_cache` module wrote its tempfile into the system tempdir and renamed across filesystems, which failed on Linux with `EXDEV`. Feature 033 already fixed that when it migrated to `FilesystemAuditCacheStore`. This feature inherits the fix; no re-implementation needed.

**Test coverage**: existing `test_filesystem_defaults.py::test_atomic_rename_leaves_no_tempfile` (feature 033) exercises the tempfile-then-rename path; new `test_local_fs_backend.py` parametrizes it against a `root` outside `/tmp` to double-cover the cross-fs case.

---

## R-005: `_StoreBundle` lazy instantiation with platform-path resolution

**Decision**: Compatible. Platform-path resolution happens inside the `UserLocal*Store.__init__`, which is called by the factory closure inside `_StoreBundle` on first property access -- not at `resolve_stores()` time.

**Verified against** `packages/darnit/src/darnit/stores/selection.py`:

- `resolve_stores()` builds factory closures that capture the backend class and kwargs; it does NOT instantiate.
- `_StoreBundle.project` / `.attestation` / `.report` / `.cache` are `@property` methods that call the factory on first access and memoize.
- Feature-033's `test_us1_lazy_instantiation.py` locks this: a bundle whose `.attestation` is never accessed never constructs the store.

**Consequence for FR-004 and SC-004**: `UserLocalAttestationStore.__init__` may do `platform.system()`, read `XDG_DATA_HOME` from env, and probe existence -- all safe because it only runs when the audit actually needs the attestation store. Zero-config audits and audits that never touch attestations pay zero cost.

**Class-shape Protocol validation (SC-007 preservation)**: `resolve_stores()` still does the eager class-shape check via `_protocol_methods()`. Since `UserLocal*Store` inherits or delegates to `LocalFs*Store` (which inherits from `Filesystem*Store`), the class shape validates without any instance construction.

---

## Summary of decisions

| # | Decision | Impact |
|---|---|---|
| R-001 | Hand-roll platform-path resolvers | ~40 lines, zero new deps |
| R-002 | Reuse `_sanitize_filename` from attestation.py | No copy-paste, SC-005 satisfied by construction |
| R-003 | Use `missing="raise"` for `root` interpolation | Loud-fail on config typos |
| R-004 | Delegate to `FilesystemAuditCacheStore` for atomic write | Cross-fs `root` handled by existing tempfile-in-target-dir |
| R-005 | Platform resolution inside `__init__`, gated by lazy bundle | SC-004 lazy-instantiation invariant preserved |

None of the five research questions requires further clarification. Ready to consume in Phase 1.
