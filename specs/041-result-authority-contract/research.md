# Phase 0 Research: Result and Authority Contract

Decisions, rationale, and alternatives. Codebase references are to the `041-result-authority-contract` branch (stacked on feature 040).

## Current state (measured)

On a scratch repository with placeholder files (README "TODO", a SECURITY.md denying any process, placeholder governance/contributing/license files, a workflow with `permissions: write-all`), the sieve concludes PASS for DO-01.01, VM-02.01, GV-01.01, GV-03.01, LE-01.01, LE-03.01 (from `file_exists`) and VM-01.01, GV-01.02, AC-04.01, QA-06.01 (from `pattern`). No `llm_eval` step runs: in every `file_exists -> regex -> llm_eval` control the first dispositive step concludes, and the model is reached only when the pattern step found no files.

Of 65 OSPS controls (plus one reference control), classified against the upstream requirement text: 4 are existence-only (LE-03.01, QA-02.01, QA-05.01, QA-05.02; BR-05.01 is borderline and treated as content), 18 are platform settings, and 43 need content judgment. Today 14 controls conclude PASS from `file_exists` and 32 from `regex`/`pattern`; only 2 of each are existence-only.

## R1. Per-outcome authority on steps

- **Decision**: Authority becomes a set of outcomes a step may conclude, not one value per handler.
  - Each handler type registers a **ceiling** (the outcomes it can conclude). `file_exists`, `regex`/`pattern`: `{fail}`; with a step declared `existence = true`, `{pass, fail}`. `exec`: `{pass, fail}` (platform checks move to R3). `llm_eval`: `{}` (it produces candidates or suggestive findings, never a conclusion). `manual`: `{}`.
  - Each step may declare `concludes = [...]` to **narrow** the ceiling (default: the ceiling).
  - A step may exceed the ceiling only with a **promotion** (R6).
  - `resolve_step_result` concludes only when the step's outcome is in its effective set; otherwise the result is evidence and evaluation continues.
- **Rationale**: RFC-0001 September 2026 revision, "Authority is per claim, not per handler". Keeps the existing tighten-only rule and generalizes it from a scalar to a set.
- **Alternatives**: keep scalar authority and add per-control overrides (cannot express "may conclude FAIL but not PASS"); rely on reordering steps (does not stop a weak step from concluding PASS).

## R2. Pattern misses

- **Decision**: A pattern step with no match is INCONCLUSIVE unless the step declares `fail_on_miss = true`, which requires that FAIL be in its effective set.
- **Rationale**: The spec (FR-004) and `framework-design.md` 3.4 already describe inconclusive misses; the handler never implemented it.

## R3. Broken measurements are ERROR

- **Decision**:
  - Result statuses gain a first-class ERROR with a recorded cause (`error_class` already exists and is reused).
  - A new `gh_api` step type calls the platform API and sees the HTTP status: `fail_on_status` (for example `[404]` for "no branch protection") may conclude FAIL; 401, 403, 429, 5xx, and transport errors are ERROR. Platform checks currently written as `exec` + `gh api` + CEL move to this handler.
  - `exec`: a missing binary is ERROR; `fail_exit_codes` is honored only for commands that are not platform API calls.
  - `github_branch_protection`: 401/403/429 become ERROR with an error class instead of INCONCLUSIVE.
  - `mcp` step: a missing required server is ERROR, not FAIL.
- **Rationale**: `gh` exits 1 for 401, 403, 404, and 429 alike, so exit codes cannot separate "does not exist" from "not permitted". A status-aware handler is the only way to honor FR-007 and FR-008. The new handler must be documented in `framework-design.md` or `validate_sync` fails.
- **Alternatives**: parse `gh` stderr inside `exec` (fragile, couples a generic handler to one tool); treat every non-zero exit as ERROR (loses genuine "not configured" failures).

## R4. Result model and PASS candidates

- **Decision**:
  - Statuses: `PASS`, `FAIL`, `WARN`, `N/A`, `ERROR`, `PENDING`. `PENDING` replaces `PENDING_LLM` and carries `pending.kind` in `{llm_judgment, confirmation}`.
  - A PASS candidate is `PENDING` with `pending.kind = "confirmation"` and a `candidate` block (verdict, reasoning, cited evidence, model, model version, evidence digest).
  - A negative model judgment is `FAIL` with authority `suggestive` and `concluded_by = "llm_judgment"` (a model finding; non-compliant either way).
  - A confirmed candidate is `PASS` with authority `asserted`, `confirmed_by`, `confirmed_at`.
  - Level compliance stays in `calculate_compliance`; the harness stops computing its own and calls it.
- **Rationale**: A single PENDING with a kind keeps one non-compliant bucket for everything awaiting a model or a person, and avoids a seventh status that every consumer would need to learn. In-repo consumers (CLI, harness, formatters, attestation) are updated together; the MCP output change is recorded in the CHANGELOG.
- **Alternatives**: a separate `PASS_CANDIDATE` status (clearer name, one more status for every consumer); keeping `PENDING_LLM` (misnames candidates that await a person, not a model).

