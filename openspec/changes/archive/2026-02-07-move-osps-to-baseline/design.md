## Context

The darnit framework (`packages/darnit/`) contains OSPS/OpenSSF-Baseline-specific code in multiple locations:

1. **`tools/audit.py`** — `format_results_markdown()` hardcodes "OpenSSF Baseline Audit Report" title and OSPS control-ID-to-tool mappings (lines 573-758)
2. **`attestation/`** — Entire module (~4 files) is OpenSSF Baseline specific: predicate type URIs, assessor names, specification URLs
3. **`threat_model/`** — Entire module (~6 files, 2027 LOC) generates OpenSSF-flavored threat models
4. **`server/tools/git_operations.py`** — Default branch name `fix/openssf-baseline-compliance`, hardcoded URLs
5. **`core/discovery.py`** — `get_default_implementation()` hardcodes preference for "openssf-baseline"
6. **`config/schema.py`, `config/context_storage.py`, `config/loader.py`** — Hardcoded `x-openssf-baseline` extension key

All of this violates the architectural rule: framework must not import or hardcode implementation specifics.

### Current tool handler architecture

darnit-baseline's `tools.py` already defines ALL MCP tool handler functions and registers them via `register_handlers()`. For `generate_attestation` and `generate_threat_model`, the handler functions import from `darnit.attestation` and `darnit.threat_model` respectively. Moving the modules means the imports change to `darnit_baseline.attestation` and `darnit_baseline.threat_model`.

## Goals / Non-Goals

**Goals:**
- Remove all OSPS-specific string literals, control IDs, and URLs from `packages/darnit/`
- Move `attestation/` and `threat_model/` modules to `packages/darnit-baseline/`
- Parameterize `format_results_markdown()` so implementations control branding and remediation maps
- Make `get_default_implementation()` implementation-agnostic
- Change git operations defaults to generic values

**Non-Goals:**
- Refactoring the `x-openssf-baseline` config extension system — this is deeply structural (schema.py, context_storage.py, loader.py, project_context.py, sieve/project_context.py) and requires a separate change to make the extension key dynamic based on the active implementation. Defer to a follow-up change.
- Adding a formal "framework metadata" protocol method — the existing `display_name`, `spec_version` properties already provide what's needed.
- Changing the MCP tool names visible to end users — `audit_openssf_baseline` and other tool names stay the same.

## Decisions

### D1: Move attestation/ and threat_model/ wholesale to darnit-baseline

**Decision:** Move both modules from `packages/darnit/src/darnit/` to `packages/darnit-baseline/src/darnit_baseline/`.

**Rationale:** Both modules are entirely OpenSSF Baseline specific. The attestation module builds predicates with hardcoded OSPS URIs, and the threat model generates reports referencing OpenSSF Baseline controls. Neither has any framework-generic value.

**Alternative considered:** Make them configurable via protocol methods. Rejected because they have zero reuse potential — a different compliance framework would need completely different attestation predicates and threat model patterns.

**Impact:** The tool handler functions in `darnit_baseline/tools.py` already call these modules — only import paths change. Tests in `tests/darnit/` for these modules move to `tests/darnit_baseline/`.

### D2: Parameterize format_results_markdown()

**Decision:** Add `report_title: str = "Compliance Audit Report"` and `remediation_map: dict | None = None` parameters.

**Rationale:** The function is framework-generic (formats any sieve results into markdown) except for two things: the H1 title and the control-ID-to-tool mapping section. Making these parameters removes all OSPS specifics while preserving the report structure.

**remediation_map structure:**
```python
remediation_map = {
    "groups": [
        {
            "name": "Branch Protection",
            "tool": "enable_branch_protection",
            "description": "Configure branch protection rules",
            "control_ids": {"OSPS-AC-03.01", "OSPS-AC-03.02", "OSPS-QA-07.01"},
        },
        {
            "name": "Security Policy",
            "tool": "create_security_policy",
            "description": "Generate SECURITY.md",
            "control_ids": {"OSPS-VM-01.01", "OSPS-VM-02.01", "OSPS-VM-03.01"},
        },
    ],
    "bulk_tool": "remediate_audit_findings",
    "bulk_description": "Auto-fix multiple compliance issues at once",
    "branch_name": "fix/openssf-baseline",
    "framework_name": "OpenSSF Baseline",
}
```

The darnit-baseline `tools.py` will define this map and pass it when calling `format_results_markdown()`.

### D3: Remove implementation preference from get_default_implementation()

**Decision:** Remove the `if "openssf-baseline" in implementations` preference. Return the first discovered implementation (alphabetical by entry point name, which is deterministic).

**Rationale:** A generic framework should not prefer one implementation over another. With only one implementation installed, the first-found behavior is identical. If multiple are installed, the user should specify which one explicitly.

### D4: Change git operation defaults to generic values

**Decision:** Change default branch name from `fix/openssf-baseline-compliance` to `fix/compliance`. Remove hardcoded OpenSSF URLs from docstrings and report templates.

**Rationale:** The defaults should work for any implementation. darnit-baseline's TOML-registered tool can override the branch name default by wrapping the function.

### D5: Defer x-openssf-baseline config extension refactoring

**Decision:** Do not change the `x-openssf-baseline` extension key system in this change.

**Rationale:** This touches schema.py (Pydantic models), context_storage.py (load/save), loader.py (schema key), project_context.py, and sieve/project_context.py — a deeply interconnected system. Making the extension key dynamic requires a new protocol method and careful migration. It works correctly today; it's just poorly named. File as a separate change.

## Risks / Trade-offs

- **[Risk: Test breakage from module moves]** → Tests that import from `darnit.attestation` or `darnit.threat_model` will fail. Mitigation: Move corresponding test files and update imports in the same commit.
- **[Risk: Stale imports in third-party code]** → Anyone importing `from darnit.attestation import ...` will break. Mitigation: This is an internal module with no external users. The MCP tool interface (tool names, parameters) does not change.
- **[Trade-off: Deferred config extension rename]** → `x-openssf-baseline` remains hardcoded in the framework for now. This is cosmetic — it doesn't affect functionality, just naming.

## Open Questions

None — all major decisions are resolved. The config extension rename is deferred to a follow-up change.
