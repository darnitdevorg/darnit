# Research: Close Remaining False-PASS Paths

**Feature**: 044-false-pass-paths | **Date**: 2026-10-04

## Current state

Paths are relative to `packages/darnit/src/darnit/` unless stated.

| Area | Today | Defect |
|---|---|---|
| Post-step expression | `sieve/orchestrator.py` `_apply_cel_expr` (~L102-180) runs for every step type except `gh_api` (`_HANDLERS_EVALUATING_OWN_EXPR`). It builds `{"output": evidence}`; on `not cel_result.success` it logs a warning and `return handler_result` (~L146-149), keeping PASS or FAIL. | #479: evaluation failure keeps the verdict. |
| Expression variables | Context has only `output`. `CELEvaluator(repo_path=None)` makes `file_exists()` return false (`sieve/cel_evaluator.py` ~L208). `gh_api` evaluates its own with `{"response": response}` (`sieve/builtin_handlers.py` ~L512). | #479: `project.*` and `file_exists` are documented (CLAUDE.md "Available context variables", `docs/architecture/framework-design.md` CEL table ~L548-565) but unusable. The docs also list `response.headers`, and `files` / `matches` for regex, which are never provided. |
| Shipped expressions on non-`gh_api` steps | BR-01.01 and AC-04.02 (`exec`, zizmor, `!output.json.exists(f, ...)`), DO-02.01, QA-05.01, QA-05.02 (`pattern`, `output.any_match` / `output.files_found == 0`), LE-02.01 (`regex`, `output.any_match`). None uses `project` or `file_exists`. | #479 exposure: zizmor exits with an accepted code and prints no JSON, so `output.json` is missing, evaluation fails, and the exec PASS stands. |
| Handler registration | `sieve/handler_registry.py` `register` (~L255-325): an existing core handler overridden by a plugin logs at debug and is replaced, including `ceiling`; a plugin-to-plugin collision logs a warning and is replaced. | #486: a plugin can widen a built-in ceiling (for example `manual` to PASS). |
| Schema strictness | `config/framework_schema.py`: `ControlConfig`, `HandlerInvocation`, and others use `extra="allow"` (L160, 183, 194, 206, 293, 325, 368, 410, 471, 518). | #486: a misspelled step field such as `fail_on_mis` is accepted and ignored. A survey of shipped TOML found no control-level keys outside the declared fields. |
| Unregistered step types | `config/control_loader.py` `validate_step_authority` (~L533) skips steps whose handler is unregistered; the orchestrator warns and skips them at dispatch (~L397). | #481: a typo in a handler name silently drops the step. `darnit-hello` and `darnit-example` use the unregistered `file_must_exist` (#501). |
| Reproducibility ceilings | `darnit-reproducibility/.../implementation.py` registers `repro_hermetic_build`, `repro_provenance_exists`, `repro_bit_for_bit`, `repro_deps_pinned`, `repro_build_env_declared` with `ceiling={"pass", "fail"}`. `repro_provenance_exists_handler` returns PASS when one of six strings appears in a workflow file. | #453, and the same for the other four (clarified 2026-10-04: all five). |
| `/user` evidence | `gh_api_handler` stores `{"endpoint", "response": {"status_code", "body"}}` (~L500-501). OSPS-AC-01.01's second step reads `/user` with `concludes = []`. | #493: the auditor's full profile lands in evidence, JSON, and attestations. |

Other plugin step types that may conclude PASS keep that ceiling:
- `gittuf_verify_policy` and `gittuf_commits_signed` run the gittuf verifier;
- `github_branch_protection` reads platform settings;
- `generate_threat_model` is a remediation handler.

## R1. A failed expression is ERROR

**Decision**: In `_apply_cel_expr`, when the handler result is PASS or FAIL and the expression fails to compile or evaluate, or evaluates to a non-boolean, return `HandlerResult(status=ERROR, error_class="evaluation", message=...)`. Carry over the handler's evidence and add `expr` and `expr_error` to it. ERROR never concludes (041), so evaluation continues to later steps.

