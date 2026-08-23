---
description: "Task list for feature 032-ruleset-branch-protection"
---

# Tasks: Ruleset-aware branch-protection verdict

**Input**: Design documents in `specs/032-ruleset-branch-protection/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/github-branch-protection-handler.md](./contracts/github-branch-protection-handler.md), [quickstart.md](./quickstart.md).

**Tests**: Included. Spec SC-004 (API-call budget) and SC-005 (zero cost when the four controls are excluded) both require mock-transport-counting tests that assert on exact call sequences. Every user story's Independent Test requires a fixture-driven behavior test. Tests are load-bearing.

**Organization**: One phase per user story after Setup + Foundational. Every user-story task carries a `[USn]` label. Cross-story files (`utils.py` helper tests, framework-design.md sync) are only touched in Setup / Foundational / Polish.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks).
- **[Story]**: `[US1]`, `[US2]`, `[US3]` matching spec's user stories.
- File paths are absolute-from-repo-root.

## Path Conventions

Single workspace repo. New product code under `packages/darnit-baseline/src/darnit_baseline/branch_protection.py`. One shared helper enhancement under `packages/darnit/src/darnit/core/utils.py`. TOML edits under `packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml`. New tests under `tests/darnit_baseline/test_branch_protection_handler.py`, `tests/darnit_baseline/test_branch_protection_integration.py`, and `tests/darnit/core/test_gh_api_status.py`.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Introduce the new module file the rest of the feature builds on, plus the handler-name registry entry so the spec-sync check finds it once code lands.

- [X] T001 Create `packages/darnit-baseline/src/darnit_baseline/branch_protection.py` with a module docstring naming its purpose (ruleset-aware branch-protection verdict handler; encapsulates classic + rulesets two-surface check for OSPS-AC-03.01 / -03.02 / OSPS-QA-03.01 / OSPS-QA-07.01), the constants `MAX_CONSIDERED_RULESETS = 20`, `DEFAULT_TIMEOUT_SECONDS = 30`, `SUPPORTED_REF_INCLUDE_LITERALS = frozenset({"~DEFAULT_BRANCH", "~ALL"})`, empty declarations for `ProtectionRequirement`, `VerdictSource`, and stub `github_branch_protection_handler(config, context) -> HandlerResult` returning `HandlerResult(status=INCONCLUSIVE, message="not implemented")`. No behavior; scaffold only. Phase 2 fills in body.

- [X] T002 Add `github_branch_protection` to the handler-name registry table in `docs/architecture/framework-design.md`. Place under the "Sieve handlers (implementation-registered)" section alongside `generate_threat_model`. One-line entry naming the short name, the registering package (`darnit-baseline`), and the docs link (`specs/032-ruleset-branch-protection/contracts/github-branch-protection-handler.md`). Required by `scripts/validate_sync.py`'s handler-name check (T059).

**Checkpoint**: Module skeleton exists and the spec-sync validator will find the new handler name once T011 wires registration. No behavior yet.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared-helper enhancement and the internal helper functions every user story depends on. Nothing US1-through-US3 can be implemented until these land, because the handler cannot distinguish 200/404/other-non-200 without the enhanced helper and cannot match rulesets without the ref-name helper.

**CRITICAL**: No user story work begins until this phase completes.

- [X] T003 Implement `gh_api_with_status(endpoint: str, *, paginate: bool = False) -> tuple[dict | list | None, int, str]` in `packages/darnit/src/darnit/core/utils.py`. On 2xx: `(parsed_json, status_code, "")`. On non-2xx with parseable `HTTP <code>:` prefix in stderr: `(None, status_code, stderr_message)`. On any other failure (subprocess `FileNotFoundError`, `JSONDecodeError` on a 2xx body, network error before request completed): `(None, 0, error_message)`. When `paginate=True`, invoke `gh api --paginate <endpoint>` and let `gh` concatenate all pages (top-level JSON array). Refactor existing `gh_api()` to be a thin wrapper: call `gh_api_with_status(endpoint)`, raise `RuntimeError(msg or f"status {status}")` on non-200 or non-dict body. Refactor `gh_api_safe()` similarly. All existing callers MUST continue to work unchanged.

- [X] T004 Implement the `ProtectionRequirement` and `VerdictSource` str enums in `packages/darnit-baseline/src/darnit_baseline/branch_protection.py` per [data-model.md](./data-model.md). ProtectionRequirement members: `REQUIRE_PULL_REQUEST` (value `"require_pull_request"`), `PREVENT_DELETION` (`"prevent_deletion"`), `REQUIRE_STATUS_CHECKS` (`"require_status_checks"`), `REQUIRE_APPROVALS` (`"require_approvals"`). VerdictSource members: `CLASSIC` (`"classic"`), `RULESET` (`"ruleset"`), `NEITHER_SURFACE_PROVIDED_PROTECTION` (`"neither-surface-provided-protection"`), `INSUFFICIENT_ACCESS` (`"insufficient-access"`), `PARTIAL_FETCH` (`"partial-fetch"`).

- [X] T005 Implement `_ref_name_matches(branch: str, default_branch: str | None, include: list[str], exclude: list[str]) -> bool` in `branch_protection.py`. Return True iff at least one entry in `include` matches AND no entry in `exclude` matches. Match semantics per research R-003: `~DEFAULT_BRANCH` matches iff `default_branch is not None AND branch == default_branch` (when `default_branch is None`, `~DEFAULT_BRANCH` is treated as non-matching per Constitution II conservative-by-default); `~ALL` matches always; exact bare name matches iff equal to `branch`; `refs/heads/<name>` matches iff `<name> == branch`; any entry containing a glob metacharacter (`*`, `?`, `[`) returns False (documented as a v0 limitation). Function is pure; no I/O.

- [X] T006 Implement `_ruleset_satisfies(rule: RulesetRule, requirement: ProtectionRequirement, minimum: int) -> tuple[bool, str]` in `branch_protection.py`. Return `(True, "")` when the rule satisfies the requirement per the mapping in data-model.md: `REQUIRE_PULL_REQUEST` -> `rule.type == "pull_request"`; `PREVENT_DELETION` -> `rule.type == "deletion"`; `REQUIRE_STATUS_CHECKS` -> `rule.type == "required_status_checks"`; `REQUIRE_APPROVALS` -> `rule.type == "pull_request"` AND `rule.parameters.required_approving_review_count >= minimum`. On no-match, return `(False, reason)` where `reason` describes why (e.g., `"rule type is deletion, need pull_request"` or `"pull_request rule but required_approving_review_count is 0, need >= 1"`).

- [X] T007 Implement `_query_classic(owner: str, repo: str, branch: str, requirement: ProtectionRequirement, minimum: int) -> tuple[bool, int, str]` in `branch_protection.py`. Calls `gh_api_with_status(f"/repos/{owner}/{repo}/branches/{branch}/protection")`. Returns `(satisfied: bool, status_code: int, error_message: str)`. On 200: check body for the requirement-specific signal per data-model.md's satisfying-signal table (e.g., `body.get("required_pull_request_reviews") is not None` for REQUIRE_PULL_REQUEST). On 404: `(False, 404, "")`. On any other status: `(False, status, message)`.

- [X] T008 Implement `_query_rulesets(owner: str, repo: str, branch: str, default_branch: str | None, requirement: ProtectionRequirement, minimum: int) -> tuple[VerdictSource, int, dict | None, list[dict], int]` in `branch_protection.py`. Returns `(source, status, matched_ruleset, considered_rulesets, truncated_count)`. Steps: (a) Call `gh_api_with_status(f"/repos/{owner}/{repo}/rulesets", paginate=True)`. (b) On non-200: return `(INSUFFICIENT_ACCESS, status, None, [], 0)`. (c) For each summary in the list, filter by `enforcement == "active"`; if not active, skip. (d) Fetch detail via `gh_api_with_status(f"/repos/{owner}/{repo}/rulesets/{id}")`. On non-200 detail fetch, return `(PARTIAL_FETCH, status, None, [], 0)`. (e) Verify detail's `enforcement == "active"` and `conditions.ref_name` covers `branch` via `_ref_name_matches(branch, default_branch, include, exclude)`. If not covering, skip. (f) For each rule in `rules`, call `_ruleset_satisfies`; on satisfied, return `(RULESET, 200, {"id": ..., "name": ...}, [], 0)`. If none satisfy, append `{"id": ..., "name": ..., "reason": <first-rule-reason or "no matching rule type">}` to a working list. (g) After the loop: compute `truncated = max(0, len(working) - MAX_CONSIDERED_RULESETS)`; return `(NEITHER_SURFACE_PROVIDED_PROTECTION, 200, None, working[:MAX_CONSIDERED_RULESETS], truncated)`. The caller composes the evidence record with `considered_rulesets_truncated` set to `truncated`.

**Checkpoint**: Framework's shared helper distinguishes HTTP status classes; internal helpers can query both surfaces and match rulesets to branches. No handler entry point yet. The default-branch value used for `~DEFAULT_BRANCH` matching flows in from `context.default_branch` (populated by the audit driver at `packages/darnit/src/darnit/tools/audit.py:428`); this feature does NOT add an extra API call to resolve it.

---

## Phase 3: User Story 1 - Repo protected via a repository ruleset is reported compliant (Priority: P1) MVP

**Goal**: A TOML control with `handler = "github_branch_protection"` produces PASS when the repository is protected via an active ruleset, even when the classic branch-protection endpoint 404s.

**Independent Test**: Point an audit at a fixture-mocked repository whose classic endpoint returns 404 and whose rulesets endpoint returns one active ruleset with a matching rule for the requirement. Assert the control resolves PASS with `evidence.source == "ruleset"` and populated `matched_ruleset`.

### Implementation for User Story 1

- [X] T010 [US1] Add `github_branch_protection_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult` in `packages/darnit-baseline/src/darnit_baseline/branch_protection.py`. Body: (a) validate `config["requirement"]` is present and parses to a `ProtectionRequirement`; on failure return `HandlerResult(status=ERROR, message="handler github_branch_protection requires 'requirement' field")`. (b) read `owner` (default `context.owner`), `repo` (default `context.repo`), `branch` (default `context.default_branch`), `required_approvals_minimum` (default 1; validate 1..10 else ERROR), `timeout` (default 30). (c) Call `_query_classic`; on satisfied return `HandlerResult(PASS)` with `evidence = {"source": "classic", "requirement": ..., "classic_status": 200}`. (d) On classic status in `(401, 403, 429)` OR `>= 500` return INCONCLUSIVE with `source="insufficient-access"`. (e) On classic status `0` (unparseable/subprocess-error): INCONCLUSIVE with `source="insufficient-access"`. (f) Otherwise (classic 404 or 200-without-signal): consume the repository's default branch from `context.default_branch` (populated by the audit driver; may be `None` on a partial context, in which case `_ref_name_matches` conservatively treats `~DEFAULT_BRANCH` include entries as non-matching per T005). Call `_query_rulesets(owner, repo, branch, context.default_branch, requirement, required_approvals_minimum)`. Do NOT make an extra `GET /repos/{owner}/{repo}` call to resolve the default branch -- that would violate SC-004's API-call budget. Map returned `source` to the HandlerResult: `RULESET`->PASS, `NEITHER_SURFACE_PROVIDED_PROTECTION`->FAIL, `INSUFFICIENT_ACCESS`/`PARTIAL_FETCH`->INCONCLUSIVE. Populate `evidence["source"]`, `evidence["classic_status"]`, `evidence["rulesets_status"]`, `evidence["requirement"]`, plus `matched_ruleset` (on `RULESET`) or `considered_rulesets` + `considered_rulesets_truncated` (on `NEITHER_SURFACE_PROVIDED_PROTECTION`) per data-model.md. INCONCLUSIVE falls through to the trailing manual pass in the control's pass list (sieve semantic).

- [X] T011 [US1] Register the new sieve handler in `packages/darnit-baseline/src/darnit_baseline/implementation.py`'s `register_handlers()` method. Add a `sieve_registry.register("github_branch_protection", phase="deterministic", handler_fn=github_branch_protection_handler, default_authority="dispositive", description="Ruleset-aware branch-protection verdict")` call inside the existing sieve-registry block (near `generate_threat_model_handler`). Import from `.branch_protection`.

- [X] T012 [US1] Update `[[controls."OSPS-AC-03.01".passes]]` in `packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml`. Replace the existing exec pass at ~line 631 with:
  ```toml
  [[controls."OSPS-AC-03.01".passes]]
  handler = "github_branch_protection"
  requirement = "require_pull_request"
  timeout = 30
  ```
  Delete the `command`, `pass_exit_codes`, `fail_exit_codes`, `output_format`, `expr` fields. Preserve the manual pass at ~line 640 unchanged.

- [X] T013 [US1] Update `[[controls."OSPS-AC-03.02".passes]]` in the same TOML at ~line 692. Same replacement pattern with `requirement = "prevent_deletion"`.

- [X] T014 [US1] Update `[[controls."OSPS-QA-03.01".passes]]` at ~line 2628. Same replacement pattern with `requirement = "require_status_checks"`.

- [X] T015 [US1] Update `[[controls."OSPS-QA-07.01".passes]]` at ~line 3229. Same replacement pattern with `requirement = "require_approvals"`. Keep `required_approvals_minimum = 1` (matches existing semantic; optional since default is 1).

- [X] T016 [P] [US1] Create `tests/darnit_baseline/test_branch_protection_handler.py`. Add a `_GhResponseSequencer` fixture that lets tests declare a list of `(endpoint_pattern, response)` tuples where each response is a `(body, status, message)` tuple, then patches `darnit_baseline.branch_protection.gh_api_with_status` to return matched responses in order. Add a `make_context()` factory returning a `HandlerContext` with `owner="octo"`, `repo="hello"`, `default_branch="main"`.

- [X] T017 [P] [US1] Write `test_ruleset_pull_request_pass` in `test_branch_protection_handler.py`: classic returns 404, rulesets list returns `[{"id": 1, "name": "Protect main", "target": "branch", "enforcement": "active"}]`, ruleset detail returns `{"id": 1, "name": "Protect main", "enforcement": "active", "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}, "rules": [{"type": "pull_request", "parameters": {"required_approving_review_count": 1}}]}`. Assert (a) HandlerResult.status == PASS; (b) evidence["source"] == "ruleset"; (c) evidence["matched_ruleset"] == {"id": 1, "name": "Protect main"}; (d) evidence["classic_status"] == 404; (e) evidence["rulesets_status"] == 200.

- [X] T018 [P] [US1] Write `test_ruleset_deletion_pass` in the same file. Same fixture shape but ruleset has `rules: [{"type": "deletion"}]` and handler config has `requirement="prevent_deletion"`. Assert PASS + source=ruleset.

- [X] T019 [P] [US1] Write `test_ruleset_status_checks_pass`. Same pattern; requirement=`"require_status_checks"`, rule type `"required_status_checks"`. Assert PASS.

- [X] T020 [P] [US1] Write `test_ruleset_approvals_pass`. requirement=`"require_approvals"`, rule type `"pull_request"`, `parameters.required_approving_review_count = 1`. Assert PASS.

- [X] T021 [P] [US1] Write `test_ruleset_approvals_minimum_enforced`. Ruleset has `required_approving_review_count = 1`, handler config has `required_approvals_minimum = 2`. Assert result is FAIL (not PASS): the ruleset targets the branch and has the right rule TYPE, but its parameter does not meet the minimum. Evidence.considered_rulesets[0].reason names the mismatch.

- [X] T022 [P] [US1] Write `test_ref_name_matching_pseudo_default_branch`. Two variants: (a) ruleset `include = ["~DEFAULT_BRANCH"]` and audited branch equals default -> match (PASS); (b) same but audited branch is `feature/foo` (not the default) -> no match (FAIL, considered_rulesets entry with reason `"ref_name.include does not cover branch feature/foo"`).

- [X] T023 [P] [US1] Write `test_ref_name_matching_exact_and_git_ref`. Two variants: (a) `include = ["main"]`, audited branch `main` -> match; (b) `include = ["refs/heads/main"]`, audited branch `main` -> match.

- [X] T024 [P] [US1] Write `test_ref_name_matching_exclude_wins`. `include = ["~ALL"]`, `exclude = ["refs/heads/main"]`, audited branch `main` -> no match.

- [X] T025 [P] [US1] Write `test_ref_name_matching_glob_treated_as_non_match`. `include = ["refs/heads/release/*"]`, audited branch `release/1.0`. Handler treats glob as non-match, result is FAIL, `considered_rulesets` entry names the ruleset with reason mentioning the glob (research R-003 documented behavior).

- [X] T026 [P] [US1] Write `test_matched_ruleset_evidence_populated`. Duplicates T017's PASS scenario but with additional assertions: `evidence` MUST NOT contain a `considered_rulesets` key on a ruleset-source PASS.

**Checkpoint**: A control author's PASS scenario works end-to-end. US1's Independent Test passes.

---

## Phase 4: User Story 2 - Repo with no protection at either surface still FAILs cleanly (Priority: P1)

**Goal**: An audit continues to FAIL when both surfaces respond definitively and neither carries the required protection. Preserves feature 019's shipped semantic for classic-only-and-still-fails while adding the two-surface check.

**Independent Test**: Point an audit at a fixture-mocked repository whose classic endpoint returns 404 and whose rulesets list returns an empty array. Assert the control resolves FAIL with `evidence.source == "neither-surface-provided-protection"`.

### Implementation for User Story 2

- [X] T027 [P] [US2] Write `test_no_classic_no_rulesets_fails` in `test_branch_protection_handler.py`: classic 404, rulesets list returns `[]`. Assert FAIL, source=neither-surface-provided-protection, `classic_status=404`, `rulesets_status=200`, `considered_rulesets == []`.

- [X] T028 [P] [US2] Write `test_no_classic_only_evaluate_mode_rulesets_fails`. Classic 404, rulesets list returns one entry, detail has `enforcement="evaluate"`. Assert FAIL. `considered_rulesets` MAY include the evaluate-mode ruleset with a `"not active enforcement"` reason (implementation choice — either always exclude evaluate-mode from consideration, or include them with a reason).

- [X] T029 [P] [US2] Write `test_no_classic_rulesets_dont_cover_branch_fails`. Classic 404, active ruleset exists but `conditions.ref_name.include = ["refs/heads/develop"]`, audited branch `main`. Assert FAIL. `considered_rulesets[0].reason` names the non-covering condition.

- [X] T030 [P] [US2] Write `test_ruleset_empty_rules_array_fails`. Active ruleset covers the branch but `rules: []`. Assert FAIL. `considered_rulesets[0].reason == "no rules declared"` or equivalent.

- [X] T031 [P] [US2] Write `test_considered_rulesets_populated_on_fail`. Classic 404, three rulesets all failing for distinct reasons (wrong rule type, wrong branch coverage, wrong parameter). Assert `considered_rulesets` has three entries in the order they were seen, each carrying `id`, `name`, and `reason`. Assert `considered_rulesets_truncated == 0`.

- [X] T032 [P] [US2] Write `test_considered_rulesets_truncation`. Fixture returns 25 non-matching active rulesets. Assert `len(evidence["considered_rulesets"]) == 20` AND `evidence["considered_rulesets_truncated"] == 5`.

- [X] T033 [P] [US2] Write `test_classic_partial_signal_falls_through_to_rulesets`. Classic returns 200 with `{"allow_deletions": {"enabled": false}}` (satisfies PREVENT_DELETION but NOT REQUIRE_PULL_REQUEST). Handler config requests REQUIRE_PULL_REQUEST. Rulesets contain an active ruleset with a `pull_request` rule targeting the branch. Assert PASS via ruleset, `evidence["source"] == "ruleset"`, evidence["classic_status"] == 200 (not 404). Locks the cross-surface layering behavior from Q1 of the clarification session.

- [X] T034 [P] [US2] Write `test_both_surfaces_confirm_uses_classic_first`. Classic 200 with `required_pull_request_reviews`, AND rulesets also have a matching active ruleset. Assert PASS with `source == "classic"` (rulesets NOT consulted; verify by asserting the sequencer received zero calls to the rulesets endpoint after the classic call succeeded).

- [X] T035 [P] [US2] Write `tests/darnit/core/test_gh_api_status.py::test_gh_api_status_200_returns_body`. Patch `subprocess.run` to return `CompletedProcess(args=[...], returncode=0, stdout='{"a":1}', stderr="")`. Call `gh_api_with_status("/some/endpoint")`. Assert `(body, status, msg) == ({"a": 1}, 200, "")`.

- [X] T036 [P] [US2] Write `test_gh_api_status_404_parses_from_stderr`. Patch to return `(returncode=1, stdout="", stderr="HTTP 404: Not Found (https://api.github.com/...)")`. Assert `(None, 404, "HTTP 404: Not Found (...)")`.

- [X] T037 [P] [US2] Write `test_gh_api_status_403_parses`. Same shape with `"HTTP 403: Forbidden"`. Assert `(None, 403, ...)`.

- [X] T038 [P] [US2] Write `test_gh_api_status_5xx_parses`. `"HTTP 502: Bad Gateway"`. Assert `(None, 502, ...)`.

- [X] T039 [P] [US2] Write `test_gh_api_status_unparseable_stderr_returns_zero`. `stderr="connection reset by peer"` (no HTTP prefix). Assert `(None, 0, "connection reset by peer")`.

- [X] T040 [P] [US2] Write `test_gh_api_status_paginate_flag`. Patch subprocess.run and capture the argv. Call `gh_api_with_status("/repos/x/y/rulesets", paginate=True)`. Assert argv contains `"--paginate"` between `"api"` and the endpoint.

- [X] T041 [P] [US2] Write `test_gh_api_status_gh_not_found`. Patch subprocess.run to raise `FileNotFoundError`. Assert `(None, 0, msg)` where msg names `gh not found` and the install URL.

- [X] T042 [P] [US2] Write `test_gh_api_wrapper_preserves_contract`. Call `gh_api("/some/endpoint")` with 200 body -> returns dict. Call with 404 -> raises `RuntimeError` with the stderr message. Confirms the thin-wrapper refactor.

- [X] T043 [P] [US2] Write `test_gh_api_safe_wrapper_preserves_contract`. Call `gh_api_safe("/some/endpoint")` with 200 -> returns dict. With any error -> returns None. Confirms `gh_api_safe`'s existing exception-swallow behavior is preserved.

**Checkpoint**: FAIL semantics for genuinely-non-compliant repos are preserved; the `gh_api_with_status` helper is fully covered. US2's Independent Test passes.

---

## Phase 5: User Story 3 - Ambiguous responses continue to resolve WARN (Priority: P2)

**Goal**: A control resolves INCONCLUSIVE (which the trailing manual pass converts to WARN with human-verification steps) whenever the framework cannot determine protection status: 401/403/429/5xx on either surface, network error, or partial-fetch mid-pagination.

**Independent Test**: Point an audit at a fixture-mocked repository whose classic endpoint returns 403 or whose rulesets endpoint returns 429. Assert the control resolves INCONCLUSIVE and, when run through the full sieve orchestrator, the trailing manual pass produces WARN with `evidence.source` naming the ambiguous surface.

### Implementation for User Story 3

- [X] T044 [P] [US3] Write `test_classic_403_returns_inconclusive` in `test_branch_protection_handler.py`. Classic returns `(None, 403, "HTTP 403: Forbidden")`. Assert `HandlerResult.status == INCONCLUSIVE`, `evidence["source"] == "insufficient-access"`, `evidence["classic_status"] == 403`, `evidence.get("rulesets_status", 0) == 0` (rulesets was not consulted because a 403 from classic cannot be distinguished from "no protection classic-side").

- [X] T045 [P] [US3] Write `test_rulesets_403_returns_inconclusive`. Classic returns 404, rulesets list returns `(None, 403, ...)`. Assert INCONCLUSIVE, `source == "insufficient-access"`, `classic_status == 404`, `rulesets_status == 403`.

- [X] T046 [P] [US3] Write `test_classic_5xx_returns_inconclusive`. Classic returns 502. Assert INCONCLUSIVE, source=insufficient-access.

- [X] T047 [P] [US3] Write `test_rulesets_429_returns_inconclusive`. Classic 404, rulesets list returns 429. Assert INCONCLUSIVE, source=insufficient-access.

- [X] T048 [P] [US3] Write `test_partial_fetch_returns_inconclusive`. Classic 404, rulesets list returns 200 with one entry, but the detail call for that entry returns 404 (ruleset was deleted between list and detail). Assert INCONCLUSIVE, `source == "partial-fetch"`, `rulesets_status == 200`, and the message names the specific ruleset id that could not be fetched.

- [X] T049 [P] [US3] Write `test_gh_cli_missing_returns_inconclusive`. Patch `gh_api_with_status` to return `(None, 0, "GitHub CLI (gh) not found. Install it from https://cli.github.com/")` for the classic endpoint. Assert INCONCLUSIVE, source=insufficient-access, message names the install URL.

- [X] T050 [P] [US3] Write `test_classic_status_zero_returns_inconclusive`. Classic returns `(None, 0, "connection refused")` (unparseable status, e.g., network error before request completed). Assert INCONCLUSIVE, source=insufficient-access.

**Checkpoint**: WARN semantics for ambiguous cases are preserved on both surfaces plus in the partial-fetch case. US3's Independent Test passes.

---

## Phase 6: Integration tests through the sieve orchestrator

**Purpose**: End-to-end verification that the four TOML controls resolve correctly when driven by the actual sieve orchestrator (not just direct handler calls). Locks the TOML edits from T012-T015 against silent regression and confirms the trailing manual pass produces the intended WARN when the handler is INCONCLUSIVE.

- [X] T051 [P] [US1] Write `tests/darnit_baseline/test_branch_protection_integration.py::test_osps_ac_03_01_pass_via_ruleset`. Construct a real `SieveOrchestrator`, load the openssf-baseline TOML, look up `OSPS-AC-03.01`, patch `darnit_baseline.branch_protection.gh_api_with_status` to return ruleset-satisfying responses. Call `orchestrator.verify(control_spec, context)`. Assert `result.status == "PASS"`, `result.evidence["source"] == "ruleset"`.

- [X] T052 [P] [US1] Same shape for `OSPS-AC-03.02` (requirement=prevent_deletion, rule type=deletion).

- [X] T053 [P] [US1] Same shape for `OSPS-QA-03.01` (requirement=require_status_checks).

- [X] T054 [P] [US1] Same shape for `OSPS-QA-07.01` (requirement=require_approvals, ruleset with required_approving_review_count=1).

- [X] T055 [P] [US2] Write `test_osps_ac_03_01_fail_when_no_protection`. Fixture returns classic 404 + empty rulesets. Assert `result.status == "FAIL"`, `result.evidence["source"] == "neither-surface-provided-protection"`. Locks the feature-019 baseline FAIL semantic on the true-negative path.

- [X] T056 [P] [US3] Write `test_osps_ac_03_01_warn_when_403_falls_through_to_manual`. Fixture returns classic 403. Assert the full pass chain resolves to WARN (handler INCONCLUSIVE -> trailing manual pass produces WARN with verification steps). Evidence from the handler pass carries `source == "insufficient-access"`.

- [X] T057 [P] [US2] Write `test_zero_rulesets_calls_when_four_controls_excluded`. Run the orchestrator against a control filter that excludes all four affected controls (e.g., `--tags` filter or a scope that only includes an unrelated control). Assert zero calls to `gh_api_with_status` for any endpoint containing `/rulesets`. Locks SC-005 (zero cost when the four controls are excluded).

- [X] T057a [P] [US2] Write `test_api_call_budget_matches_sc_004` in `test_branch_protection_integration.py`. Fixture: classic 404 + rulesets list returning 3 active rulesets (spread across a single page) + 3 detail-fetch responses that all target the branch but do NOT satisfy the requirement (so the handler exhausts all three and resolves FAIL). Use the `_GhResponseSequencer` in strict mode (assertions on order AND count). Assert (a) exactly ONE call to the classic branch-protection endpoint, (b) exactly ONE call to `/rulesets` (single page, per `gh api --paginate` behavior for a fits-in-one-page response), (c) exactly THREE calls to `/rulesets/{id}` (one per active summary), (d) zero calls to any other GitHub endpoint (specifically NOT `/repos/{owner}/{repo}` since T010 uses `context.default_branch` per F1 remediation). Locks spec SC-004's exact budget formula: `1 classic + ceil(N/page_size) list + N detail` when the ruleset list fits in one page.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Full workspace verification, scope guard, lint clean, spec-sync validation, product-scope invariant.

- [X] T058 Run the full workspace test sweep from repo root: `uv run pytest tests/ -q --deselect tests/darnit/context/test_dot_project_upstream.py::TestUpstreamSpecSync::test_upstream_spec_unchanged`. Confirm exit code 0.

- [X] T059 [P] Two sub-steps, both MUST pass. **(a) Structure Decision**: `git diff --name-only main..HEAD | grep -E 'packages/(darnit-gittuf|darnit-reproducibility|darnit-hello)/src/'` MUST produce zero lines (only `darnit-baseline/` and one file in `darnit/core/utils.py` are touched under `packages/*/src/`). **(b) FR-013 no-new-runtime-dep guard**: `git diff main..HEAD -- pyproject.toml packages/*/pyproject.toml` MUST be empty (no new deps introduced).

- [X] T060 [P] Run `uv run ruff check .` on repo root; MUST exit 0. Fix any lint issues in the files this feature touched; do NOT auto-format unrelated files.

- [X] T061 [P] Run `uv run python scripts/validate_sync.py --verbose`; MUST exit 0. Specifically confirm the "Pass Types Sync: Handler names in sync" line now includes `github_branch_protection`. This proves T002 correctly wired the handler-name registry entry.

- [X] T062 Confirm the module docstring on `packages/darnit-baseline/src/darnit_baseline/branch_protection.py` accurately describes the final implementation (specifically the two-surface flow from T010 and the `_ref_name_matches` semantics from T005). Fix any docstring/code drift. Also confirm the `contracts/github-branch-protection-handler.md` failure-mode table matches every distinguishable path in T010's `HandlerResult` construction.

- [X] T063 Manually verify the `help_md` sections for all four affected controls in `openssf-baseline.toml` still make sense. The user-facing remediation guidance did not change (still says "enable branch protection"), but the automated-check description language may benefit from a small addition mentioning that either classic protection OR a repository ruleset satisfies. Optional; keep changes minimal.

---

## Dependencies

```
Phase 1 (T001..T002) --> Phase 2 (T003..T008) --> Phase 3 (US1: T010..T026)
                                                        |
                                                        +--> Phase 4 (US2: T027..T043) [all [P] within phase after T010-T015 land]
                                                        |
                                                        +--> Phase 5 (US3: T044..T050)
                                                        |
                                                        +--> Phase 6 (Integration: T051..T057a)
                                                        |
                                                        +--> Phase 7 (Polish: T058..T063)
```

Phase 1 tasks T001 and T002 touch different files -- can run `[P]` but listed sequentially for reviewer readability.

Within Phase 2, T003 (utils.py) is independent of T004-T008 (branch_protection.py). T004-T008 all touch `branch_protection.py` and must serialize on it, but they are internal helpers and can be authored in any order relative to each other; sequential is preferred.

Within Phase 3, T010 must land before T011-T015 (TOML edits reference the handler). T012-T015 touch the same TOML file and must serialize. T016-T026 are test tasks and can be authored in parallel (pytest handles concurrent test-file additions cleanly).

Within Phase 4, T035-T043 (`test_gh_api_status.py`) is a different file from T027-T034 (`test_branch_protection_handler.py`) and can run in a separate work stream.

Within Phase 6, T051-T057 all touch `test_branch_protection_integration.py` and must serialize on that file.

## Parallel execution examples

After Phase 3 (US1) MVP lands, US2/US3/US6 test tasks are largely disjoint:

```sh
# Fire US2 handler tests, US2 helper tests, and US3 tests concurrently.
uv run pytest tests/darnit_baseline/test_branch_protection_handler.py -k "no_protection or considered_rulesets or partial_signal or both_surfaces" -q &
uv run pytest tests/darnit/core/test_gh_api_status.py -q &
uv run pytest tests/darnit_baseline/test_branch_protection_handler.py -k "403 or 429 or 5xx or partial_fetch or gh_cli_missing" -q &
wait
```

Within Phase 7:

```sh
uv run pytest tests/ -q --deselect ...              # T058 (long-running; start it first)
git diff --name-only main..HEAD | grep -E ...       # T059 (fast, [P])
uv run ruff check .                                 # T060 (fast, [P])
uv run python scripts/validate_sync.py --verbose    # T061 (fast, [P])
# T062, T063 run last, require final state
```

## Implementation strategy

MVP scope = Phase 1 + Phase 2 + Phase 3 (User Story 1 alone). Landing US1 gets the machinery working end-to-end against the mock and delivers the P1 goal from the spec: a repo protected via a ruleset resolves PASS. Everything after that locks failure semantics and adds regression coverage.

Incremental delivery order:

1. Land T001..T026 (Setup + Foundational + US1) as the MVP PR. At this point the handler works, the four TOMLs are updated, and the ruleset-source PASS path is fully tested.
2. Land T027..T043 (US2 + `gh_api_with_status` coverage) as a follow-up commit or same PR. Locks the FAIL-preservation invariant and the helper's contract.
3. Land T044..T050 (US3) as a follow-up commit. Locks the WARN-preservation invariant.
4. Land T051..T057 (integration through orchestrator) as a follow-up commit. End-to-end regression suite.
5. Land T058..T063 (polish) as the last commit or squash into the MVP.

All commits belong to the same PR against `main` unless the review size demands a split. If piecewise review is preferred, reviewer order is (foundational + US1 code, US2 tests, US3 tests, integration, polish) so each commit's contract-level effect is legible independently.
