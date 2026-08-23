# Implementation Plan: Ruleset-aware branch-protection verdict

**Branch**: `032-ruleset-branch-protection` | **Date**: 2026-08-22 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/032-ruleset-branch-protection/spec.md` (with 3 clarifications recorded 2026-08-22: consult-rulesets whenever classic surface did not itself provide the required signal; distinguish HTTP status classes via shared helper enhancement; use `gh api --paginate` and WARN on any page-fetch failure).

## Summary

Extend the four OSPS branch-protection controls (`OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`) to consult the GitHub Repository Rulesets API surface in addition to the classic `/branches/{branch}/protection` endpoint. A repo whose default branch is protected via a ruleset (rather than classic branch protection) currently produces false FAILs from all four controls; that regression, introduced when feature 019 tightened the 404-means-not-protected verdict, is corrected here without weakening the FAIL semantics for genuinely non-compliant repos or the WARN semantics for ambiguous responses.

Implementation lives entirely inside `packages/darnit-baseline/`. A new sieve handler `github_branch_protection` (registered by the baseline plugin) encapsulates the two-surface check. The four TOML controls' first pass switches from `exec` on `gh api /branches/{branch}/protection` to `handler = "github_branch_protection"` with a `requirement` parameter naming which protection is being tested for. The trailing manual pass on each control is unchanged. A small shared helper enhancement in `packages/darnit/src/darnit/core/utils.py` (a status-code-aware sibling of `gh_api`) is added so both the classic and the rulesets calls can distinguish 200 / 404 / other-non-200 rather than collapsing everything into `RuntimeError`. The helper enhancement is scoped and reusable by any future control that needs the same WARN/FAIL boundary.

Zero new runtime dependencies. Zero controls outside the named four change behavior.

## Technical Context

**Language/Version**: Python 3.11/3.12 (workspace targets - unchanged).

**Primary Dependencies**: `gh` CLI (already required for the classic-protection pass and for other baseline controls); Pydantic 2.x (already used for framework schema); no new pip dependencies.

**Storage**: Filesystem only. No new persistent state; the two GitHub API responses are consumed per-invocation and their salient fields recorded in the control's evidence dict for the audit report.

**Testing**: pytest under `tests/darnit_baseline/`. The handler tests mock the shared `gh_api` helper directly (function-level substitution) rather than mocking `subprocess.run`, so the tests remain robust across `gh` CLI version changes. Live-integration tests against a real repo are out of scope for CI (they require network + a specifically-configured fixture repo) but the quickstart documents how to run them manually.

**Target Platform**: Same as darnit workspace - any platform Python 3.11+ runs on. `gh` CLI must be on PATH; already required by peer controls.

**Project Type**: Compliance-implementation-package change. Scoped to `packages/darnit-baseline/` (new handler + TOML edits + tests) with one small enhancement to `packages/darnit/src/darnit/core/utils.py` (shared helper).

**Performance Goals**: Not a hot path; API calls are network-bound by definition. Spec's SC-004 caps API calls per audit at 1 classic-endpoint call + `ceil(N/page_size)` rulesets-list calls + N detail calls per repository, where N is the ruleset count. The default-branch value is consumed from `context.default_branch` (populated by the audit driver at `packages/darnit/src/darnit/tools/audit.py:428`), NOT via an extra `GET /repos/{owner}/{repo}` call. In practice: for a typical repo with 0-2 rulesets, this feature adds at most 3 API calls per repo beyond the classic call feature 019 already made.

**Constraints**:
- Zero new runtime dependencies (FR-013).
- No behavior change for non-GitHub audits (existing `when = { platform = "github" }` guards remain, FR-010).
- Evidence-record additions MUST be additive (existing fields preserved; new `source` field added, FR-016).
- Preserve WARN semantics on ambiguous surface responses (FR-006, User Story 3).
- Preserve FAIL semantics when both surfaces confirm no protection (FR-005, User Story 2).
- Only rulesets with `enforcement = "active"` count (FR-012).

**Scale/Scope**: One new sieve handler in baseline (~200-300 lines including tests-side fixtures); one shared helper enhancement in core (~30-50 lines); four TOML controls updated in place (~40 lines of TOML edits net-zero); ~500-800 lines of new test code. Estimated diff: ~1000 lines total.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The darnit constitution (5 core principles) evaluated against this feature:

| Principle | Applies | Assessment |
|-----------|---------|------------|
| I. Plugin Separation | Yes | PASS. The `github_branch_protection` handler lives in `darnit-baseline` (implementation), NOT in `darnit` core. The shared helper enhancement in `darnit.core.utils` is a framework-level utility that does not import implementation packages. Core -> implementation direction remains one-way. |
| II. Conservative-by-Default | Yes | PASS. This entire feature is a Conservative-by-Default correction: the current code produces a false FAIL for a compliant repo, which is the exact class of error the principle forbids. FR-005 (FAIL only when BOTH surfaces respond and NEITHER protects) and FR-006 (WARN on ANY ambiguity) tighten the WARN/FAIL boundary. |
| III. TOML-First Architecture | Yes | PASS. The four affected controls' passes remain fully declared in TOML. The new handler is invoked declaratively via `handler = "github_branch_protection"` and a `requirement = "..."` parameter, matching the same TOML-first pattern as `exec` and `api_call`. No Python-code path for control logic is introduced. |
| IV. Never Guess User Values | Yes | PASS. Branch protection status is an OBSERVATION (query external API for ground truth), not a user-judgment key. The handler produces `dispositive` results by default. No candidate/confirm mechanism is involved. |
| V. Sieve Pipeline Integrity | Yes | PASS. The handler returns a single `HandlerResult`; orchestrator's disposition logic is unchanged. An INCONCLUSIVE result (WARN cause) correctly falls through to the trailing manual pass, matching feature 019's already-shipped semantic. CEL post-step is not used by this handler because the handler already produces its own PASS/FAIL/INCONCLUSIVE verdict; the classic-only exec pass being replaced was where the CEL post-step lived (a CEL over the JSON response). |

Architecture constraints (three-layer architecture, package structure): PASS. Layer 1 (Checking) gains a new baseline-registered handler; Layer 2 (Remediation) is unchanged; Layer 3 (MCP Tools) is unchanged.

Development workflow (lint, tests, spec sync): PASS. Standard workflow. No new gates required. The spec-sync check (`validate_sync.py`) validates handler names in code against `docs/architecture/framework-design.md`; the new handler must be added to that document (T050 in the tasks plan).

**Gate result: PASS. Proceed to Phase 0.**

## Project Structure

### Documentation (this feature)

```text
specs/032-ruleset-branch-protection/
├── plan.md              # This file
├── research.md          # Phase 0 output - gh stderr format, rulesets JSON shape, testing approach
├── data-model.md        # Phase 1 output - ProtectionRequirement enum, evidence record, helper return type
├── quickstart.md        # Phase 1 output - control-author + operator debugging examples
├── contracts/
│   └── github-branch-protection-handler.md   # Phase 1 output - TOML surface + evidence shape
├── checklists/
│   └── requirements.md  # From /speckit-specify (all 16 items pass)
└── tasks.md             # /speckit-tasks output (not created here)
```

### Source Code (repository root)

```text
packages/darnit/src/darnit/core/
└── utils.py            # Extend with `gh_api_with_status()` returning (body, status_code, error_msg) tuple.
                        # Existing `gh_api()` and `gh_api_safe()` remain unchanged callers.

