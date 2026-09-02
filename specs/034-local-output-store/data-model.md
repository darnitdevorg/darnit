# Data Model: Local Output Data Store (Phase 1)

**Feature**: 034-local-output-store
**Date**: 2026-09-01

Five entities. No new persisted data schema; every entity is either a Python class hierarchy or a TOML config field.

---

## E-001: `LocalFs*Store` (3 classes + 1 optional)

**Purpose**: filesystem-backed store variants that write to any configurable `root` path outside the audited repository.

**Classes**:

| Class | Protocol satisfied | File |
|---|---|---|
| `LocalFsAttestationStore` | `AttestationStore` | `packages/darnit/src/darnit/stores/defaults/local_fs.py` |
| `LocalFsReportStore` | `ReportStore` | same file |
| `LocalFsAuditCacheStore` | `AuditCacheStore` | same file |
| `LocalFsProjectStateStore` | `ProjectStateStore` | same file (optional -- registered but flagged unusual per FR-009) |

**Construction contract** (shared shape, per class):

- `__init__(self, root: str | Path, **_)`.
  - `root: str` accepted from TOML with `$VAR` interpolation and `~` expansion applied at construction, in that order.
  - `root: Path` accepted from Python callers (tests) verbatim.
  - Extra `**_` kwargs are accepted-and-ignored to preserve compatibility with feature 033's `_instantiate_plugin` kwargs pass-through.
- Delegates to the matching `Filesystem*Store(root=<resolved>)` internally.

**Root resolution rules** (applied in order at `__init__`):

1. If input is a `Path`, use as-is (test-only shortcut).
2. If input is a `str`, run `substitute_dollar_vars(root, missing="raise")` (per R-003). A missing env var raises `KeyError` here, before the audit begins.
3. Run `os.path.expanduser(resolved)` to expand `~`.
4. Convert to absolute `Path` via `Path(resolved).resolve()` for logging + downstream I/O.
5. Do NOT create the directory yet -- creation happens on the first write, consistent with `FilesystemAttestationStore`.

**Write contract**: delegate verbatim to the corresponding `Filesystem*Store` write method. The delegate handles directory creation, filename sanitization (`_sanitize_filename`), tempfile-then-rename for cache, and content-type-to-extension mapping for attestation.

**Logging obligation** (FR-015): after every successful write, emit exactly one info-level line to logger `darnit.stores.local`:

```
INFO wrote <kind> (local-fs): <resolved-absolute-path>
```

Where `<kind>` is `"attestation"`, `"report:markdown"` / `"report:json"` / `"report:sarif"`, or `"cache"`. The `report:*` split gives the operator one log line per format so multi-format audit runs are self-documenting.

**Close contract**: `close()` is a no-op, matching the delegate.

---

## E-002: `UserLocal*Store` (3 classes)

**Purpose**: convenience variants that resolve `root` from platform conventions so operators don't spell out full paths.

**Classes**:

| Class | Protocol satisfied | Data root computation | Cache root computation |
|---|---|---|---|
| `UserLocalAttestationStore` | `AttestationStore` | `platform_paths.user_data_root() / "attestations"` | N/A |
| `UserLocalReportStore` | `ReportStore` | `platform_paths.user_data_root() / "reports"` | N/A |
| `UserLocalAuditCacheStore` | `AuditCacheStore` | N/A | `platform_paths.user_cache_root() / "audit-cache"` |

**Not defined**: `UserLocalProjectStateStore` -- FR-009 requires `.project/` stay in-repo. No entry-point registration for `stores.project` at `user-local`.

**Construction contract**:

- `__init__(self, **kwargs)`.
- Accepts and ignores any `root` kwarg the caller might pass (per FR-004: "MUST either be ignored with a warning or rejected with a clear error"). Chosen behavior: **log a warning at info level** and proceed with the platform-computed root. Rationale: less disruptive than an error for operators who accidentally copied a `root` from a `local-fs` example; the warning names the resolved platform path so they can correlate.
- Extra `**kwargs` are otherwise accepted-and-ignored.