**Rationale**: FR-001. This matches `gh_api`'s existing behavior (041: "CEL failure is now ERROR") and the 041 rule that a broken measurement is neither PASS nor FAIL.

**Alternatives considered**: INCONCLUSIVE, which would hide that something is broken, whereas `error.class = evaluation` is what operators read. Keeping FAIL on failure ("conservative"), which records a verdict nobody established; 041 says a broken measurement is never FAIL.

## R2. What an expression can see

**Decision**: The orchestrator's context becomes `{"output": evidence, "project": <usable project values>}`, and the evaluator receives `repo_path = Path(context.local_path)`.
- `project` is the step's `project_context`, which since 042 holds only usable values (confirmed, or concluded for detectable keys), keyed by canonical name (`project.ci_provider`, `project.has_releases`).
- A reference to an unusable key is a "no such member" evaluation error, so it becomes ERROR (R1).

`gh_api` keeps `{"response": {"status_code", "body"}}`; that step type adds no `project`.

The docs (CLAUDE.md, framework-design.md CEL table) are corrected:
- drop `response.headers`, and `files` / `matches` for regex;
- state which names each step type gets;
- keep `json_path` (implemented).

**Rationale**: FR-002 and FR-004. Binding `project` to usable values keeps 042's single-consumer rule.

**Alternatives considered**: Removing `project` and `file_exists` from the docs instead. They are useful, and the cost of binding them correctly is small.

## R3. Load-time check of expression references

**Decision**: When controls load (`validate_step_authority`, which already runs after plugins register), parse each step's `expr` with `celpy.Environment().compile` and collect the free identifiers:
- take every `ident` in a `primary` position;
- subtract variables bound by comprehension macros (the first argument of `exists`, `all`, `exists_one`, `map`, `filter`);
- subtract the known functions (`file_exists`, `json_path`, the CEL built-ins).

Each step type declares the names it provides (`expression_names`, R5). For `exec`, `pattern`, and `regex` that is `{"output", "project"}`; for `gh_api` it is `{"response"}`. An undeclared name fails loading with control, step index, handler, and name. A syntax error also fails loading.

**Rationale**: FR-003. A typo such as `ouput` is caught before any audit runs.

**Alternatives considered**: A dry evaluation with stub values, which is brittle with macros and types. Checking only at run time, which reports the problem as ERROR on every audit instead of at load.

## R4. Plugins cannot replace step types

**Decision**: `SieveHandlerRegistry.register` refuses, with a WARNING log and an entry in a `refused_registrations` list readable by reports and `darnit list`:
- a registration from a plugin context for a name already registered by core (`existing.plugin is None`);
- a registration for a name registered by a different plugin.

The same plugin re-registering its own name is allowed (idempotent loads). Core registers before plugins (import of `builtin_handlers` and `register_builtin_handlers()` run first); a test pins that order.

**Rationale**: FR-005 and FR-006, which protect the 041 authority contract.

**Alternatives considered**: An operator-config opt-in to allow overrides, which nothing needs today and which would reopen the hole. "Last plugin wins with a warning" (today), which makes the result depend on discovery order.

## R5. Declared step settings and strict schemas

**Decision**:
- **Common step fields**: `HandlerInvocation`'s declared fields plus `description` and `expr`. `description` is documentation-only and used by shipped TOML. `expr` is accepted only when the step type declares expression names.
- **Built-in step types**: `register(..., settings=frozenset({...}))` for each, listing exactly the keys the handler reads. These come from each handler's `config.get(...)` calls and match the shipped-TOML survey; remediation handlers are included.
- **Plugin step types** may pass `settings=`. If they don't, they get one warning per type per process: "settings for step type X are not checked".
- **Validation**: in `validate_step_authority` (passes) and in the remediation-handler validator (043), any step key outside common plus declared settings fails loading with `framework`, `control`, `step`, and key.
- **Control level**: `ControlConfig` becomes `extra="forbid"`; no shipped control uses extra keys. Templates and other sub-models keep their current behavior (out of scope).
- **Unregistered step types**: a step type that is not registered fails loading (FR-009). The one exception is an operator-supplied pass override or custom control (feature 040) that names a step type from a plugin that is not installed. There the control loads, and the orchestrator produces ERROR `missing_tool` with the cause "step type X is not registered" at dispatch, replacing today's skip. Dispatch never skips silently.

