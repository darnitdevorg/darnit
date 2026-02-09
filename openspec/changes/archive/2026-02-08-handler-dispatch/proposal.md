## Why

The handler-based dispatch infrastructure (registry, orchestrator dispatch, executor dispatch, backward compatibility) was built in the `toml-schema-improvements` change, but the 350 TOML controls in `openssf-baseline.toml` still use the legacy typed format (`passes.exec = { command = [...] }`, `passes.deterministic = { file_must_exist = [...] }`). The orchestrator falls back to the legacy path for every control because none have `handler_invocations` in their metadata. This means the handler registry, shared handler cache, confidence gradient, and `use_locator` features are unused in practice. Tasks 9.4 and 9.5 from `toml-schema-improvements` were deferred specifically for this change.

## What Changes

- **Convert verification passes to handler format**: Migrate the 145 typed pass blocks across 350 controls from legacy format (e.g., `passes.exec = { command = [...] }`) to handler invocation lists (e.g., `passes.deterministic = [{ handler = "exec", command = [...] }]`)
- **Replace `file_must_exist` with `use_locator = true`**: For the ~15 controls that duplicate their `locator.discover` list in `file_must_exist`, use `use_locator = true` on the handler invocation instead, eliminating the DRY violation
- **Convert remediation configs to handler format**: Migrate remediation sections from typed fields (`file_create = { ... }`) to handler invocation lists where the executor supports it
- **Validate handler dispatch is the primary path**: After migration, verify that the orchestrator uses `_dispatch_handler_invocations()` for all controls and the legacy fallback path is never reached during a full audit
- **Remove legacy dispatch fallback** (optional, if all controls are migrated): Remove the legacy pass execution path from the orchestrator's `verify()` method, leaving only handler dispatch

## Capabilities

### New Capabilities

None — this is a migration of existing controls to use already-implemented infrastructure.

### Modified Capabilities

- `handler-pipeline`: Add requirement that the legacy typed-pass dispatch path SHALL be removed once all controls use handler format (currently the spec only describes the handler path, not the removal of the legacy path)

## Impact

- **Files modified**: `openssf-baseline.toml` (bulk migration of 145 pass blocks + remediation sections), potentially `orchestrator.py` (remove legacy fallback)
- **Tests**: Existing handler dispatch tests and backward compatibility tests cover both paths; need to verify all controls dispatch via handler path after migration
- **Risk**: Medium — bulk TOML changes across 350 controls. Backward compatibility layer means partial migration is safe (mixed old+new format works). Migration can be done incrementally by control level or domain.
- **Breaking**: None if legacy fallback is kept. If removed, any external TOML configs using typed format would need migration.
