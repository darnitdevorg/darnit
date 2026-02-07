## Context

The sieve verification loop is implemented 3 times:

1. **`darnit/tools/audit.py`** — `_run_sieve_checks()` (100 lines). The richest version: creates `UnifiedLocator`, passes `locator_config` to `CheckContext`, iterates by level via registry. Called by `run_checks()` which adds user config exclusions.
2. **`darnit/server/tools/builtin_audit.py`** — `builtin_audit()` inline loop (15 lines). Simpler: flat iteration over pre-loaded controls, no locator, no exclusions.
3. **`darnit-baseline/tools.py`** — `audit_openssf_baseline()` inline loop (20 lines). Similar to #2, also rebuilds summary dict inline instead of calling `summarize_results()`.

Additionally, `detect_workflow_checks()` is duplicated between `darnit/remediation/helpers.py` and `darnit/remediation/github.py`.

The existing public API from `darnit.tools` exports: `prepare_audit`, `run_checks`, `calculate_compliance`, `summarize_results`, `format_results_markdown`.

## Goals / Non-Goals

**Goals:**
- Single sieve execution path so bug fixes and features (locator, exclusions) apply everywhere
- All callers get `UnifiedLocator` integration and user config exclusion support
- Reduce total code by ~120 lines (inline loops + duplicate formatter + duplicate utility)
- Codify the pattern in the framework-design spec so future contributors don't re-introduce duplication

**Non-Goals:**
- Changing the sieve orchestrator internals (`SieveOrchestrator.verify()`)
- Modifying how controls are loaded from TOML (that stays in config module)
- Consolidating the broader report formatting system (summary tables, emoji mappings) — that's a separate change
- Changing the `_run_baseline_checks()` in the remediation orchestrator — it already delegates to `prepare_audit()` + `run_checks()`

## Decisions

### Decision 1: Extract `run_sieve_audit()` from existing `_run_sieve_checks()`

**Choice:** Rename `_run_sieve_checks()` to `run_sieve_audit()`, make it public, and broaden its signature to accept optional pre-loaded controls.

**Alternatives considered:**
- *Create a new function alongside `_run_sieve_checks`* — rejected because it would add yet another function; the existing one already does 90% of what's needed.
- *Have callers use `run_checks()` directly* — rejected because `run_checks()` couples control loading with execution; callers that already loaded/filtered controls would need to reload.

**Signature:**
```python
def run_sieve_audit(
    owner: str,
    repo: str,
    local_path: str,
    default_branch: str,
    level: int = 3,
    *,
    controls: list[ControlSpec] | None = None,
    tags: list[str] | None = None,
    apply_user_config: bool = True,
    stop_on_llm: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
```

Returns `(results, summary)` so callers don't need to call `summarize_results()` separately.

### Decision 2: Keep `run_checks()` as a thin wrapper

**Choice:** `run_checks()` becomes a thin wrapper that calls `run_sieve_audit()` and adds the skipped-controls dict to match its existing return type `(results, skipped_controls)`.

**Rationale:** Preserves backward compatibility for the CLI path and the remediation orchestrator which both use `run_checks()`.

### Decision 3: `builtin_audit()` delegates instead of reimplementing

**Choice:** Rewrite `builtin_audit()` to:
1. Load config and controls (existing code)
2. Call `run_sieve_audit(controls=loaded_controls, ...)`
3. Call `format_results_markdown()` for output

Delete `_format_audit_report()` entirely (~90 lines).

### Decision 4: `audit_openssf_baseline()` delegates instead of reimplementing

**Choice:** Rewrite the sieve loop section to:
1. Keep existing config/control loading and tag filtering
2. Replace the inline loop + summary calculation with `run_sieve_audit(controls=filtered_controls, ...)`
3. Continue using `format_results_markdown()` (already does this)

### Decision 5: Delete `detect_workflow_checks` from `helpers.py`

**Choice:** Delete the simpler version in `helpers.py` (~80 lines), keep the more complete version in `github.py` that handles matrix builds and job names.

**Verification:** Grep for all imports of `detect_workflow_checks` from `helpers` and redirect to `github`.

### Decision 6: Add spec requirements for audit pipeline pattern

**Choice:** Add a new "Audit Pipeline" section to the framework-design spec that codifies:
- All audit entry points MUST delegate to `run_sieve_audit()`
- No module SHALL reimplement the sieve loop
- Utility functions MUST NOT be duplicated within the framework package

This serves both human developers and LLM coding agents who read the spec before writing code.

## Risks / Trade-offs

**[Signature change to `_run_sieve_checks`]** → The function is currently private (underscore prefix). Renaming to `run_sieve_audit` and making it public is safe since no external consumers depend on the private name. Internal callers (`run_checks`) are updated in the same change.

**[`builtin_audit` loses its simpler formatter]** → The full `format_results_markdown()` produces longer output with remediation guidance and next steps. This is strictly better for MCP users since they get the same rich output regardless of entry point. If a minimal format is ever needed, it can be added as a `compact` parameter to the existing formatter.

**[`run_checks()` return type unchanged]** → The existing `(results, skipped_controls)` return type is different from `run_sieve_audit()`'s `(results, summary)`. This is intentional — `run_checks` serves the CLI/orchestrator path that needs skipped control info, while `run_sieve_audit` serves MCP tools that need summaries.

**[`detect_workflow_checks` removal from helpers]** → Any code importing from `helpers` will break. Mitigation: grep for all imports and update them before deleting. The function is only used in `github.py` itself and the remediation orchestrator.
