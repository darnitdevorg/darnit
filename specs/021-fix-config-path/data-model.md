# Phase 1 Data Model: Framework config loading works under wheel install

**Feature**: 021-fix-config-path
**Date**: 2026-08-04

This feature is a packaging + resolver bug fix. No data structures are added, and no existing data structures change shape. Only one contract is touched:

## `ComplianceImplementation.get_framework_config_path()`

**Location:** `packages/darnit/src/darnit/core/plugin.py` (protocol definition).

**Signature (unchanged):**

```python
def get_framework_config_path(self) -> Path | None: ...
```

**Semantics before this fix:**

- Returns a `Path` computed from `__file__` via three `.parent` walks.
- The returned `Path` may not exist on disk under wheel installs; callers hit `FileNotFoundError` when attempting to read it.

**Semantics after this fix:**

- Returns a `Path` computed via `importlib.resources.files(__package__)`.
- The returned `Path` MUST exist and MUST be readable, whether the package was installed editable or from a wheel.
- If the TOML is missing from the installed package (a broken build), the implementation SHOULD raise a clear error naming which implementation's TOML is missing, rather than returning a `Path` that will later fail with a generic `FileNotFoundError`.

**Return-type extension: not needed.** Every consumer of `get_framework_config_path()` today treats the return value as a filesystem `Path`. The `importlib.resources.files()` result can be safely coerced to a `Path` for filesystem-backed installs (the only supported install channel today), so the protocol return type stays `Path | None`. No callers need to change.

## Related entry-point contract

The `darnit.frameworks` entry point (registered in each implementation's `pyproject.toml`) exports a module-level `get_framework_path()` function that delegates to `implementation.get_framework_config_path()`. Both must return the corrected path. This delegation is preserved as-is; only the underlying `get_framework_config_path()` method body changes.

## No new entities

No new pydantic models, TypedDicts, dataclasses, protocols, or TOML schema fields are introduced by this fix.
