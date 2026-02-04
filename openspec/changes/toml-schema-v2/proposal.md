## Why

The current TOML schema has grown organically with custom fields for each check type, making it harder to extend and maintain. We need a more robust, extensible schema that:
1. Aligns with the emerging [CNCF .project/ specification](https://github.com/cncf/automation/tree/main/utilities/dot-project) for project metadata
2. Simplifies policy expressions using an established language (CEL) instead of proliferating custom fields
3. Provides a cleaner plugin registration mechanism
4. Formalizes the context gathering flow for remediations that need user input

## What Changes

This is a significant evolution split into **4 incremental phases**:

### Phase 1: .project/ Integration
- Read and honor `.project/` YAML files following CNCF spec
- Support the [proposed extension mechanism](https://github.com/cncf/automation/pull/131) for tool-specific config
- Map `.project/` sections (security, governance, documentation) to check context
- **Write-back**: Update .project/ files after remediation (e.g., add security.policy path after creating SECURITY.md)
- Fallback chain: `.project/` → heuristic detection (existing behavior)
- **Non-breaking**: Additive capability, existing checks continue to work

### Phase 2: Context Collection
- Formalize `[context]` section for interactive context collection
- Define prompt schemas for user input (e.g., "who are your maintainers?")
- Support pointing to existing files as context sources (e.g., `source = "MAINTAINERS.md"`)
- Context flows into remediation as variables
- **Non-breaking**: New section, opt-in usage

### Phase 3: CEL Expressions
- Add `expr` field for pass/fail conditions using [CEL (Common Expression Language)](https://cel.dev/)
- Support data extraction from command outputs and API responses
- Simplify check definitions: instead of `pass_if_json_path` + `pass_if_json_value`, use `expr = "output.status == 'pass'"`
- **Breaking**: Old fields deprecated, CEL becomes preferred
- **TODO**: Explore CUE, Expr, and other alternatives before finalizing

### Phase 4: Plugin System
- New `[plugins]` section for declaring plugin dependencies
- Plugins auto-register their handlers, templates, and passes when loaded
- Secure by default: whitelist-based module loading, no arbitrary code paths
- **Breaking**: New plugin declaration syntax

## Security Considerations

The plugin system inherently runs code, so we minimize attack surface:

| Risk | Mitigation |
|------|------------|
| Arbitrary code execution | Whitelist allowed module prefixes (`darnit.`, `darnit_baseline.`, registered entry points) |
| Path traversal | Validate all file paths are within repo root |
| Command injection | Commands executed as arrays, not shell strings; no user-controlled interpolation |
| Malicious plugins | Explore Sigstore signing; unsigned plugins require explicit opt-in with warning |
| CEL injection | CEL is non-Turing-complete and sandboxed; no filesystem/network access |
| .project/ write-back | Only write to .project/ files, validate YAML structure, preserve comments where possible |

**Documentation requirements:**
- Clear warning that plugins execute arbitrary code
- Guidance on vetting third-party plugins
- Security model explanation in framework docs

## Capabilities

### New Capabilities
- `dot-project-integration`: Reading and using .project/ metadata as check context (Phase 1)
- `context-collection`: Interactive context gathering with user prompts and file sources (Phase 2)
- `cel-expressions`: CEL-based policy expressions for check pass/fail conditions (Phase 3)
- `plugin-registry`: Declarative plugin registration and auto-discovery (Phase 4)

### Modified Capabilities
- `framework-design`: Schema changes to `[controls]`, new `[plugins]` and `[context]` sections, CEL expression support in passes

## Impact

### Code Changes (by phase)

**Phase 1:**
- New: `packages/darnit/src/darnit/context/dot_project.py` - .project/ parser
- Modify: `packages/darnit/src/darnit/sieve/orchestrator.py` - inject .project/ context

**Phase 2:**
- New: `packages/darnit/src/darnit/context/collection.py` - context prompts
- Modify: `packages/darnit/src/darnit/config/framework_schema.py` - `[context]` schema

**Phase 3:**
- New: `packages/darnit/src/darnit/sieve/cel_evaluator.py` - CEL evaluation
- Modify: `packages/darnit/src/darnit/sieve/passes.py` - CEL expression support
- Modify: `packages/darnit/src/darnit/config/framework_schema.py` - `expr` field

**Phase 4:**
- Modify: `packages/darnit/src/darnit/core/plugin.py` - auto-registration
- Modify: `packages/darnit/src/darnit/config/framework_schema.py` - `[plugins]` schema

### Dependencies
- Phase 1: `pyyaml` (likely already present)
- Phase 3: `cel-python` or `celpy` for CEL evaluation

### Migration
- Phases 1-2: No migration needed (additive)
- Phases 3-4: Deprecation warnings, then removal in next major version

## Open Questions

- **CEL alternatives**: Before Phase 3 implementation, evaluate CUE, Expr, Starlark as alternatives. CEL chosen initially for Kubernetes ecosystem alignment and safety guarantees.
- **.project/ spec compliance**:
  - Implement strict compliance with CNCF .project/ spec, not a loose interpretation
  - Add CI job to periodically check upstream [cncf/automation](https://github.com/cncf/automation/tree/main/utilities/dot-project) for schema changes
  - Subscribe to/watch the repo for updates; consider GitHub Actions workflow that checks `types.go` hash weekly
  - Reader should be tolerant of unknown fields (forward compatibility) but validate known fields strictly
  - Document which spec version we target and maintain a compatibility matrix
- **Plugin signing**: Explore [Sigstore](https://www.sigstore.dev/) for plugin signature verification. Options to investigate:
  - `sigstore-python` for verifying plugin signatures
  - Keyless signing via Fulcio (no key management burden)
  - Rekor transparency log for audit trail
  - Integration with PyPI trusted publishing
  - Fallback: allow unsigned plugins with explicit user opt-in and warning
