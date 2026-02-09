## Context

The darnit framework uses a TOML-based schema to declaratively define compliance controls. Currently the schema hardcodes specific check types (`file_must_exist`, `exec`, `pattern`, `llm`, `manual`) as distinct fields in `PassesConfig`. This conflates the **confidence gradient** (the order in which you try things) with **specific handler implementations** (the things you actually run).

The insight: the sieve pipeline represents how a human approaches compliance verification — and this same approach applies to verification, context gathering, and remediation:

1. **Deterministic** — Run scans. High-confidence, binary answers.
2. **Pattern** — Investigate further. Heuristic, regex, content analysis.
3. **LLM** — Reason about it. AI evaluation with confidence scoring.
4. **Manual** — Ask a human. Last resort when automation can't get there.

Within each phase, the actual work is done by **handlers** — pluggable units registered by core or by implementations. The framework provides the phase ordering and fallback semantics. Handlers are the extensible part.

### Current Architecture (what changes)

```
PassesConfig (hardcoded types)
  ├── deterministic: DeterministicPassConfig  # file_must_exist only
  ├── exec: ExecPassConfig                    # commands (labeled deterministic internally)
  ├── pattern: PatternPassConfig              # regex
  ├── llm: LLMPassConfig                     # AI eval
  └── manual: ManualPassConfig               # human steps
```

`exec` is already classified as `PassPhase.DETERMINISTIC` at line 354 of `framework_schema.py` — it's not a separate phase, just a separate TOML field that leaks implementation into schema.

Similarly, remediation hardcodes `file_create`, `exec`, `api_call`, `manual`, `project_update` as separate typed fields. Context gathering has its own ad-hoc detection functions.

### What We Want

The confidence gradient as a **universal workflow** across all three operations:

| Phase | Verification | Context Gathering | Remediation |
|-------|-------------|-------------------|-------------|
| **Deterministic** | File exists, API returns value, command exits 0 | GitHub API for maintainers, read CODEOWNERS | Template file creation, API call, exec |
| **Pattern** | Regex content analysis, heuristic matching | Parse README for maintainer patterns | Search and replace, content patching |
| **LLM** | AI reasoning about evidence | Infer governance from docs | "Update all docs mentioning maintainers" |
| **Manual** | Human verification steps | Ask user to confirm | Step-by-step instructions |

Same handler system, same fallback philosophy. Handlers are registered by:
- **Core darnit** — built-in handlers (file_exists, exec, regex, etc.)
- **Libraries** — reusable handler packages
- **Implementations** — domain-specific handlers in Python (scorecard check, branch protection analyzer, etc.)

### Stakeholders

- Framework (`packages/darnit/`) — schema, loader, orchestrator, handler registry
- Implementation (`packages/darnit-baseline/`) — `openssf-baseline.toml`, Python handlers
- Plugin authors — anyone building a new compliance framework on darnit

## Goals / Non-Goals

**Goals:**
- Generalize the sieve pipeline to handler-based phases (deterministic → pattern → llm → manual) for verification, context gathering, and remediation
- Provide a handler registry where core registers built-ins and implementations register domain-specific handlers
- Eliminate redundant execution via shared handler invocations with per-audit caching
- Express control-to-control relationships (`depends_on`, `inferred_from`)
- Mark controls as not-applicable based on project type (`when` clause)
- Remove DRY violations (`use_locator`, auto-derived `on_pass`)
- Extend template variables to support `${context.<key>}` and `${project.<dotted.path>}` references
- Codify: context informs locators, never overrides verification