**Root resolution**: computed once in `__init__` via a call into `platform_paths` (see E-003). The result is passed to `super().__init__(root=<resolved>)` (extends `LocalFs*Store`), so all downstream logic (sanitizer, delegation, logging) is inherited.

**Logging obligation** (FR-015): same format as E-001, with `<backend>` = `"user-local"`.

---

## E-003: `platform_paths` module

**Purpose**: OS-dispatching path resolution for `user-local`.

**Public API**:

```python
def xdg_data_home() -> Path: ...       # Linux: $XDG_DATA_HOME or ~/.local/share
def xdg_cache_home() -> Path: ...      # Linux: $XDG_CACHE_HOME or ~/.cache
def user_data_root() -> Path: ...      # returns <platform-data-root>/darnit
def user_cache_root() -> Path: ...     # returns <platform-cache-root>/darnit
```

`user_data_root()` and `user_cache_root()` are the only two entry points `UserLocal*Store` calls; `xdg_data_home()` / `xdg_cache_home()` are exported for direct testing.

**Platform dispatch** (inside `user_data_root` / `user_cache_root`):

```python
system = platform.system()   # "Linux" | "Darwin" | "Windows"

# data root
if system == "Darwin":
    return Path.home() / "Library" / "Application Support" / "darnit"
if system == "Windows":
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "darnit" / "Data"
# Linux and unknown: XDG
return xdg_data_home() / "darnit"
```

Analogous for cache root, substituting `Library/Caches`, `LOCALAPPDATA\...\Cache`, and `xdg_cache_home()`.

**Unknown platform** (`platform.system()` returns e.g. `"FreeBSD"`): falls through to the XDG branch (data at `$XDG_DATA_HOME` or `~/.local/share/darnit`, cache at `$XDG_CACHE_HOME` or `~/.cache/darnit`). Documented in the module docstring.

---

## E-004: `root` config field

**Purpose**: the TOML surface. Applies to `local-fs` only. `user-local` reads no config; if the operator writes `root = "..."` on a `[stores.<kind>] backend = "user-local"` block, `UserLocal*Store` logs a warning and ignores it.

**TOML surface**:

```toml
[stores.attestation]
backend = "local-fs"
root = "/absolute/path"      # OR
root = "~/subpath"           # OR
root = "$VAR/subpath"        # OR
root = "~/$VAR/subpath"      # combinations OK; $VAR resolved before ~
```

**Schema-level**: no schema change. Feature 033's `StoreBlock` uses `extra="allow"`, so arbitrary backend-specific keys (like `root`) pass through the config layer verbatim into `_instantiate_plugin`'s kwargs.

**Interpolation order** (per R-003 + E-001):

1. `substitute_dollar_vars(root, missing="raise")`
2. `os.path.expanduser(...)`
3. `Path(...).resolve()`

Steps 1 and 2 both run even if the input contains neither `$` nor `~` (both are no-ops in that case, cheap).

**Absent `root` on `local-fs`**: caller receives `TypeError` from Python (missing required kwarg) -- surfaces to the operator as "TypeError: LocalFsAttestationStore.__init__() missing 1 required argument: 'root'". Feature 033's `_instantiate_plugin` propagates the exception into `StoreOperationError` at the audit boundary, which is the loudest possible signal.

---

## E-005: Info-log format for outside-repo writes

**Purpose**: single, greppable line per write. Satisfies FR-015 and enables SC-009's caplog assertion.

**Log record**:

- Logger name: `darnit.stores.local` (shared across `local-fs` and `user-local`)
- Level: INFO
- Message template: `"wrote %s (%s): %s"` with args `(kind, backend, str(resolved_path))`

Example emitted line:

```
INFO darnit.stores.local: wrote attestation (local-fs): /home/mike/darnit-attestations/acme-widget-baseline-attestation.intoto.json
```

**Zero-config exemption**: `Filesystem*Store` classes are unchanged. They do NOT emit this line. Zero-config audits produce zero log lines from this logger, which is what SC-009 requires.

**Multi-format reports**: `LocalFsReportStore.write_markdown` / `.write_json` / `.write_sarif` each emit one line with `kind = "report:markdown"` / `"report:json"` / `"report:sarif"`. Three-format audit runs yield three log lines.
