## Context

Today, both the sieve orchestrator (`orchestrator.py:235`) and the remediation executor (`executor.py:369`) iterate `HandlerInvocation` lists unconditionally — every handler in the list is dispatched regardless of project characteristics. The only conditional mechanism is the control-level `when` clause on `ControlConfig`, which skips an entire control.

Meanwhile, the auto-detection system already collects `primary_language`, `platform`, and `ci_provider` at audit time. The `when` evaluation logic exists for control-level applicability. The pieces are in place — they just need to be connected at the handler level.

The key insertion points are:
- **Sieve orchestrator**: `_dispatch_handler_invocations()` loop at `orchestrator.py:235`
- **Remediation executor**: `_execute_handler_invocations()` loop at `executor.py:369`
- **Context availability**: Both loops already have access to `project_context` via `HandlerContext`

## Goals / Non-Goals

**Goals:**
- Enable TOML authors to write conditional handlers with `when = { primary_language = "go" }` or `when = { languages = "go" }` on any `HandlerInvocation`
- Support list-valued context matching (`"go" in ["go", "typescript"]`) for forward-compatible monorepo support
- Provide `first_match` strategy on `RemediationConfig` so conflicting language-specific remediations don't all fire
- Detect all languages in a repo as `languages: list[str]` alongside the existing `primary_language: str`
- Reuse the `when` evaluation logic across both sieve passes and remediation handlers

**Non-Goals:**
- **Directory-level language locations** (`language_locations: dict[str, list[str]]`) — deferred to a future monorepo change
- **`${language_root}` substitution variable** in remediation templates — deferred; hardcoded paths work for v1
- **`when` using CEL expressions** — the `when` clause stays a simple key-value dict, not a full expression language. CEL is available via `expr` for post-handler evaluation, which is a separate concern.
- **Strategy on sieve passes** — the sieve orchestrator already has "stop at first conclusive result" semantics. Adding `strategy` is only needed for remediation where "run all" is the default.

## Decisions

### Decision 1: Shared `evaluate_when()` function

**Choice**: Extract a single `evaluate_when(when_clause, context) -> bool` function in a new module `darnit/config/when_evaluator.py`.

**Rationale**: Both the sieve orchestrator and the remediation executor need the same evaluation logic. Putting it in `config/` makes it available to both without creating a circular dependency (both `sieve/` and `remediation/` already import from `config/`).

**Alternatives considered**:
- Inline in each dispatch loop → duplication, inconsistent behavior
- In `sieve/` → remediation would need to import from sieve, muddying the layer boundary

**Evaluation rules**:
| Context value type | `when` value type | Match rule |
|--------------------|-------------------|------------|
| `str` | `str` | Exact equality |
| `str` | `list[str]` | Context value is in the list (existing control-level behavior) |
| `bool` | `bool` | Exact equality |
| `list[str]` | `str` | **Scalar is contained in the list** (new — enables `when = { languages = "go" }`) |
| `list[str]` | `list[str]` | All when-values are contained in context list (subset check) |
| Missing key | any | **Condition not met → handler skipped** (conservative) |

Multiple keys in a single `when` clause are AND-ed (all must match), consistent with control-level `when`.

### Decision 2: `when` field on `HandlerInvocation` (not a new model)

**Choice**: Add `when: dict[str, Any] | None = None` as an explicit field on `HandlerInvocation`.

**Rationale**: `HandlerInvocation` uses `extra="allow"`, so `when` would technically work as a pass-through field already. But making it explicit means:
- It's documented in the schema
- It's not accidentally passed to handlers as config
- The orchestrator/executor can access it directly via `invocation.when` instead of fishing through `model_extra`

**Impact**: The orchestrator/executor must strip `when` from the handler config dict they build from `model_extra`, so handlers don't receive it as config. Since `when` is now an explicit field, it won't appear in `model_extra` — Pydantic handles this automatically.

### Decision 3: `strategy` field on `RemediationConfig`

**Choice**: Add `strategy: Literal["all", "first_match"] = "all"` to `RemediationConfig`.

**Rationale**:
- `"all"` (default): Run all matching handlers in order. This preserves existing behavior — today every handler runs. For cases like "create file AND update project config", you want both.
- `"first_match"`: Stop after the first handler whose `when` matches (or has no `when`). For cases like "create go.mod OR pyproject.toml OR Cargo.toml", you want exactly one.

**Note**: `first_match` only affects handlers that have a `when` clause. A handler without `when` always matches. So `first_match` with a list of conditional handlers followed by a `manual` fallback means: try the conditional ones, fall through to manual if none match.

**Sieve passes don't need `strategy`**: The sieve already stops at the first conclusive result. The `when` clause just adds "skip this handler if condition isn't met" before dispatch — the existing stop-on-conclusive logic handles the rest.

### Decision 4: `detect_languages()` alongside `detect_primary_language()`

**Choice**: Add `detect_languages(local_path) -> list[str]` that scans for all manifest files (not stopping at the first match), and call it from `collect_auto_context()`.

**Rationale**:
- `primary_language` stays as-is for backward compatibility — controls using `when = { primary_language = "go" }` continue working
- `languages` is a new list-valued key that captures the full picture
- Detection reuses the same manifest-file checks, just doesn't `break` on first match
- Both are auto-detected (factual, safe, no user confirmation needed)

**TypeScript refinement**: If `package.json` is found and `tsconfig.json` exists, the list includes `"typescript"` rather than `"javascript"` (same logic as today, applied per-detection).

### Decision 5: Context assembly for `when` evaluation

**Choice**: Build the `when` evaluation context from the same sources already available in both dispatch loops, merging auto-detected context with user-confirmed context.

In the sieve orchestrator, `HandlerContext.project_context` already contains the merged context. In the remediation executor, `self._project_values` and `self._context_values` provide the same.

The `when` evaluator receives a flat `dict[str, Any]` — it doesn't need to know where values came from. The caller is responsible for assembling it. Both call sites already have this data.

## Risks / Trade-offs

**[Risk] Handler authors put `when` in `model_extra` on old code** → Since `when` becomes an explicit field, Pydantic will extract it from `model_extra` automatically. Existing TOML that already has `when` in a handler invocation (none exists today) will just work.

**[Risk] `first_match` with no matching handler produces confusing results** → Mitigation: If `strategy = "first_match"` and no handler's `when` matches, the executor returns a "no applicable remediation" result with a message listing the unmatched conditions. This is analogous to how the sieve returns WARN when all phases are inconclusive.

**[Risk] `languages` detection is imprecise for monorepos** → Mitigation: v1 only scans root-level manifests (same as today). This handles the common case (Go + TS at root) but not deeply nested monorepos. The `primary_language` fallback works for single-language repos. Future `language_locations` support can add depth when needed.

**[Trade-off] `when` evaluation is simple dict matching, not CEL** → This is intentional. CEL is powerful but heavyweight and would require the CEL evaluator at handler dispatch time (before the handler runs). The simple dict-matching approach covers the expected use cases (language, platform, CI provider) without adding complexity. If future use cases require expression evaluation, `expr` (post-handler CEL) or a new `when_expr` field could be added later.

**[Trade-off] No `strategy` on sieve passes** → The sieve's "stop at first conclusive" already handles the common case. If a sieve author writes three `file_exists` handlers with different `when` clauses, the first match that returns PASS stops the pipeline. This is naturally `first_match` behavior without needing an explicit field.
