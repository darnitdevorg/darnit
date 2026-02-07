## Context

The darnit remediation system has a clean TOML-first architecture: controls declare remediation blocks with typed actions (`file_create`, `exec`, `api_call`, `project_update`), and the executor in `packages/darnit/src/darnit/remediation/executor.py` dispatches based on which type is present. Legacy Python handlers exist as a fallback via the `handler` field.

**Current state**: Of 62 OSPS controls, only 12 (~19%) have any remediation path. The remaining 50 controls produce `FAIL` results with no guidance on what to do next. This creates two problems:

1. **AI confusion**: The MCP-based AI doesn't know whether a missing remediation means "not yet implemented" vs "not possible to automate." It may attempt ad-hoc fixes or report inability when structured guidance would suffice.

2. **User dead-ends**: Running `remediate_audit_findings` skips controls silently if they lack a remediation block, giving no indication of what manual steps are needed.

**Constraints**:
- Framework package (`packages/darnit/`) must not import implementation packages
- All new remediation types must be declarative (TOML-defined), not Python-only
- Backward compatibility: existing remediations must continue working unchanged
- The `RemediationConfig` schema uses `model_config = ConfigDict(extra="allow")`, so new fields don't break parsing of existing configs

## Goals / Non-Goals

**Goals:**
- Add a `manual` remediation type to the framework that surfaces structured human guidance
- Add `file_create` remediations for 4-5 controls where the fix is "create a file from a template"
- Fix `generate_threat_model` to optionally write files to disk
- Implement `configure_status_checks` (referenced in registry but never defined)
- Improve `file_create` messaging when the target file already exists
- Make the remediation coverage gap visible and incrementally fixable

**Non-Goals:**
- Automating controls that require org-admin access (MFA, workflow permissions)
- Automating controls that require project-specific knowledge (which tests to run, what license to choose)
- Building a comprehensive template library — start with minimal useful templates
- Changing the sieve/checking architecture — this is remediation-only
- Replacing the legacy Python handler system (it will continue to work alongside declarative types)

## Decisions

### D1: `manual` is a new remediation type, not a special status

**Decision**: Add `manual` as a new field on `RemediationConfig` alongside `file_create`, `exec`, and `api_call`. It holds structured guidance (steps, docs URL, context hints) and the executor returns it as a successful "informational" result rather than executing any action.

**Alternatives considered**:
- *Use TOML comments*: Not machine-readable, AI can't surface them
- *Use a separate "guidance" file*: Splits remediation info across two locations
- *Mark controls as N/A*: Wrong — the control applies, it just can't be automated yet

**Rationale**: Treating `manual` as a first-class type means the executor, MCP tools, and AI all handle it consistently. The orchestrator can distinguish "no remediation configured" from "manual steps documented" and surface appropriate guidance.

### D2: `ManualRemediationConfig` schema mirrors `ManualPassConfig`

**Decision**: The new config model:

```python
class ManualRemediationConfig(BaseModel):
    steps: list[str]        # Ordered human-readable steps
    docs_url: str | None    # Link to relevant documentation
    context_hints: list[str] = []  # Context keys that would enable future automation
```

This parallels `ManualPassConfig` (which has `steps` and `docs_url`) to maintain consistency across the checking and remediation layers.

### D3: Executor returns `success=True` for manual remediations

**Decision**: When the executor encounters a `manual` block, it returns `success=True` with `remediation_type="manual"` and the steps/docs in `details`. This distinguishes it from `success=False` ("no remediation configured" or "remediation failed").

**Rationale**: From the AI's perspective, a manual remediation is a successful response — it got actionable guidance. The `remediation_type` field lets callers distinguish "automated fix applied" from "manual guidance returned."

### D4: `file_create` returns success when file already exists and control checks for file existence

**Decision**: Change `_execute_file_create` to return `success=True` with `remediation_type="file_create_skipped"` when the file exists and `overwrite=false`. The message changes from the generic "File already exists" to "File already exists — control may already be satisfied."

**Rationale**: Most `file_create` remediations are for controls that check "does this file exist?" If the file exists, the remediation's goal is already met. Reporting this as a failure confuses the AI and users.

### D5: `generate_threat_model` gains `output_path` parameter

**Decision**: Add an optional `output_path: str | None` parameter to `generate_threat_model()` in `tools.py`. When provided, write the generated content to that path (relative to `local_path`) and return a confirmation message. When `None` (default), behave as today — return content as a string.

**Alternative considered**: Create a separate `write_threat_model` tool. Rejected because it fragments the workflow and requires the AI to coordinate two calls.

### D6: New `file_create` templates are minimal and useful

**Decision**: Templates for README.md, LICENSE (MIT default), THREAT_MODEL.md, and .gitignore follow this principle: provide the minimum structure that satisfies the control check, with clear `<!-- TODO -->` markers for sections the user needs to fill in.

**Rationale**: Over-engineered templates create maintenance burden and may not match the project. Minimal templates get the control to pass and give the user a starting point.

### D7: `configure_status_checks` uses the existing `api_call` pattern

**Decision**: Rather than implementing a new Python function, add a declarative `api_call` remediation block for OSPS-QA-03.01 that calls the GitHub branch protection API to set required status checks. The check names come from context (`ci.required_checks`).

**Alternative considered**: Python implementation via `actions.py`. Rejected because the `api_call` executor already handles GitHub API calls with variable substitution and dry-run support. Adding another Python function duplicates this capability.

**Caveat**: This requires the `ci.required_checks` context key to be confirmed. The remediation block should declare `requires_context` for this key, so the orchestrator prompts for it if missing.

## Risks / Trade-offs

**[Manual remediations may become stale]** → Review them when the OSPS spec is updated. The `context_hints` field documents what context would enable automation, creating a clear path to upgrade.

**[Template content may not match all project types]** → Templates use `$PROJECT_NAME` substitution and `<!-- TODO -->` markers. Future work can add project-type-specific template variants.

**[`file_create_skipped` may mask real issues]** → Only change messaging, not behavior. The result still indicates the file wasn't created. The `details` dict preserves the original path and overwrite flag for debugging.

**[`generate_threat_model` file writing could overwrite user content]** → Default to not writing (backward compatible). When `output_path` is provided, check if file exists and don't overwrite unless explicitly requested.

**[`api_call` for status checks requires knowing check names]** → Declare `requires_context` with `key = "ci.required_checks"`. The context system handles prompting. If context is missing, the remediation gracefully skips with a message about what context is needed.

## Open Questions

- Should `manual` remediations be included in the `remediate_audit_findings` MCP tool output, or filtered to a separate "guidance" section? Leaning toward including them with a clear `type: manual` marker.
- For LICENSE template: should we default to MIT, or require license type as a context key? Leaning toward context key (`legal.license_type`) with MIT as fallback.
