## Why

The TOML schema maps well to the sieve pipeline but has gaps when measured against the full compliance workflow: discover project facts, run deterministic checks, fall back to heuristics, enrich context, remediate with that context, and update context post-remediation.

Key pain points:
- Redundant API calls (4 controls hit the same branch protection endpoint)
- DRY violations between `locator.discover` and `passes.deterministic.file_must_exist`
- No control dependency chain (OSPS-LE-03.02 literally has a TODO saying "if OSPS-LE-03.01 passes, this is satisfied")
- No way to mark controls as not-applicable based on project context (e.g., release controls when `has_releases = false`)
- Many controls only check existence without validating content — the schema should encourage the two-phase pattern: (1) does the thing exist, (2) does it look right

There is also an important architectural principle to codify: **context informs where to look, never whether to pass**. The `.project/` context may be stale or wrong. Context tells the sieve "check SECURITY.md for the security policy" — but the sieve must still verify SECURITY.md exists AND contains a valid security policy. Context is a locator hint, not a trust anchor.

## What Changes

- Add shared execution definitions so multiple controls can reference one API call/command instead of duplicating it
- Add control dependencies (`depends_on` / `inferred_from`) so controls can auto-PASS when a prerequisite passes — but only when the inference is logically sound (e.g., LICENSE in repo → LICENSE in release archives, because GitHub auto-includes repo files)
- Add applicability controls (`when`) so controls can be marked N/A based on project context — this is about relevance ("release controls don't apply to projects without releases"), NOT about correctness
- Allow passes to reference locator discovery lists (`use_locator = true`) instead of duplicating file lists
- Auto-derive `on_pass` from `locator.project_path` when both locator and `file_must_exist` are present, eliminating boilerplate
- Extend template variable substitution to support `${context.<key>}` and `${project.<path>}` references
- Encourage two-phase check pattern in schema: existence check (deterministic) + validity check (pattern/exec/LLM) — context guides where to look for both phases

## Capabilities

### New Capabilities
- `shared-execution`: Define shared check definitions that multiple controls can reference, with caching to avoid redundant API/command calls
- `control-dependencies`: Express control-to-control relationships — `depends_on` for ordering and `inferred_from` for logical pass propagation
- `conditional-controls`: Mark controls as not-applicable based on project context (`when` clause for relevance, not correctness)

### Modified Capabilities
- `framework-design`: Add schema-level requirements for `use_locator`, auto-derived `on_pass`, `${context.*}` template variables, and the principle that context informs locators but never overrides verification

## Impact

- `packages/darnit/src/darnit/config/framework_schema.py` — New Pydantic models for shared execution, control dependencies, conditional controls; extended `PassesConfig`, `ControlConfig`, `TemplateConfig`
- `packages/darnit/src/darnit/config/control_loader.py` — Resolve shared execution references, wire up `use_locator`, auto-derive `on_pass`
- `packages/darnit/src/darnit/sieve/orchestrator.py` — Evaluate `when` conditions, resolve `depends_on`/`inferred_from` before running passes; ensure context never short-circuits verification
- `packages/darnit/src/darnit/remediation/executor.py` — Expand `${context.*}` and `${project.*}` in template variable substitution
- `packages/darnit-baseline/openssf-baseline.toml` — Migrate redundant exec definitions to shared execution, add `when` clauses, add `depends_on`, replace duplicate file lists with `use_locator`
- `openspec/specs/framework-design/spec.md` — Delta spec for new schema requirements