**Rationale**: FR-007, FR-008, FR-009.

**Alternatives considered**: `extra="forbid"` on `HandlerInvocation`, which cannot work because handler settings are pass-through by design. JSON-schema per handler, which is heavier than a key set for the same check.

## R6. Reproducibility checks become FAIL-only

**Decision**: Register all five reproducibility step types with `ceiling={"fail"}`. Their handlers already return INCONCLUSIVE when signals are absent. Where a handler today returns PASS on signals, 041's orchestrator treats an outcome outside the effective set as evidence only and continues to the control's later steps (`llm_eval` / `manual`), carrying the signals in evidence.

Review each handler for FAIL paths. For example, `repro_deps_pinned` FAILs when a manifest exists without a lockfile; that is proof of non-compliance and stays.

The corpus (`tests/darnit_baseline/corpus/` or the reproducibility test fixtures) gains a case: a workflow that mentions `cosign sign` in a comment, with no provenance, must not PASS. Expected outcomes that relied on PASS from signals are updated, with the reason given in the fixture.

The ceilings live in the framework's own `implementation.py`, so PR #532's rename carries them over unchanged.

**Rationale**: FR-010, FR-011, the clarification (all five), and 041's rule that presence and pattern steps conclude only FAIL.

**Alternatives considered**: `concludes = ["fail"]` per step in the TOML. That narrows per control, but a new control using the type would get PASS again; the registration ceiling covers every use.

## R7. Personal data from `/user`

**Decision**:
- Add a `gh_api` step setting `evidence_fields: list[str]`: top-level body keys to keep. When it is set, the stored `response.body` contains only those keys; the expression still evaluates against the full response in memory.
- OSPS-AC-01.01's `/user` step declares `evidence_fields = ["login", "two_factor_authentication"]`.
- Load-time rule: a `gh_api` step whose endpoint is `/user` or starts with `/users/` must declare `evidence_fields`; otherwise loading fails.
- Attestations and JSON output read evidence, so they inherit the redaction.

**Rationale**: FR-012. TOML-first, and generic for any future step reading a personal record.

**Alternatives considered**: Hard-coding a redaction list for `/user` in the handler, which is not TOML-first and misses `/users/{name}`. Dropping the step, which removes useful evidence for reviewers.

## R8. Shipped templates (#501)

**Decision**: Replace `file_must_exist` with `file_exists` (with `files =`) in `packages/darnit-hello/.../hello.toml`, `packages/darnit-example/.../example-hygiene.toml`, and the docs that teach it (`docs/packaging-plugins.md`, `docs/IMPLEMENTATION_GUIDE.md`, CLAUDE.md "Sieve Pattern" diagram). With R5 these templates would otherwise fail to load, and CI's plugin-discovery smoke loads `darnit-hello`.

## R9. Corpus and verification

**Decision**: Add false-PASS corpus cases (FR-013):
- an exec step whose expression cannot evaluate, from the zizmor-with-no-JSON reproduction;
- a plugin registering `manual` with a PASS ceiling, asserting refusal and no change in the outcome;
- a reproducibility text signal without provenance.

The existing gate already fails the build on any false PASS.

## R10. Compatibility

**Decision**:
- **Breaking, announced in the CHANGELOG**: third-party framework files with unknown keys or unregistered step types now fail to load, with the key or type named.
- **Not breaking**: plugin step types that don't declare settings only warn.
- **Behavior change**: reproducibility controls stop passing automatically.
- **Unchanged**: `gh_api` steps without `evidence_fields`, except personal-record endpoints.
