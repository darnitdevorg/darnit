# Implementation Plan: Close Remaining False-PASS Paths

**Branch**: `044-false-pass-paths` | **Date**: 2026-10-04 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/044-false-pass-paths/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Close the four remaining ways a control can PASS without evidence:

- **Expressions:** an expression that cannot be evaluated turns the step into ERROR (`evaluation`) instead of keeping its verdict. Expressions get usable project values and a repository-aware `file_exists`. A load-time check rejects references a step type does not provide.
- **Registration:** the registry refuses any plugin registration that would replace a built-in or another plugin's step type.
- **Strict loading:** step types declare the settings they accept. Unknown control and step keys, and unregistered step types, fail loading. A missing plugin type in operator-supplied controls becomes ERROR instead of a silent skip.
- **Reproducibility:** the five text/presence step types become FAIL-only, as 041 requires.
- **Personal data:** a new `evidence_fields` setting keeps the auditor's profile out of evidence and attestations.

The shipped templates that use an unregistered step type are fixed so they load. Design decisions are in [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.11/3.12 (workspace targets)

**Primary Dependencies**: existing only.
- `cel-python`, whose AST is used for the load-time reference check.
- `pydantic >= 2`, with `ControlConfig` moving to `extra="forbid"`.
- `gh` through the existing responder seam.

No new runtime dependencies.

**Storage**: none. Changes are confined to registration metadata, load-time validation, and evidence shape.

**Testing**:
- pytest, with framework TOML fixtures for the load errors.
- A zizmor stand-in on `PATH` (the pattern from 043's `test_plan_contract`).
- Recorded platform responses (`RecordedGhApi`).
- Test plugins registered in-process.
- The 041 false-PASS corpus gains cases.

**Target Platform**: unchanged.

**Project Type**: library, MCP server, and CLI.

**Performance Goals**: the load-time expression parse runs once per step per load, which is negligible next to an audit.

**Constraints**:
- Principle II: never PASS without evidence.
- Principle III: settings and `evidence_fields` live in TOML or registration, not in logic.
- Principle I: core changes are generic, and reproducibility changes stay inside its package, so they survive PR #532.
- Principle V: the expression is still a universal post-handler step in the orchestrator.
- `framework-design.md` is updated first.
- Breaking changes are announced in the CHANGELOG.
- ASCII only.

**Scale/Scope**:

| Item | Count |
|---|---|
| Built-in step types declaring settings | ~14 (check and remediation) |
| Shipped expressions | 21, all loading under the new check |
| Reproducibility registrations | 5 |
| Shipped control using `/user` | 1 |
| Templates to fix | 2 (`hello.toml`, `example-hygiene.toml`) |

Existing tests that pin the old behavior include `test_handler_registry`, the CEL post-step tests from feature 020, `test_builtin_handlers`, the reproducibility handler tests, and the corpus.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment | Status |
|---|---|---|
| I. Plugin Separation | All core changes are generic (registry, schema, orchestrator, `gh_api` setting). The reproducibility ceilings change in its own `implementation.py`, and Baseline only gains `evidence_fields` in TOML. No core import of implementations. "Missing implementations degrade gracefully" is kept: a missing plugin type is ERROR, never a crash. | Pass |
| II. Conservative-by-Default | Every change removes a PASS that lacked evidence; a broken expression is ERROR (non-compliant). | Pass |
| III. TOML-First Architecture | `evidence_fields` is TOML; settings are declared at registration next to the handler; strict loading enforces the TOML schema. | Pass |
| IV. Never Guess User Values | `project` in expressions holds only usable values; unconfirmed keys are evaluation errors. | Pass |
| V. Sieve Pipeline Integrity | "CEL `expr` fields are evaluated as a universal post-handler step in the orchestrator" is kept. "Each pass type MUST have well-defined PASS / FAIL / INCONCLUSIVE semantics" is strengthened by declared settings and an ERROR rule for broken expressions. | Pass |
| Development workflow | `framework-design.md` first (CEL table, step registration, strict loading, reproducibility ceilings); lint, tests, `validate_sync`. | Pass (planned) |

Post-design re-check: unchanged.

## Project Structure

### Documentation (this feature)

```text
specs/044-false-pass-paths/
|-- plan.md
|-- research.md          # R1-R10
|-- data-model.md
|-- quickstart.md        # V1-V6
|-- contracts/
|   `-- step-contract.md
|-- checklists/
|   `-- requirements.md
`-- tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
packages/darnit/src/darnit/
|-- sieve/
|   |-- orchestrator.py        # _apply_cel_expr: ERROR on failure; project + repo_path; ERROR missing_tool at dispatch
|   |-- handler_registry.py    # settings, expression_names, refused_registrations, collision refusal
|   |-- cel_evaluator.py       # free-identifier extraction helper (macro-bound names excluded)
|   `-- builtin_handlers.py    # settings/expression_names on every built-in; gh_api evidence_fields
`-- config/
    |-- framework_schema.py    # ControlConfig extra="forbid"
    `-- control_loader.py      # validate_step_authority: unknown keys, unregistered types, expr references, /user rule

packages/darnit-reproducibility/src/darnit_reproducibility/implementation.py   # ceiling={"fail"} x5
packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml             # AC-01.01 /user evidence_fields
packages/darnit-hello/.../hello.toml, packages/darnit-example/.../example-hygiene.toml   # file_must_exist -> file_exists

docs/architecture/framework-design.md, CLAUDE.md, docs/packaging-plugins.md, docs/IMPLEMENTATION_GUIDE.md
tests/darnit_baseline/corpus/  # new false-PASS cases
```

**Structure Decision**: Single Python workspace. Validation concentrates in `validate_step_authority`, which already runs after plugins register, so one function knows every registered step type.

## Sequencing and dependencies

1. `framework-design.md`:
   - the CEL table (names per step type), failure leading to ERROR;
   - step registration (`settings`, `expression_names`, collision refusal);
   - strict loading;
   - reproducibility ceilings;
   - `evidence_fields`.
2. Registry: `settings`, `expression_names`, collision refusal (US2), with built-in declarations.
3. Templates (#501) fixed before strict loading is turned on.
4. Strict loading: control schema, step keys, unregistered types, expression references (US2, US1 scenario 6).
5. Orchestrator: expression failure is ERROR, plus `project` and `repo_path`, and ERROR `missing_tool` at dispatch (US1, US2).
6. Reproducibility ceilings, with test and corpus updates (US3).
7. `gh_api` `evidence_fields` and the AC-01.01 TOML (US4).
8. Corpus cases, CHANGELOG (breaking), docs, quickstart.

Steps 2-4 come before 5 so the orchestrator change runs against validated configurations. Step 6 is independent of 2-5. Step 7 depends only on step 2 (settings for `gh_api`).

## Follow-ups (out of scope)

- Real verification for reproducibility properties, e.g. checking that provenance is actually published, to restore automatic PASS with evidence.
- Strictness for non-control sub-models (templates, context definitions).
- #442 (control registry leaking across frameworks in one process).

## Complexity Tracking

No constitution violations; no entries.
