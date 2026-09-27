# Implementation Plan: Result and Authority Contract

**Branch**: `041-result-authority-contract` | **Date**: 2026-09-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/041-result-authority-contract/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Replace per-handler authority with per-step, per-outcome authority: each step type registers a ceiling (presence and pattern steps: FAIL only unless the requirement is existence), steps may narrow it, and only a recorded promotion widens it. Pattern misses become inconclusive; platform errors, missing tools, and model-service failures become ERROR with a cause; a new status-aware `gh_api` step lets "does not exist" prove FAIL while auth and rate-limit responses do not. Model judgments never conclude PASS: a positive judgment with verified verbatim citations becomes a PASS candidate that the operator confirms (feature 040 confirmation store), after which the result is an asserted PASS; negative judgments are suggestive FAILs. Coding agents submit judgments through a new `submit_judgment` MCP tool, and the ActionPlan audit step stops accepting client verdicts. An adversarial fixture corpus with per-control labels measures every step and fails CI on any false PASS by a step allowed to conclude PASS. The OpenSSF Baseline controls are re-declared under these rules. Design decisions are in [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.11/3.12 (workspace targets)

**Primary Dependencies**: existing only -- `pydantic >= 2` (models, `extra="forbid"`), `cel-python` (CEL), `pydantic-ai-slim[anthropic]` behind the `LLMStep` protocol, `gh` CLI for platform calls. No new runtime dependencies.

**Storage**: Filesystem. PASS candidates and confirmations use the feature 040 operator-side store. Corpus fixtures are files under `tests/darnit_baseline/corpus/`.

**Testing**: pytest; corpus runner as a pytest module plus `scripts/corpus_report.py`; platform scenarios via recorded responses served to the `gh_api` handler; harness judgments via `MockLLMStep`.

**Target Platform**: Linux, macOS, Windows (unchanged).

**Project Type**: Library + CLI + MCP server + headless harness.

**Performance Goals**: The corpus runs offline in CI in under 2 minutes; per-audit overhead of authority resolution is negligible.

**Constraints**: Conservative-by-default (Principle II); steps still run in order and the first conclusive result wins (Principle V); `framework-design.md` updated first and `validate_sync` passing (new `gh_api` handler must be documented); ASCII-only docs; deterministic-only runs remain test tooling (#505).

**Scale/Scope**: 65 OSPS controls re-declared (4 existence-only, 18 platform, 43 content); about 40 content controls stop concluding PASS on real repositories until judgments are confirmed or steps are promoted; goldens regenerated (error-class baseline, CLI e2e, parity expectations).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment | Status |
|---|---|---|
| I. Plugin Separation | Ceilings are registered by handlers; core defines the rules and never imports implementations. The Baseline re-declaration is TOML in the implementation package; `github_branch_protection` stays in the implementation. | Pass |
| II. Conservative-by-Default | Weak steps cannot PASS; misses and errors never become PASS; PENDING, WARN, ERROR, and candidates are non-compliant; promotion requires zero false PASS. | Pass |
| III. TOML-First Architecture | Step declarations, promotions, and platform failure statuses are TOML; corpus labels are data. | Pass |
| IV. Never Guess User Values | Unchanged; candidates require explicit operator confirmation, which records who and when. | Pass |
| V. Sieve Pipeline Integrity | Order and first-conclusive-wins preserved; what counts as conclusive now depends on the step's declared outcomes. The constitution's description of the sieve needs a matching wording update (governance change, see follow-ups). | Pass (wording follow-up) |
| Architecture constraints | The constitution lists `file_must_exist`; the real handler is `file_exists` (#501). Unaffected here. | Pass |
| Development workflow | `framework-design.md` first; lint, tests, `validate_sync`. | Pass (planned) |

Post-design re-check: unchanged.

## Project Structure

### Documentation (this feature)

```text
specs/041-result-authority-contract/
|-- plan.md
|-- research.md          # R1-R10
|-- data-model.md        # ceilings, step declarations, results, candidates, corpus
|-- quickstart.md
|-- contracts/
|   |-- step-declarations.md
|   `-- results-and-judgments.md
|-- checklists/
|   `-- requirements.md
`-- tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
packages/darnit/src/darnit/
|-- sieve/
|   |-- handler_registry.py     # ceilings (set of outcomes, existence_ceiling) replace scalar default_authority
|   |-- builtin_handlers.py     # pattern miss inconclusive (+ fail_on_miss); exec missing tool = ERROR;
|   |                           # new gh_api handler (status-aware); mcp missing server = ERROR
|   |-- orchestrator.py         # resolve by effective outcome set; ERROR propagation; judgments -> candidate /
|   |                           # suggestive FAIL / ERROR; inferred_from through the same rules
|   `-- models.py               # statuses (PENDING replaces PENDING_LLM), error, pending, candidate fields
|-- config/
|   |-- framework_schema.py     # step fields: concludes, existence, fail_on_miss, fail_on_status, promotion
|   `-- control_loader.py       # one authority validation called from every loading path
|-- core/llm_step.py            # LLMJudgment: cited_evidence, model, model_version
|-- trust/judgments.py          # NEW: citation verification, evidence digest, candidate record/lookup (040 store)
|-- tools/audit.py              # candidates/confirmations applied to results; calculate_compliance unchanged rule
|-- harness/driver.py           # uses calculate_compliance; model failure = ERROR; judgments via trust/judgments
|-- server/tools/judgments.py   # NEW: submit_judgment MCP tool
|-- server/tools/harness_loop.py, core/action_plan.py  # audit step no longer accepts client verdicts
`-- skills/darnit-audit, darnit-comply  # submit_judgment instead of agent verdicts

packages/darnit-baseline/src/darnit_baseline/
|-- openssf-baseline.toml       # re-declared steps (existence, gh_api + fail_on_status, llm_eval candidates)
|-- branch_protection.py        # 401/403/429 -> ERROR with class
`-- attestation/predicate.py    # PENDING/candidate/asserted labels in the predicate

scripts/corpus_report.py        # NEW: per-step/outcome report (Markdown, JSON)
tests/darnit_baseline/corpus/   # NEW: fixtures + labels.toml; test_corpus.py runner
tests/darnit/parity/tier1/test_no_product_changes.py  # narrowed in a separate prior change (R8)
docs/architecture/framework-design.md                 # updated first: ceilings, gh_api, statuses, candidates
```

**Structure Decision**: Single Python workspace; changes concentrate in the sieve (registry, handlers, orchestrator, models), config validation, and a new `trust/judgments.py`; the Baseline implementation changes its TOML, one handler, and attestation labels.

## Sequencing and dependencies

1. **Prerequisite (separate change)**: narrow the parity guard so feature PRs may update parity expectations (R8, #509).
2. `framework-design.md` update.
3. Result model and ceilings (models, registry, orchestrator resolution, load-time validation in every path).
4. Handlers: pattern miss, exec/mcp errors, `gh_api`, branch-protection errors.
5. Judgments: `LLMJudgment` fields, citation verification, candidates via the 040 store, harness wiring and compliance, `submit_judgment`, ActionPlan change, skills.
6. Corpus: fixtures, labels, runner, report script, CI job.
7. Baseline re-declaration, driven by corpus results; goldens regenerated.
8. Attestation labels; CHANGELOG; docs.

## Follow-ups (out of scope)

- Evidence gathering for model judgments (#485): what content is gathered, truncation, batching.
- Engine-held run state and pending tasks (RFC-0001 Stage 2); `submit_judgment` here is per-control and stateless.
- Constitution wording for Principle V to describe per-step, per-outcome conclusions (governance change).
- LE-01.01 control mapping (upstream requirement is contributor sign-off, darnit checks for a LICENSE file); BR-01.02 retirement (#495).
- Publishing the corpus as a shared asset (RFC-0001 open question 8).

## Complexity Tracking

No constitution violations; no entries.
