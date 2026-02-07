## Why

No working, installable example exists that uses the modern `ComplianceImplementation` protocol. The existing examples all use outdated patterns: `darnit-testchecks` uses old adapter entry points, `docs/examples/python-framework/` redefines its own `CheckResult` and isn't installable, and `docs/examples/declarative-framework/` is pure TOML with no package structure. The recently written `docs/IMPLEMENTATION_GUIDE.md` teaches the modern pattern using a hypothetical "darnit-mystandard", but there's nothing to validate that the guide is actually followable. A real, minimal implementation would both validate the guide and serve as a copy-paste starting point for plugin authors.

## What Changes

- Add new `packages/darnit-example/` workspace package implementing a "Project Hygiene Standard" with 8 controls across 2 levels
- Define 6 TOML-only controls and 2 Python controls demonstrating the factory function pattern, custom analyzers, and glob matching
- Include remediation actions, handler registration, and a full test suite
- Add `"darnit_example."` to `ALLOWED_MODULE_PREFIXES` in the framework's handler registry
- Add the package to root `pyproject.toml` workspace sources and ruff isort config
- Update `docs/IMPLEMENTATION_GUIDE.md` to reference `darnit-example` as a companion example

## Capabilities

### New Capabilities
- `example-plugin`: A minimal, installable darnit implementation package demonstrating TOML controls, Python controls, remediation, handler registration, and testing

### Modified Capabilities

_(none — no existing spec-level requirements change)_

## Impact

- **New package**: `packages/darnit-example/` with entry points `darnit.implementations` and `darnit.frameworks`
- **Framework change**: `packages/darnit/src/darnit/core/handlers.py` — one line added to `ALLOWED_MODULE_PREFIXES`
- **Root config**: `pyproject.toml` — workspace source and ruff isort additions
- **Documentation**: `docs/IMPLEMENTATION_GUIDE.md` — callout box and key-file-paths table updates
- **Tests**: `tests/darnit_example/` — new test directory (no existing tests affected)