**Non-Goals:**
- Async/parallel check execution (orthogonal, can layer on later)
- External template files (separate concern, already tracked in roadmap)
- Schema migration tooling (premature — we're still at 0.1.0-alpha)
- Rewriting existing handler implementations — existing `file_must_exist`, `exec`, `pattern` logic stays, just gets registered as handlers instead of being hardcoded

## Decisions

### D1: The sieve pipeline is a confidence gradient with pluggable handlers

**Choice**: `PassesConfig` becomes four optional lists of handler invocations, one per phase. Each entry names a handler and provides handler-specific configuration.

```toml
# Verification passes
[controls."OSPS-DO-01.01".passes]
deterministic = [
  { handler = "file_exists", files = ["README.md", "README.rst"], use_locator = true },
]
pattern = [
  { handler = "regex", file = "$FOUND_FILE", pattern = "^# .+", min_matches = 3 },
]

# A control with an exec-based deterministic check
[controls."OSPS-AC-03.01".passes]
deterministic = [
  { handler = "exec", command = ["gh", "api", "..."], expr = "output.json.required_pull_request_reviews != null" },
]
```

**Schema**:

```python
class HandlerInvocation(BaseModel):
    """A single handler call within a phase."""
    handler: str                          # Handler name (registered in registry)
    shared: str | None = None             # Reference a shared handler definition
    model_config = ConfigDict(extra="allow")  # Handler-specific fields pass through

class PassesConfig(BaseModel):
    """Verification pipeline: 4 phases, each a list of handler invocations."""
    deterministic: list[HandlerInvocation] | None = None
    pattern: list[HandlerInvocation] | None = None
    llm: list[HandlerInvocation] | None = None
    manual: list[HandlerInvocation] | None = None
```

`extra="allow"` on `HandlerInvocation` is key — it lets handler-specific config (`files`, `command`, `expr`, `pattern`, etc.) pass through without the framework schema needing to know about every handler's parameters. The handler validates its own config at registration or execution time.

**Why lists?** A phase may have multiple checks. e.g., a deterministic phase might check file existence AND run an API call. They all run within the same confidence tier.

**Why not a flat list with phase annotations?** Grouping by phase in TOML makes the confidence gradient visually obvious and prevents accidental misordering.

**Built-in handlers registered by core darnit:**

| Handler | Phase | What it does |
|---------|-------|-------------|
| `file_exists` | deterministic | Check file existence from a list of paths |
| `exec` | deterministic | Run command, evaluate exit code / CEL expr |
| `api` | deterministic | HTTP request, evaluate response |
| `regex` | pattern | Match regex patterns in file content |
| `content_analysis` | pattern | Heuristic content validation |
| `llm_eval` | llm | AI evaluation with confidence threshold |
| `manual_steps` | manual | Human verification checklist |

Implementations register their own: `scorecard`, `branch_protection_check`, `license_analyzer`, etc.

### D2: The same gradient applies to context gathering

**Choice**: Context definitions in the TOML can specify a handler pipeline for auto-detection, following the same phase ordering.

```toml
[context.maintainers]
category = "governance"
description = "Project maintainers"
detect = [
  { phase = "deterministic", handler = "exec", command = ["gh", "api", "/repos/$OWNER/$REPO/collaborators"], expr = "..." },
  { phase = "deterministic", handler = "file_exists", files = ["CODEOWNERS", ".github/CODEOWNERS"] },
  { phase = "pattern", handler = "regex", file = "$FOUND_FILE", pattern = "@\\w+" },
  { phase = "llm", handler = "llm_eval", prompt = "Who are the maintainers of this project?" },
]
confirm = "manual"  # Always ask user to confirm detected values
```

**Why the same gradient?** A human gathering project context would do exactly this: check the API first, look at files, try to infer from content, ask someone if still unsure. The same handler infrastructure works.

**`confirm = "manual"`** means low-confidence detections (or all detections, depending on policy) prompt the user for confirmation before writing to `.project/`. This replaces the current ad-hoc `_auto_detect_context()` functions with a declarative, extensible pipeline.

### D3: Remediation also uses the handler gradient

**Choice**: `RemediationConfig` follows the same pattern — a phased list of handler invocations instead of hardcoded typed fields.

```toml
[controls."OSPS-DO-01.01".remediation]
deterministic = [
  { handler = "file_create", template = "readme_basic", path = "README.md" },
  { handler = "project_update", updates = { "documentation.readme.path" = "README.md" } },
]

# For complex cases where templates aren't enough
[controls."OSPS-GV-01.01".remediation]
deterministic = [
  { handler = "file_create", template = "governance_doc", path = "GOVERNANCE.md" },
]
llm = [
  { handler = "llm_update", prompt = "Update all documentation files that reference the project maintainers list with: ${context.maintainers}" },
]
manual = [
  { handler = "manual_steps", steps = ["Review generated GOVERNANCE.md", "Verify maintainer list is complete"] },
]
```

**Why?** Most remediations are deterministic (create file, call API, run command). But there are cases where:
- A template or search-and-replace can't handle the complexity (LLM fallback: "update all docs that mention maintainers")
- The implementation doesn't have full automation for a control (LLM can supplement)
- The remediation needs human review or manual steps

**Schema**: Same `list[HandlerInvocation]` pattern. Built-in remediation handlers: `file_create`, `exec`, `api_call`, `project_update`, `manual_steps`, `llm_update`.

**Fallback behavior**: Unlike verification (which stops at first conclusive result), remediation runs all deterministic handlers, then falls to pattern/llm only if the deterministic handlers indicate incomplete remediation or if the implementation author explicitly includes them.

### D4: Shared handler definitions with per-audit caching

**Choice**: `[shared_handlers]` is a top-level TOML section where named handler configurations are defined once and referenced by multiple controls.

```toml
[shared_handlers.branch_protection]
handler = "exec"
command = ["gh", "api", "/repos/$OWNER/$REPO/branches/$BRANCH/protection"]
output_format = "json"

[controls."OSPS-AC-03.01".passes]
deterministic = [
  { shared = "branch_protection", expr = "has(output.json.required_pull_request_reviews)" },
]

[controls."OSPS-AC-03.02".passes]
deterministic = [
  { shared = "branch_protection", expr = "output.json.allow_deletions.enabled == false" },
]
```

When `shared` is set, the handler config is inherited from the shared definition. The control provides its own `expr` (or other evaluation-specific fields). The framework executes the shared handler once per audit run and caches the result.

**Cache scope**: Per audit invocation. Never persisted across runs.

**Shared handler failure**: If the shared handler errors (e.g., API rate-limited), all referencing controls get ERROR with a message identifying the shared handler by name.

**Unreferenced shared handlers**: Not executed.

### D5: `when` conditions evaluated before the handler pipeline

**Choice**: `when` is evaluated in the orchestrator *before* entering the phase loop. If the condition evaluates to false, return N/A immediately.

**Schema**: `ControlConfig` gains `when: dict[str, Any] | None = None`.

**Evaluation rules**:
- All conditions are AND-ed
- Missing context key → control runs normally (not N/A), debug log
- `when = { key = true }` — boolean match
- `when = { key = "value" }` — string equality
- `when = { key = ["a", "b"] }` — list membership

`when` determines **applicability** (is this control relevant to my project?), never **correctness** (does this control pass?). Release controls don't apply to projects without releases — that's applicability. Context saying "you have a SECURITY.md" doesn't mean the control passes — that's correctness, and the handler pipeline must verify it.

**Result type**: `SieveStatus.NOT_APPLICABLE`. N/A results get their own section in the markdown report, separate from PASS/FAIL/WARN.

### D6: Control dependencies via `depends_on` and `inferred_from`

**Choice**: The orchestrator topologically sorts controls before verification.

**`depends_on`**: Ordering only. A failed dependency does NOT skip the dependent control. The dependency's result is available in the dependent control's evidence as `dependency.<CTRL_ID>.status`.

**`inferred_from`**: If the referenced control PASSES, the declaring control auto-PASSES with an inference message and skips its own handlers. If the referenced control does NOT pass, the declaring control runs normally. `inferred_from` implies `depends_on`.

**Cycle detection**: Log warning, break by ignoring back-edges, evaluate in natural order.

**Out-of-scope references**: If a dependency target is filtered out by level, the dependency is ignored with a debug log.

### D7: `use_locator` and auto-derived `on_pass` — load-time resolution

**Choice**: Both resolved in `control_loader.py` during TOML → ControlSpec conversion.

**`use_locator = true`** on a deterministic handler invocation → loader copies `locator.discover` into the handler's `files` parameter. If both `use_locator` and `files` are set, `files` wins. Missing `locator.discover` → log warning, handler returns INCONCLUSIVE.

**Auto-derived `on_pass`**: When a control has `locator.project_path`, a deterministic `file_exists` handler (or `use_locator`), and no explicit `on_pass`, the loader generates `on_pass = { project_update = { "<project_path>.path" = "$EVIDENCE.found_file" } }`. Explicit `on_pass` always wins.

### D8: Template variables support `${context.*}` and `${project.*}`

**Choice**: Extend `executor.py:_get_substitutions()` to resolve:
- `${context.<key>}` — confirmed context values from `.project/project.yaml`
- `${project.<dotted.path>}` — arbitrary project YAML values by dotted path

**Resolution**: Unresolved references → empty string + debug log. Never fail a remediation over a missing variable.

**Where used**: File creation content, exec command arguments, API payloads, stdin content — everywhere the existing `$VAR` substitution already applies.

### D9: Handler registry architecture

**Choice**: A central handler registry where handlers are registered by name with their phase affinity and a callable.

```python
# Core registers built-ins
registry.register("file_exists", phase="deterministic", handler_fn=file_exists_handler)
registry.register("exec", phase="deterministic", handler_fn=exec_handler)
registry.register("regex", phase="pattern", handler_fn=regex_handler)

# Implementation registers domain-specific handlers
registry.register("scorecard", phase="deterministic", handler_fn=scorecard_handler)
```

**Handler interface**: A handler receives its config dict (the extra fields from `HandlerInvocation`) plus the execution context (local path, project config, evidence so far). Returns a result with status, confidence, evidence, and message.

**Phase affinity**: Handlers declare which phase they belong to. The framework validates that a handler isn't used in the wrong phase (e.g., an LLM handler in the deterministic phase). This is a warning, not an error — the implementation author may have good reasons.

**Three tiers of handlers**:
1. **Core** (`packages/darnit/`) — built-in handlers shipped with the framework
2. **Library** — reusable handler packages installable via pip
3. **Implementation** (`packages/darnit-baseline/`) — domain-specific handlers registered via the plugin system

This uses the existing `ComplianceImplementation.register_handlers()` method. No new plugin mechanism needed.

## Risks / Trade-offs

**Handler validation at runtime vs load time** → With `extra="allow"` on `HandlerInvocation`, handler-specific config isn't validated by Pydantic at TOML load time. Invalid config surfaces only when the handler runs. Mitigation: handlers can register a config schema that the loader validates eagerly. Start permissive, tighten later.

**Backward compatibility** → The current `PassesConfig` with typed fields (`deterministic`, `exec`, `pattern`) is used by `openssf-baseline.toml` (2600+ lines). Mitigation: support both formats during transition. The loader detects old-style typed configs and converts them to `HandlerInvocation` lists internally. Deprecate old format in the next minor version.

**Shared handler cache invalidation** → Cache is per-audit-run, so staleness isn't a concern. But a shared handler failure (e.g., rate-limited API) errors ALL referencing controls. Mitigation: clear error message identifying the shared handler name.

**Circular dependencies** → Topological sort detects cycles. Log warning, break by ignoring back-edges. This is a configuration error, not a runtime failure.

**`inferred_from` misuse** → Someone could claim an inference where the logic doesn't hold. The framework can't validate semantic correctness — this is a TOML authoring concern. Document that inference must be logically sound.

**LLM remediation unpredictability** → LLM-based remediation (e.g., "update all docs mentioning maintainers") may produce unexpected changes. Mitigation: LLM remediation handlers should always produce a diff for user review, never auto-apply. The `manual` fallback phase catches anything the LLM gets wrong.

**Handler sprawl** → With everything pluggable, implementations might register many small handlers. Mitigation: core provides enough built-in handlers (`file_exists`, `exec`, `regex`, `llm_eval`, `manual_steps`, `file_create`, `api_call`, `project_update`) that most controls need zero custom handlers. Custom handlers are for genuinely domain-specific logic.

## Open Questions

1. **Should handlers declare a config schema?** If yes, the loader can validate handler-specific config at load time. If no, validation happens at execution time. Recommend: optional schema registration, validate if present.

2. **Should `inferred_from` support a list?** Current spec says single control ID. OR semantics (any of several controls passing satisfies this one) could be useful. Start with single, extend later if needed.

3. **Should remediation phases have fallback semantics?** Currently proposed as "run deterministic, fall to LLM/manual if explicitly configured." Could also support auto-fallback: "if deterministic remediation didn't fully fix it, try the next phase." Needs more real-world use cases to decide.

4. **Context gathering pipeline scope** — Should context detection pipelines be part of the framework TOML or the implementation TOML? Current answer: implementation TOML (the context definitions section), since what context to gather is implementation-specific. But the handler infrastructure comes from core.
