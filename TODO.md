# Darnit Future Work

This document tracks future enhancements and design work needed.

## Global Configuration System

**Status**: Design needed
**Priority**: Medium
**Context**: Currently, configuration is per-repository via `.baseline.toml`. We need a more flexible system.

### Problem Statement

Users need the ability to:
1. **Compose multiple configs** - Point to multiple darnit config sources that get merged
2. **Use local shared configs** - Reference files like `.darnit-baseline.toml` from a parent directory or shared location
3. **Use remote config servers** - Fetch configs from a central server (enterprise use case)
4. **Layer configs** - Organization defaults → Team overrides → Project-specific

### Use Cases

1. **Enterprise Central Policy**
   ```toml
   # .baseline.toml
   extends = [
       "https://config.company.com/darnit/security-policy.toml",
       "https://config.company.com/darnit/team-backend.toml",
       "openssf-baseline",
   ]
   ```

2. **Monorepo Shared Config**
   ```toml
   # packages/my-service/.baseline.toml
   extends = [
       "../../.darnit-shared.toml",
       "openssf-baseline",
   ]
   ```

3. **Config Inheritance Chain**
   ```
   org-policy.toml (remote server)
       └── team-policy.toml (remote server)
           └── .baseline.toml (local repo)
   ```

### Design Considerations

- **Merge strategy**: How do arrays merge? Last-wins? Append? Explicit merge operators?
- **Security**: Remote configs could inject malicious trusted_publishers or adapters
- **Caching**: How long to cache remote configs? Offline fallback?
- **Versioning**: Pin remote config versions? `extends = "https://...@v1.2.0"`?
- **Authentication**: How to auth to private config servers?
- **Validation**: Validate remote configs before merging?

### Related Work

- Kubernetes: ConfigMaps, Kustomize overlays
- ESLint: `extends` with npm packages and file paths
- Prettier: Config cascade (package.json → .prettierrc → CLI)
- Terraform: Module sources (local, git, registry, HTTP)

### Tasks (to be created)

- [ ] Design RFC for global config system
- [ ] Prototype `extends` with local file paths
- [ ] Prototype `extends` with remote URLs
- [ ] Define merge semantics for config layering
- [ ] Security review for remote config loading
- [ ] Implement caching strategy for remote configs

---

## Other Future Work

<!-- Add other TODO items here as they come up -->
