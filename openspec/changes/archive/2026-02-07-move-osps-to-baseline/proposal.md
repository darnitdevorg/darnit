## Why

The darnit framework package (`packages/darnit/`) contains hardcoded OSPS control IDs, OpenSSF Baseline URLs, predicate types, and report branding scattered across 10+ files. This violates the core architectural rule that the framework must be implementation-agnostic — all compliance-framework-specific code belongs in the implementation package (`packages/darnit-baseline/`). Until this is fixed, no second compliance implementation can be plugged in without modifying framework internals.

## What Changes

- **Parameterize audit report formatting** — `format_results_markdown()` in `tools/audit.py` gains `report_title` and `remediation_map` parameters instead of hardcoding "OpenSSF Baseline Audit Report" and OSPS control-to-tool mappings. The OSPS-specific mappings move to `darnit-baseline`.
- **Move attestation module to darnit-baseline** — The `attestation/` package (predicate builder, generator, signing) is entirely OpenSSF Baseline specific. Move it to `darnit_baseline/attestation/` and have darnit-baseline's MCP tools call it directly.
- **Move threat model module to darnit-baseline** — The `threat_model/` package (STRIDE analysis, pattern library) generates OpenSSF Baseline-flavored threat models. Move it to `darnit_baseline/threat_model/`.
- **Move attestation and threat-model MCP tool handlers to darnit-baseline** — The `server/tools/` handlers for `generate_attestation`, `generate_threat_model` are wrappers around the moved modules. Register them as plugin-provided MCP tools via `register_handlers()`.
- **Parameterize git operations defaults** — `git_operations.py` branch names and URLs become parameters sourced from the active implementation rather than hardcoding "openssf-baseline".
- **Parameterize config extension key** — `x-openssf-baseline` in schema.py/context_storage.py/loader.py becomes derived from the active implementation's `name` property.
- **Clean up framework defaults** — CLI default framework, discovery preference, and docstring examples use generic phrasing instead of hardcoding "openssf-baseline".

## Capabilities

### New Capabilities
- `framework-agnostic-reporting`: Audit report formatting accepts implementation-provided branding and remediation mappings instead of hardcoding OSPS specifics.
- `implementation-provided-tools`: Attestation and threat model MCP tools are registered by the implementation plugin rather than built into the framework.

### Modified Capabilities
- `framework-design`: Section 10 (Audit Pipeline) updated to require report formatter parameterization. New section on implementation-provided MCP tools.

## Impact

- **packages/darnit/** — ~10 files modified (tools/audit.py, attestation/ moved out, threat_model/ moved out, server/tools/ handlers moved, config/schema.py, config/context_storage.py, config/loader.py, cli.py, core/discovery.py, server/tools/git_operations.py)
- **packages/darnit-baseline/** — Gains attestation/, threat_model/, and MCP tool handlers. tools.py updated to pass OSPS-specific mappings to framework formatter.
- **Tests** — Tests for attestation and threat_model move to `tests/darnit_baseline/`. Framework-level audit tests updated for parameterized API.
- **No breaking changes to MCP tool interface** — End users see the same tool names and parameters. The change is internal plumbing.
