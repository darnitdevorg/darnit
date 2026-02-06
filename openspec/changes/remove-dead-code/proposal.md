## Why

The codebase has accumulated dead modules, deprecated compatibility shims, and obsolete scripts as the architecture evolved from Python-first to TOML-first. A deep audit found concrete targets: modules never imported anywhere, scripts fully replaced by newer versions, and deprecated shims whose only consumers are themselves dead code. Removing them reduces maintenance burden, eliminates confusion about what's current, and shrinks the codebase.

## What Changes

- **Remove `scripts/create-test-repo.sh`**: Obsolete bash script fully replaced by `scripts/create-example-test-repo.py`. The Python version is referenced in docs and tests; the bash version is not.
- **Remove `packages/darnit/src/darnit/config/validation.py`**: Dead module — never imported anywhere in the codebase. Defines reference validation functions (`validate_local_reference`, `validate_url_reference`, `validate_repo_reference`) that are never called.
- **Remove `packages/darnit/src/darnit/config/models.py`**: Deprecated re-export shim. With `validation.py` removed, only 2 production files still import from it (`executor.py`, `predicate.py`) — both importing `ProjectConfig` which lives in `schema.py`. Migrate those imports, remove the legacy class re-exports from `config/__init__.py`, then delete the file. **BREAKING**: External code importing `ReferenceStatus`, `ResourceReference`, or `ControlStatus` from `darnit.config.models` or `darnit.config` will break. These classes have had deprecation warnings since introduction.
- **Update `docs/FRAMEWORK_DESIGN.md`**: Fix import example that references `config.models` → `config.schema`.

### Explicitly NOT removing (confirmed still in use)

- `rules/catalog.py` — Deprecated but actively used in 6 import sites. Requires separate TOML-only migration.
- `checks/` directory — Runtime implementations, NOT legacy despite misleading labels.
- `checks/helpers.py` — Convenience re-exports used within the checks package.
- Legacy result conversion functions — Active backward compatibility.
- `darnit-example/` package — Intentional reference implementation.
- `ENTRY_POINT_IMPLEMENTATIONS` constant — Still used by discovery.py.

## Capabilities

### New Capabilities

None. This is a pure removal/cleanup change.

### Modified Capabilities

None. No spec-level behavior changes — only removing code that is never reached.

## Impact

- **Deleted files** (3): `scripts/create-test-repo.sh`, `config/validation.py`, `config/models.py`
- **Edited files** (3): `remediation/executor.py`, `attestation/predicate.py`, `config/__init__.py`
- **Docs** (1): `FRAMEWORK_DESIGN.md` import example update
- **Breaking**: `ReferenceStatus`, `ResourceReference`, `ControlStatus` removed from public API (already emitting deprecation warnings)
- **No behavioral changes**: All removed code is unreachable
