# Contract: `local-fs` backend

**Backend name (TOML)**: `local-fs`
**Registered under**: `darnit.stores.attestation`, `darnit.stores.report`, `darnit.stores.cache`, `darnit.stores.project` (see FR-009 note below)
**Config surface**: `[stores.<kind>]` block in `.baseline.toml`

## TOML surface

```toml
[stores.<kind>]
backend = "local-fs"
root    = "<path>"              # REQUIRED. Absolute, ~-relative, or $VAR-templated.
```

- `root` MUST be a non-empty string.
- Any additional keys are accepted-and-ignored (extra="allow" per feature 033).

## Root resolution (E-001, R-003)

Applied in `__init__`, in order:

1. `substitute_dollar_vars(root, missing="raise")` -- typo in `$VAR` name is a hard error, not a silent empty.
2. `os.path.expanduser(...)` -- `~` and `~user` expand to the running user's home directory.
3. `Path(...).resolve()` -- final absolute canonical path used for I/O and logging.

Directory creation is deferred to first write (matches feature 033's `FilesystemAttestationStore.write`).

## Per-kind behavior

| Kind | Class | Delegate |
|---|---|---|
| attestation | `LocalFsAttestationStore` | `FilesystemAttestationStore(root=<resolved>)` |
| report | `LocalFsReportStore` | `FilesystemReportStore(root=<resolved>)` |
| cache | `LocalFsAuditCacheStore` | `FilesystemAuditCacheStore(root=<resolved>)` |
| project | `LocalFsProjectStateStore` | Uses `<resolved>/.project/` layout inside `root`; see below |

### `project` kind (FR-009 note)

`local-fs` MAY be selected for `[stores.project]`, but doing so is documented as unusual. The `.project/project.yaml` file is the CNCF `.project/` spec's canonical repo-committable artifact. Redirecting it outside the repo means downstream consumers (governance dashboards, other darnit-adjacent tools) can no longer find it via the repo path.

If an operator explicitly configures `[stores.project] backend = "local-fs" root = "<path>"`, the store writes `<root>/project.yaml` and `<root>/maintainers.yaml` (NO `.project/` subdirectory prefix -- the `<root>` IS the `.project/` equivalent). Documentation in `docs/plugin-authoring/stores.md` covers this.

`user-local` is deliberately not registered for `[stores.project]`.

## Write contract (per Protocol)

Unchanged from feature 033's `Filesystem*Store`. Every method delegates to the underlying `Filesystem*Store` after the info-log line (see below).

- `AttestationStore.write(bundle_id, bundle_bytes, content_type)`:
  - Path: `<resolved-root>/<sanitize(bundle_id)><ext>` where `<ext>` maps from `content_type` via the existing `_CONTENT_TYPE_TO_EXT` table (`in-toto+json` -> `.intoto.json`, `sigstore.bundle+json` -> `.sigstore.json`, else `.bin`).
  - Errors: OSError, PermissionError propagate to the audit driver -> `StoreOperationError`.
- `ReportStore.write_markdown(report_id, contents)` / `.write_json` / `.write_sarif`:
  - Paths: `<resolved-root>/<sanitize(report_id)>.md` / `.json` / `.sarif`.
  - Errors: same propagation.
- `AuditCacheStore.read(cache_key) -> dict | None`: returns None on miss, corrupt JSON, or OSError (feature 033 FR-011: best-effort).
- `AuditCacheStore.write(cache_key, envelope)`: tempfile-then-rename (same directory as target, cross-fs safe). Best-effort -- swallows all exceptions to a debug log.
- `close()`: no-op.

## Sanitization (SC-005)

All identifiers passed as filename components (`bundle_id`, `report_id`, `cache_key`) go through the shared `_sanitize_filename` regex from `stores/defaults/attestation.py`:

```
_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9._+@-]")
_sanitize_filename(x) = _FILENAME_UNSAFE.sub("_", x) or "unnamed"
```

Consequence: `bundle_id = "../../etc/foo"` produces a filename `.._.._etc_foo.intoto.json` INSIDE `<resolved-root>`. Path traversal is impossible by construction.

## Logging (FR-015 / SC-009)

Every successful write emits one info-level log line to logger `darnit.stores.local`:

```
INFO wrote <kind-tag> (local-fs): <resolved-absolute-path>
```

- `<kind-tag>`: `"attestation"`, `"report:markdown"` | `"report:json"` | `"report:sarif"`, or `"cache"`.
- `<resolved-absolute-path>`: the full absolute path after sanitization and content-type-to-extension mapping. This is the exact path the file lives at.

Failed writes do NOT emit this line (the OSError propagation is the failure signal). Cache best-effort failures emit a debug-level line only (already existing).

## Error modes (recap of feature 033 Protocol contracts)

| Protocol | Error condition | Behavior |
|---|---|---|
| `AttestationStore` | Directory unwritable, disk full | Raises `OSError` -> `StoreOperationError` -> operator sees clear message naming backend + kind + path (SC-008) |
| `ReportStore` | Same | Same |
| `AuditCacheStore` | Same | Best-effort: swallow to debug log; read returns None; audit continues |
| `ProjectStateStore` | Same on read/write | Propagates; affected controls resolve WARN |

## Test surface

- `tests/darnit/stores/test_local_fs_backend.py`: per-kind write round-trip, `$VAR` interpolation (present + missing = raise), `~` expansion, path-traversal sanitization (SC-005), cross-filesystem `root` (uses `tmp_path` on the test's temp filesystem which may differ from `/tmp`).
- `tests/darnit/stores/test_local_fs_logging.py`: caplog assertion on each write (SC-009), zero-log assertion for `Filesystem*Store` writes.
- `tests/darnit/stores/test_local_fs_isolation.py`: `[stores.attestation] backend = "local-fs"` + others unset -> only attestation redirects (SC-007).

## Non-scope

- No retention/pruning inside `root`. Operator manages it.
- No cross-filesystem atomic-write for `AttestationStore`/`ReportStore` (only `AuditCacheStore` needs it, and R-004 confirms it's handled).
- No encryption at rest.
