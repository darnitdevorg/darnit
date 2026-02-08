## Why

The remediation system has two parallel dispatch paths: TOML declarative (file_create, exec, api_call, manual) and legacy Python functions in `actions.py` dispatched via `func_map`/`REMEDIATION_REGISTRY`. This duplication creates confusion about which path runs, makes it hard to add new remediations (contributors must understand both systems), and the legacy functions embed file templates as Python string literals instead of using the declarative template system. Now that the TOML declarative remediation infrastructure is mature and 74% of controls already have TOML remediation defined, it's time to migrate the remaining legacy categories and remove the fallback path entirely.

## What Changes

- **Migrate 7 remaining controls to TOML declarative remediation**: 5 controls still have `handler = "legacy_func"` references (GV-01.01, GV-04.01, QA-07.01, VM-04.02, DO-03.01) and 2 have no remediation section at all (GV-01.02, GV-03.02). Add `file_create` or `manual` TOML remediation so they no longer fall through to legacy Python. 5 other controls already have working TOML remediation but carry dead `handler` references that need cleanup.
- **Add 5 missing templates**: CODEOWNERS, GOVERNANCE.md, MAINTAINERS.md, SUPPORT.md, and VEX policy section templates. Other templates (SECURITY.md, CONTRIBUTING.md, bug report, dependabot, branch protection) already exist in `[templates]`.
- **Delete `actions.py`**: Remove the ~1,380-line file containing 11 legacy remediation functions and their helpers
- **Delete `REMEDIATION_REGISTRY`**: Remove `registry.py` with its category-to-function mapping and helper functions
- **Remove legacy dispatch path from orchestrator**: Delete `func_map`, `_apply_legacy_remediation()`, and the legacy fallthrough branch in the main dispatch loop
- **Simplify orchestrator imports**: Remove the 12 lines of function imports from `actions.py`
- **BREAKING**: The `status_checks` registry category (function `configure_status_checks`) is removed — it was never implemented and was already converted to manual guidance in TOML

## Capabilities

### New Capabilities

- `declarative-file-templates`: TOML-based file creation templates for all governance, security, and CI config files (SECURITY.md, CONTRIBUTING.md, CODEOWNERS, GOVERNANCE.md, MAINTAINERS.md, SUPPORT.md, dependabot.yml, bug_report.md) using `${context.*}` and `${project.*}` template variables

### Modified Capabilities

- `remediation-manual-guidance`: Extends existing spec to cover DCO enforcement (previously a Python function, now manual steps) and branch protection API call remediation

## Impact

- **Code removed**: ~1,800 lines across `actions.py`, `registry.py`, and orchestrator legacy path
- **Files deleted**: `packages/darnit-baseline/src/darnit_baseline/remediation/actions.py`, `packages/darnit-baseline/src/darnit_baseline/remediation/registry.py`
- **Files modified**: `orchestrator.py` (remove legacy path), `openssf-baseline.toml` (add file_create templates), `__init__.py` (remove exports)
- **Tests**: Tests referencing legacy functions or registry need updating; new tests for TOML template rendering
- **Breaking**: Any external code calling `REMEDIATION_REGISTRY` or importing from `actions.py` directly will break. The MCP tool API (`remediate_audit_findings`) is unchanged.