## R5. Model judgment validation

- **Decision**:
  - `LLMJudgment` gains `cited_evidence: list[str]` (verbatim excerpts), `model`, and `model_version`.
  - A positive judgment produces a candidate only if every cited excerpt appears verbatim in the content the step gathered (after whitespace normalization); otherwise it is recorded as an invalid judgment and the control stays WARN.
  - The candidate's evidence digest covers the gathered content and the control's rubric, so a confirmation lapses when either changes.
  - A model-service failure is ERROR for that step, not WARN.
- **Rationale**: FR-014; research on LLM judges shows verbatim quotes are necessary but not sufficient, which is why confirmation is still required (FR-011).

## R6. Promotions

- **Decision**: A step may exceed its ceiling only with `promotion = { outcome = "pass", corpus = "<corpus version>", note = "..." }` on the step in framework TOML. Loading rejects widening without a promotion. The corpus run (R7) independently fails if any step allowed to conclude PASS produces a false PASS, so a stale promotion is caught in CI.
- **Rationale**: Reviewable in the TOML diff (FR-020); enforcement does not depend on trusting the reference string.
- **Validation choke point**: authority validation today runs only in `control_from_effective`; the main MCP audit path (`load_controls_from_framework`) skips it. Validation moves to a single function called from every control-loading path, after plugin handlers register (schema validation cannot do it because plugin handlers register later).

## R7. Adversarial fixture corpus

- **Decision**:
  - Location: `tests/darnit_baseline/corpus/<fixture>/` (not under `tests/darnit/parity/`). Each fixture is a small file tree plus `labels.toml` mapping control IDs to an expected outcome: `PASS`, `FAIL`, `NOT_PASS` (anything but PASS is acceptable), or `N/A`, with a short rationale.
  - Platform-dependent controls use recorded platform responses served through a stub for the `gh_api` handler, so the corpus is offline and deterministic.
  - Runner: a pytest module that fails on any false PASS by a step allowed to conclude PASS (FR-018), plus `scripts/corpus_report.py` producing the per-step, per-outcome table (FR-017) as Markdown and JSON.
  - Initial fixtures: placeholder README; security policy denying a process; `write-all` workflow; placeholder governance, contributing, maintainers, and license files; empty repository (missing everything); a well-formed reference repository; platform scenarios (no branch protection, protection via ruleset, permission denied, rate limited).
- **Rationale**: The parity fixture format holds only whole-fixture counts; the corpus needs per-control labels. Keeping it out of `tests/darnit/parity/` avoids the parity guard.

## R8. Parity guard conflict

- **Decision**: Before this feature merges, a separate small change (#509) narrows the parity guard (`tests/darnit/parity/tier1/test_no_product_changes.py`) so it applies only when the parity harness (tier1/tier2 code) changes, not when a feature updates parity fixtures and their expected outcomes under `tests/darnit/parity/fixtures/`. This feature then updates parity expectations alongside the product changes that alter them.
- **Rationale**: The guard's heuristic ("touches parity tests" means "is a parity PR") blocks every feature that legitimately changes results. It already forced the feature-040 parity-fixture migration into a separate change.

## R9. Baseline re-declaration

- **Decision**: Every Baseline control's steps are re-declared: presence and pattern steps limited to FAIL except the 4 existence-only controls; platform checks moved to `gh_api` with `fail_on_status`; content controls end in `llm_eval` (PASS candidate) then `manual`. `inferred_from` is routed through the same rules, so an inferred PASS requires the source control's PASS to be conclusive under them.
- **Known mapping issues surfaced by labelling** (tracked separately, not fixed here): LE-01.01's upstream requirement is contributor sign-off enforcement while darnit checks for a LICENSE file; BR-01.02 is retired upstream (#495).

## R10. MCP judgment submission

- **Decision**:
  - New tool `submit_judgment(control_id, verdict, reasoning, cited_evidence, model, model_version, owner, repo[, host], local_path)`: re-gathers the control's evidence, applies R5, and records a candidate operator-side (reusing the feature-040 confirmation store with claim `pass_candidate`). The next audit reports the control as a PASS candidate; the existing confirmation tool confirms it.
  - The ActionPlan audit step no longer accepts client-supplied verdicts: `submit_action_result` for the audit step records only engine-produced results.
  - Agent skills stop instructing the agent to decide verdicts and instead call `submit_judgment` for pending controls.
- **Rationale**: FR-015; today `submit_action_result` accepts any client-reported status, and the audit and comply skills tell the agent to judge PASS or FAIL itself.

## Impact

Roughly 40 content controls will stop concluding PASS on real repositories until judgments are confirmed or steps are promoted. Goldens that pin current results (error-class baseline, CLI e2e zero-FAIL assertion, parity expectations) are regenerated as part of this feature.