packages/darnit-baseline/src/darnit_baseline/
├── branch_protection.py  # NEW. `github_branch_protection` sieve handler + ProtectionRequirement enum
│                         # + ruleset-matching helpers. All feature-specific logic lives here.
├── implementation.py     # Register the new sieve handler in `register_handlers()` (small addition).
└── openssf-baseline.toml # UPDATE 4 controls' first pass from exec-to-handler; unchanged manual passes.

tests/darnit_baseline/
├── test_branch_protection_handler.py  # NEW. Unit tests: each requirement type against
│                                       # classic-only, ruleset-only, both-surfaces, both-ambiguous,
│                                       # exclude-conditions, evaluate-mode ruleset, empty rules array,
│                                       # partial-fetch failure, pagination.
└── test_branch_protection_integration.py  # NEW. Integration tests through the sieve orchestrator
                                            # for the four TOML controls (one test per control).

tests/darnit/
└── core/test_gh_api_status.py  # NEW. Unit tests for the new `gh_api_with_status()` helper:
                                 # 200/404/403/5xx status extraction from gh stderr.

docs/architecture/
└── framework-design.md         # Small edit adding the new handler name to the registry table
                                 # so `validate_sync.py` passes.
```

**Structure Decision**: Keep the whole feature footprint inside `packages/darnit-baseline/` except for the tiny shared-helper enhancement, which properly belongs in core because it's transport infrastructure any future implementation can reuse. Splitting the new logic into its own `branch_protection.py` module inside baseline (rather than piling into `tools.py`) improves reviewability and creates a natural extension point when we generalize beyond these four controls or add organization-level ruleset support (v0.1 follow-up per the spec).

## Complexity Tracking

No constitution violations to justify. The feature is a scoped handler addition with zero new architectural surface.

## Phase 0: Research

Research questions surfaced by Technical Context and the spec's Assumptions/Edge Cases:

1. **What is `gh`'s stderr format on HTTP-error non-zero exits?** — The stderr output on a non-2xx response follows the pattern `HTTP <code>: <message>` (e.g., `HTTP 404: Not Found (https://api.github.com/...)`). Verifiable by manually running `gh api /repos/nonexistent/nonexistent 2>&1`. Research decision: parse the first-line prefix with a compiled regex `^HTTP (\d{3}):`. Fallback: absent the pattern (e.g., network error before the request completed), treat as ambiguous status and resolve WARN per FR-006. This matches the shared helper's contract from FR-017.

2. **What is the JSON shape of a ruleset list vs a ruleset detail?** — `GET /repos/{owner}/{repo}/rulesets` returns an array of ruleset summaries: `[{"id": N, "name": "...", "target": "branch", "enforcement": "active|evaluate|disabled", "source_type": "Repository", ...}, ...]`. The summary does NOT include `rules` or `conditions`; those require `GET /repos/{owner}/{repo}/rulesets/{id}` (detail fetch). Research decision: v0 fetches every ruleset's detail (bounded by SC-004's `N` where N is the ruleset count); we do NOT prematurely filter by summary-level `enforcement` because a maintainer may re-enable a ruleset between the list and detail calls and we care about the state at detail-fetch time. Detail response carries `conditions.ref_name.include: [...]`, `conditions.ref_name.exclude: [...]`, and `rules: [{"type": "pull_request", "parameters": {"required_approving_review_count": 1, ...}}, ...]`. Ruleset rule types relevant to this feature: `pull_request`, `deletion`, `required_status_checks`, `non_fast_forward`. Full type list documented at [GitHub's ruleset schema docs](https://docs.github.com/en/rest/repos/rules).

3. **How is the `ref_name` targeting field structured, and what forms does `include` take?** — Values in the `include` list are one of: `~DEFAULT_BRANCH` (the pseudo-ref that resolves to the repository's default branch at evaluation time), `~ALL` (all refs), an exact `refs/heads/<name>` git-ref, or a bare branch name like `main`. Glob patterns (e.g., `refs/heads/release/*`) are allowed but not evaluated in v0 (treated as "does not match" per the spec's Edge Cases). Research decision: matching function accepts `(branch: str, default_branch: str)` and returns True for `~DEFAULT_BRANCH` iff `branch == default_branch`, True for `~ALL`, True for exact branch name matches, and False otherwise (including all patterns). Absence of the audited branch in `exclude` is a precondition for a match.

4. **What is the naming convention for baseline sieve handlers?** — Existing precedent: `generate_threat_model_handler` (registered under the short name via the sieve registry). Research decision: register the new handler under the short name `github_branch_protection`. Rationale: matches the domain (GitHub branch-protection surfaces), leaves room for a future `gitlab_branch_protection` if we ever add that platform, and follows the same underscore-separated verb-noun pattern as `file_exists` and `api_call`. The handler function itself is named `github_branch_protection_handler` in `branch_protection.py`.

5. **What is the shape of the shared helper enhancement?** — Two options considered: (a) new function `gh_api_with_status(endpoint) -> tuple[dict | None, int, str]`, (b) enhance the existing `gh_api` to raise a typed exception carrying the status code. Option (a) wins because (a) it does not change any of the ~30 existing `gh_api` / `gh_api_safe` callers, (b) it makes the "I care about status codes" intent explicit at call sites, and (c) it composes cleanly: `gh_api` and `gh_api_safe` remain thin wrappers over `gh_api_with_status`. Return contract: on 2xx, `(body_dict, status, "")`; on non-2xx with parseable status, `(None, status, stderr_message)`; on `FileNotFoundError` (gh CLI missing) or other exception before/without a parseable status, `(None, 0, error_message)`.

6. **How do existing baseline handler tests mock the GitHub API?** — Reviewing `tests/darnit_baseline/` shows the convention: tests mock at the module-level function (`monkeypatch.setattr(module, "gh_api_safe", fake_fn)`). Research decision: the handler tests substitute `darnit_baseline.branch_protection.gh_api_with_status` with a mock that returns pre-canned `(body, status, message)` tuples for each `(endpoint_pattern, expected_call_index)` pair. This lets tests exercise the exact API-call-order the handler emits without mocking `subprocess.run`, avoiding `gh`-version fragility. A small `_GhResponseSequencer` fixture in the test module encapsulates the pattern.

**Output**: `research.md` documenting each decision with rationale and rejected alternatives.

## Phase 1: Design & Contracts

**Prerequisites**: `research.md` complete.

### Data Model (`data-model.md`)

New schema types and their relationships:

- **`ProtectionRequirement`** (str Enum in `branch_protection.py`): the requirement a control tests for. Members: `REQUIRE_PULL_REQUEST`, `PREVENT_DELETION`, `REQUIRE_STATUS_CHECKS`, `REQUIRE_APPROVALS`. Set via TOML `requirement = "..."` on the handler pass. Extension point for future requirements without changing the handler dispatch.

- **`RequiredApprovalsMinimum`** (int on the handler config, default 1): For `REQUIRE_APPROVALS` requirement, the minimum `required_approving_review_count` that satisfies. Defaults to 1 to match `OSPS-QA-07.01`'s existing semantic.

- **`RulesetSummary`** (TypedDict, runtime-only in `branch_protection.py`): The shape of the list-response items we care about (`id`, `name`, `target`, `enforcement`). Total-only; we don't type the full ruleset schema because we treat unknown fields as opaque.

- **`RulesetDetail`** (TypedDict, runtime-only): The shape of the detail-response fields we care about (`id`, `name`, `enforcement`, `conditions.ref_name.{include,exclude}`, `rules: list[{type, parameters}]`).

- **`VerdictSource`** (str Enum, in `branch_protection.py`): The enumerated evidence-source values from spec FR-016. Members: `CLASSIC` (verdict from classic surface alone), `RULESET` (verdict from a specific ruleset), `NEITHER_SURFACE_PROVIDED_PROTECTION` (both surfaces answered, neither protects), `INSUFFICIENT_ACCESS` (either surface returned 401/403), `PARTIAL_FETCH` (list succeeded but a detail or a subsequent page failed).

- **Handler evidence record** (dict shape): the evidence dict written into `HandlerResult.evidence` by the handler. Keys: `source: str` (a `VerdictSource` value), `classic_status: int` (status code from the classic-endpoint call, `0` if the call was skipped), `rulesets_status: int` (status from the list call, `0` if skipped), `matched_ruleset: {"id": int, "name": str} | None` (populated when `source == RULESET`), `considered_rulesets: list[{"id": int, "name": str}]` (populated on FAIL; enumerates every active ruleset that targets the branch but did not satisfy the requirement; capped at 20 entries with a `truncated: N` suffix), `requirement: str` (the ProtectionRequirement that was tested for).

  Capping the `considered_rulesets` list at 20 addresses the plan-time deferral from the clarification session: it prevents a rare high-ruleset repo from bloating the evidence record while preserving the information needed to explain the FAIL to a human. A repo with more than 20 non-satisfying active rulesets is pathological.

- **`gh_api_with_status`** (new function in `darnit.core.utils`): return type `tuple[dict | list | None, int, str]`. First element is the parsed JSON body (dict OR list; rulesets endpoint returns a list at the top level), second is HTTP status (0 if unparseable), third is the stderr text on error. Existing `gh_api()` becomes `body, status, msg = gh_api_with_status(endpoint); if status != 200: raise RuntimeError(msg)` (thin wrapper). Existing `gh_api_safe()` similarly.

### Contracts (`contracts/github-branch-protection-handler.md`)

The public control-author API. Contents:

- **TOML pass surface**: exact field list for `handler = "github_branch_protection"`. Fields: `owner` (default `$OWNER`), `repo` (default `$REPO`), `branch` (default `$BRANCH`), `requirement` (required; one of the four enum values), `required_approvals_minimum` (optional, default 1, only meaningful when requirement is `REQUIRE_APPROVALS`), `timeout` (optional, default 30 seconds; total budget across both surfaces including pagination).

- **Evidence shape**: the fields the handler writes into `HandlerResult.evidence` per the data model above. Downstream evidence-readers (Markdown formatter, JSON output, SARIF) treat unknown keys as opaque, matching feature 019's evidence-additive posture.

- **Progress-log shape**: none. The handler runs in the same dispatch step as other sieve handlers; no per-surface INFO line is emitted (matches `file_exists`, `exec`, `api_call`). Feature 031's `dispatching_mcp` is a separate concept because that pool is orchestrator-owned; here the handler runs synchronously within the sieve step.

- **Failure modes**: exhaustive table mapping every distinguishable scenario to (control status, source enum value, message).

- **Non-goals for v0**: (a) organization-level rulesets (v0.1 follow-up); (b) generalizing beyond the four named controls; (c) evaluate-mode ruleset counting; (d) glob-pattern ref_name matching.

### Quickstart (`quickstart.md`)

Two worked examples:

1. **Control author perspective**: rewriting `OSPS-AC-03.01`'s first pass from the old exec form to the new handler form. Includes the exact TOML diff, the expected evidence-record output for a repo protected via a ruleset, and the expected evidence output for a repo with no protection at either surface.

2. **Operator debugging perspective**: an audit produced WARN on `OSPS-QA-07.01`. Read the evidence record, see `source: "insufficient-access"` and `rulesets_status: 403`. Fix: reauthenticate `gh` with `admin:read` scope. Alternate scenario: `source: "partial-fetch"` and `rulesets_status: 429` — fix: rerun after rate-limit window resets.

Also includes the "failure-mode diagnostics" section: how to interpret each failure-status message from the contract.

### Agent Context Update

Update the reference between `<!-- SPECKIT START -->` and `<!-- SPECKIT END -->` markers in `CLAUDE.md` to point at `specs/032-ruleset-branch-protection/plan.md`.

## Post-Design Constitution Recheck

The design phase artifacts do not introduce any new principle-touching decisions:

- **I. Plugin Separation**: reinforced by the module layout — the handler is under `darnit-baseline/`, not `darnit/`. The `gh_api_with_status` addition is a pure transport primitive in `darnit.core.utils` with no implementation-package imports.
- **II. Conservative-by-Default**: reinforced by the `VerdictSource` enum's inclusion of `INSUFFICIENT_ACCESS` and `PARTIAL_FETCH` as first-class WARN causes — the framework will never conflate "we could not tell" with "we know it fails."
- **III. TOML-First**: reinforced by the exact TOML surface documented in the reader contract; the handler adds no new Python-code escape hatch.
- **IV. Never Guess User Values**: reinforced by the fact that branch protection is an observation, not a candidate; no `auto_detect` / `allow_sieve_hints` machinery is touched.
- **V. Sieve Pipeline Integrity**: reinforced by the handler returning a single `HandlerResult` and using the trailing manual pass as the natural INCONCLUSIVE fallback.

**Post-design gate: PASS.**
