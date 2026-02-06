## Context

The darnit framework evolved through several phases: legacy Python check functions → TOML-first declarative controls → CNCF-standard project config. Each transition left behind compatibility shims. A codebase-wide audit using static analysis (grep for imports, call sites, entry points) identified three files that are provably dead — zero importers, zero callers — and one obsolete script with a direct replacement.

**Current dependency graph for the targets:**

```
config/models.py  ←── config/__init__.py (re-exports legacy classes)
                  ←── config/validation.py (uses ReferenceStatus, ResourceReference)
                  ←── remediation/executor.py (imports ProjectConfig — lives in schema.py)
                  ←── attestation/predicate.py (imports ProjectConfig — lives in schema.py)

config/validation.py  ←── (nothing — zero importers)

scripts/create-test-repo.sh  ←── (nothing — replaced by create-example-test-repo.py)
```

The key insight: `validation.py` is the sole consumer of the legacy classes (`ReferenceStatus`, `ResourceReference`) in `models.py`. Since `validation.py` itself is dead code, removing it first makes `models.py` trivially removable after migrating 2 `ProjectConfig` imports.

## Goals / Non-Goals

**Goals:**
- Remove 3 files containing ~300 lines of dead/deprecated code
- Migrate 2 `ProjectConfig` imports from `models` → `schema`
- Remove legacy class re-exports from the `config` package public API
- Fix stale documentation import example

**Non-Goals:**
- Removing `rules/catalog.py` (still has 6 active import sites — separate migration)
- Migrating the `checks/` directory (confirmed to be active runtime code)
- Removing any backward-compatibility code that is still reachable
- Changing any runtime behavior

## Decisions

### 1. Remove `validation.py` before `models.py`

**Decision**: Delete `validation.py` first, then `models.py`.

**Rationale**: `validation.py` is the only consumer of the `ReferenceStatus` and `ResourceReference` legacy classes. Removing it first eliminates the only blocker for `models.py` removal. If we tried to remove `models.py` first, we'd need to migrate `validation.py` to use new types — wasted effort for a dead module.

### 2. Migrate imports to `darnit.config.schema`, not `darnit.config`

**Decision**: Change `from darnit.config.models import ProjectConfig` → `from darnit.config.schema import ProjectConfig`.

**Alternative considered**: Import from `darnit.config` (the package `__init__.py` re-exports `ProjectConfig` from schema). Rejected because both import sites are in `TYPE_CHECKING` blocks where explicit module paths are clearer and avoid loading the full `config` package for type annotations.

### 3. Remove legacy classes from `config/__init__.py` re-exports

**Decision**: Remove the `ControlStatus`, `ReferenceStatus`, `ResourceReference` imports from `config/__init__.py` lines 121-126.

**Rationale**: These are the deprecated re-exports. With `models.py` deleted, these imports would error anyway. Removing them makes the breaking change explicit and clean.

### 4. Delete the bash script without adding redirects

**Decision**: Simply delete `scripts/create-test-repo.sh`.

**Rationale**: The Python replacement (`create-example-test-repo.py`) has been in place since the project restructuring. No docs or code reference the bash version. No redirect or deprecation notice needed.

## Risks / Trade-offs

**[Breaking change for external consumers of legacy classes]** → Low risk. `ReferenceStatus`, `ResourceReference`, and `ControlStatus` have emitted `DeprecationWarning` since introduction. They exist only in the `darnit.config.models` and `darnit.config` namespaces. No known external consumers. Darnit is pre-1.0 with no stability guarantees.

**[Accidental removal of reachable code]** → Mitigated by static analysis verification. Every target was confirmed to have zero importers via `grep -r` across the full codebase. Post-removal test suite run provides additional safety net.
