## Context

The darnit framework currently uses a TOML schema that has grown organically, with custom fields for each check type (`pass_if_json_path`, `pass_if_json_value`, `file_must_exist`, etc.). This makes extending the framework verbose and inconsistent.

**Current state:**
- Checks defined in `openssf-baseline.toml` with bespoke fields per pass type
- No integration with external project metadata standards
- Context for remediation gathered ad-hoc
- Plugins wired manually via handler references

**Constraints:**
- Must remain TOML-based (human-readable, AI-editable)
- Security-sensitive (plugins run arbitrary code)
- .project/ spec is alpha and evolving

## Goals / Non-Goals

**Goals:**
- Align with CNCF .project/ spec for project metadata
- Simplify policy expressions via CEL
- Formalize context collection flow
- Secure, auto-registering plugin system
- Incremental migration path (4 phases)

**Non-Goals:**
- Full OPA/Rego policy engine (too complex)
- GUI for TOML editing
- Support for non-TOML config formats
- Backward compatibility with pre-1.0 configs (breaking changes acceptable)

## Decisions

### Decision 1: CEL for Policy Expressions

**Choice**: Use CEL (Common Expression Language) for pass/fail conditions

**Rationale**:
- Non-Turing-complete → safe, predictable execution
- Kubernetes ecosystem alignment (ValidatingAdmissionPolicy uses CEL)
- Fast evaluation (nanoseconds to microseconds)
- Good Python support via `celpy`

**Alternatives considered**:
- **CUE**: More powerful but steeper learning curve, better for schema validation than policy
- **Starlark**: Python-like but Turing-complete, harder to sandbox
- **Expr**: Simpler than CEL but less ecosystem adoption
- **Custom DSL**: Maintenance burden, reinventing the wheel

**TODO**: Evaluate alternatives before Phase 3 implementation. CEL is the starting point.

### Decision 2: .project/ as Primary Context Source

**Choice**: Read .project/project.yaml as the authoritative source for project metadata

**Rationale**:
- CNCF standard gaining adoption
- Structured format for maintainers, security contacts, governance
- Extension mechanism (PR #131) allows tool-specific config
- Single source of truth reduces drift

**Implementation**:
```
.project/
├── project.yaml      # Main metadata (CNCF spec)
├── maintainers.yaml  # Maintainer roster
└── extensions/       # Tool-specific configs (future)
    └── darnit.yaml
```

### Decision 3: Write-Back After Remediation

**Choice**: Update .project/ files when remediation creates relevant artifacts

**Rationale**:
- Keep .project/ in sync with actual project state
- E.g., after creating SECURITY.md, update `security.policy.path`
- Reduces manual maintenance

**Implementation**:
- Remediation actions can declare `.project/` updates
- YAML writer preserves comments and formatting where possible
- Changes staged for user review (not auto-committed)

### Decision 4: Plugin Auto-Registration with Signing

**Choice**: Plugins declare capabilities in their package metadata; framework auto-discovers

**Rationale**:
- Reduces boilerplate in TOML configs
- Entry points already used for plugin discovery
- Signing via Sigstore adds trust without key management

**Security model**:
```
[plugins]
# Explicit trust for unsigned plugins
allow_unsigned = false

# Trusted publishers (PyPI attestations)
trusted_publishers = ["openssf", "kusari-oss"]

# Specific plugin versions
[plugins.darnit-baseline]
version = ">=1.0.0"
```

### Decision 5: Phased Rollout

**Choice**: 4 incremental phases, each independently valuable

**Rationale**:
- Reduces risk of big-bang migration
- Earlier phases unblock later phases
- Users can adopt incrementally

**Phase dependencies**:
```
Phase 1 (.project/) ──┬──> Phase 2 (Context)
                      │
                      └──> Phase 3 (CEL) ──> Phase 4 (Plugins)
```

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| .project/ spec changes upstream | Schema drift, broken parsing | Weekly CI check of `types.go` hash; tolerant reader for unknown fields |
| CEL learning curve | User confusion | Good docs, examples, fallback to old syntax during transition |
| Plugin signing adoption | Users may not sign plugins | Allow unsigned with explicit opt-in + warning; sign our own plugins |
| YAML comment preservation | Complex to implement | Use `ruamel.yaml` which preserves comments; accept some edge cases |
| Sigstore availability | Verification failures if service down | Cache verification results; graceful degradation to warning |

## Migration Plan

### Phase 1 → 2 → 3 → 4 Rollout

**Phase 1 (.project/ integration)**:
1. Add .project/ reader module
2. Inject .project/ data into sieve context
3. Add write-back capability to remediation
4. Release as minor version (non-breaking)

**Phase 2 (Context collection)**:
1. Add `[context]` schema to framework_schema.py
2. Implement prompt UI in MCP tools
3. Wire context into remediation variables
4. Release as minor version (non-breaking)

**Phase 3 (CEL expressions)**:
1. Add `celpy` dependency
2. Implement CEL evaluator with sandboxing
3. Add `expr` field to pass schemas
4. Deprecate old fields with warnings
5. Release as major version (breaking)

**Phase 4 (Plugin system)**:
1. Define plugin manifest schema
2. Implement auto-registration from entry points
3. Add Sigstore verification (optional)
4. Migrate darnit-baseline to new system
5. Release as major version (breaking)

### Rollback Strategy

Each phase is independently reversible:
- Phase 1: Remove .project/ reader, context continues from heuristics
- Phase 2: Remove `[context]` section, remediation uses defaults
- Phase 3: Revert to old field syntax (keep both during transition)
- Phase 4: Revert to manual handler wiring

## Open Questions

1. **CEL library choice**: `celpy` vs `cel-python` vs other? Need to evaluate maturity and maintenance status.

2. **Sigstore integration depth**: Full SLSA provenance or just signature verification? Start simple.

3. **.project/ extension namespace**: Should we use `extensions.darnit` or propose a standard `extensions.security-baseline`?

4. **Comment preservation scope**: How much effort to preserve YAML comments? ruamel.yaml handles most cases but edge cases exist.

5. **Upstream tracking automation**: GitHub Action vs Dependabot-style bot for .project/ spec changes?
