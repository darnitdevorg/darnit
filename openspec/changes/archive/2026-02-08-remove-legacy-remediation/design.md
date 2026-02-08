## Context

The remediation system currently has three dispatch tiers in `orchestrator.py`:

1. **TOML declarative** (file_create, exec, api_call) — executed by `RemediationExecutor`
2. **TOML manual** — returns step-by-step guidance
3. **Legacy Python fallback** — 11 functions in `actions.py` dispatched via `func_map` and `REMEDIATION_REGISTRY`

The legacy tier predates the TOML system. Each Python function embeds file templates as string literals, duplicates ecosystem detection logic, and manually handles context substitution. The TOML system already supports all these operations declaratively via `file_create` with `${context.*}` template variables.

**Current state**: 9 controls have executable TOML remediation, 32 have TOML manual guidance, 21 have none. The legacy `REMEDIATION_REGISTRY` maps 11 categories covering ~20 controls, but several of these controls already have TOML remediation that wins in the dispatch priority order.

## Goals / Non-Goals

**Goals:**
- Migrate all 11 legacy Python remediation functions to TOML declarative format
- Delete `actions.py`, `registry.py`, the `func_map`, and `_apply_legacy_remediation()`
- Simplify the orchestrator to a 2-tier dispatch: TOML executable → TOML manual
- Preserve identical file output for all migrated remediations (templates match current Python output)
- Move `requires_context` definitions from `REMEDIATION_REGISTRY` to TOML `remediation.requires_context`

**Non-Goals:**
- Improving the content of generated files (e.g., better GOVERNANCE.md templates) — that's a separate change
- Migrating to handler-based dispatch (tasks 9.4/9.5 from toml-schema-improvements) — deferred until orchestrator supports `HandlerInvocation`
- Adding new remediation coverage for the 21 controls that currently have none
- Changing the MCP tool API surface (`remediate_audit_findings` parameters stay the same)

## Decisions

### 1. File templates go in TOML `[templates]` section

**Decision**: Use the existing `[templates]` section in `openssf-baseline.toml` to define multi-line file templates, referenced from `remediation.file_create.template`.

**Rationale**: The template system already exists and supports `${context.*}` / `${project.*}` substitution via `RemediationExecutor._substitute()`. This avoids inventing a new mechanism. Template variable syntax aligns with the existing `${owner}`, `${repo}` patterns.

**Alternative considered**: External template files in a `templates/` directory. Rejected because it splits the single-file TOML config into multiple files, complicating distribution and plugin packaging.

### 2. `enable_branch_protection` becomes `api_call` in TOML

**Decision**: Migrate the branch protection function to `remediation.api_call` using the existing GitHub API call infrastructure.

**Rationale**: The function already does a `gh api` call under the hood. The TOML `api_call` type supports the same `command`, `payload`, and `method` fields. The orchestrator's `RemediationExecutor` already handles `api_call` dispatch.

### 3. `configure_dco_enforcement` becomes `manual` guidance

**Decision**: Convert DCO enforcement from a Python function to TOML `remediation.manual` steps.

**Rationale**: The Python function checks for a `.github/dco.yml` file and creates it, but DCO enforcement also requires installing the DCO GitHub App — which cannot be done via API. The current function only handles the config file, not the app installation. Manual guidance that covers both steps is more honest about what's needed.

### 4. `REMEDIATION_REGISTRY` is deleted entirely, not converted

**Decision**: Remove `registry.py` completely. The category-to-control mapping is already implicit in the TOML structure (each control has its own `[remediation]` section).

**Rationale**: The registry exists only to map category names to Python functions. Once all functions are TOML-driven, the registry has no purpose. The `get_categories_for_failures()` helper is only used by the legacy dispatch path. The `remediate_audit_findings` MCP tool already works by iterating TOML controls, not by querying the registry.

**Migration**: Any code that currently imports from `registry.py` (only `orchestrator.py`) gets its imports removed along with the legacy dispatch path.

### 5. Context requirements move to TOML `requires_context`

**Decision**: The `requires_context` entries currently in `REMEDIATION_REGISTRY` (for `codeowners`, `maintainers`, `governance`) move to each control's `[controls."ID".remediation]` section as `requires_context = [{ key = "maintainers", ... }]`.

**Rationale**: The orchestrator's `_validate_context_requirements()` already reads `requires_context` from TOML when available, falling back to the registry. Once TOML has the definitions, the registry fallback is unnecessary.

### 6. Migration order: templates first, then delete

**Decision**: Implement in two phases:
1. Add all TOML file_create templates and requires_context entries (legacy still works as fallback)
2. Delete legacy code after verifying TOML remediations produce correct output

**Rationale**: Phase 1 is safe — TOML declarative wins over legacy in dispatch priority, so adding TOML remediation for a control automatically bypasses its legacy function. Phase 2 is a clean deletion with no behavioral change.

## Risks / Trade-offs

**[Template fidelity]** → The Python functions dynamically adapt templates based on context (e.g., `create_governance_doc` changes structure based on `governance_model`). TOML templates are simpler string substitution.
→ Mitigation: Use conditional template sections where supported, or accept slightly less dynamic output. The generated files are starting points that users customize anyway.

**[Ecosystem detection loss]** → `create_dependabot_config` auto-detects package ecosystems (npm, pip, cargo, etc.). TOML `file_create` doesn't have this logic.
→ Mitigation: Use a generic dependabot template that covers common ecosystems, with manual steps prompting the user to customize. Alternatively, add ecosystem detection as a context sieve pass that populates a `detected_ecosystems` context value.

**[Test coverage gap]** → Deleting `actions.py` removes ~1,380 lines of tested code. New TOML templates need their own validation.
→ Mitigation: Add integration tests that verify TOML template rendering produces valid file content for each migrated category.

**[Breaking change for registry importers]** → Any code importing from `registry.py` breaks.
→ Mitigation: The only importer is `orchestrator.py` (same package). No external consumers documented.

## Open Questions

1. Should `create_dependabot_config`'s ecosystem detection be preserved as a context sieve detector, or is a generic multi-ecosystem template sufficient?
2. Should the TOML templates be extracted to a separate `[templates]` section (referenced by name) or inlined in each control's `remediation.file_create.content`? Currently the codebase uses both patterns.
