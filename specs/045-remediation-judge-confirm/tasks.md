# Tasks: Judge and Confirm After Remediation

**Input**: Design documents from `specs/045-remediation-judge-confirm/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included. SC-005 requires tests over every outcome kind, and the project merges behavior changes only with tests and a recorded end-to-end run.

**Organization**: By user story. Base branch is the #672 head (`fix/question-picker`); rebase onto `upstream/main` once #669-#672 merge.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1-US4 from spec.md

## Path Conventions

- Framework: `packages/darnit/src/darnit/`
- Baseline implementation: `packages/darnit-baseline/src/darnit_baseline/`
- Tests: `tests/darnit/`, `tests/darnit_baseline/`
- Commits: `Assisted-by: Claude:claude-opus-5-5`, never `Signed-off-by` or `Co-Authored-By`; ASCII-only text in every file

---

## Phase 1: Setup

- [X] T001 Confirm the worktree is on `045-remediation-judge-confirm` based on the #672 head (`git merge-base --is-ancestor 69516e9c HEAD`), run `uv sync`, and record the baseline `uv run pytest tests/ --ignore=tests/integration/ -q` pass/skip counts in a scratch note for comparison at T040

---

## Phase 2: Foundational (spec first; blocks every story)

**Purpose**: The constitution's workflow requires `docs/architecture/framework-design.md` to change before code.

- [X] T002 In `docs/architecture/framework-design.md` section 5.4, add `get_pass_candidates(owner, repo, host, local_path, control_ids, run_id)` beside `get_judgment_requests`: read only, returns only candidates matching the current evidence digest with title, description, files, reasoning, cited passages, model, source, and the `remediation` block from the run manifest; pages under 40,000 bytes; returns `procedure` and `ask_user_batch` (contracts/get-pass-candidates.md)
- [X] T003 In `docs/architecture/framework-design.md` section 15.4, add `pending_kind` to `RemediationOutcome` (set only on `changed_not_passing` with a PENDING re-check, equal to the re-check's `pending.kind`; outcome kinds unchanged) and `awaiting` to `RemediationRun` (derived like `summary`), plus the report's "Awaiting" line and "Next steps" section, with scenarios (contracts/remediation-outcome.md); in 15.5 note that a PENDING re-check's kind is carried on the outcome
- [X] T004 In `docs/architecture/framework-design.md`, add section 15.9 "After remediation: judge and confirm": order (apply, improve generated files, judge unfiltered with `get_judgment_requests`, confirmation step via `get_pass_candidates` with the run id, final audit, then the pull request), the confirmation rules (show all, one question per candidate, confirm only named, never on silence or blanket instruction, generated-and-edited disclosure, confirmations local to this machine), with scenarios; update the 15.8 skills row to point at 15.9 and say `/darnit-audit` ends with the same confirmation step
- [X] T005 Run `uv run python scripts/validate_sync.py --verbose` and fix any handler-name or schema drift the spec edits introduce

**Checkpoint**: Spec text approved; stories can start.

---

## Phase 3: User Story 1 - Comply judges what it wrote and asks the person to confirm (Priority: P1) MVP

**Goal**: After remediation and the agent's edits, comply judges the remediated controls and offers every matching PASS candidate for explicit confirmation before the final audit.

**Independent Test**: quickstart.md section 5 (interactive) and section 4 (headless: candidates listed as awaiting, none confirmed).

### Tests for User Story 1

- [X] T006 [P] [US1] Write `tests/darnit/server/test_procedures_confirmation.py`: `confirmation_procedure(owner, repo, host, local_path)` names only the caller's repository and checkout (placeholders when unnamed, never a remote), holds no candidate value or passage, tells the agent to show all candidates before asking, to disclose remediation-written and agent-edited documents and that the judgment is the agent's own, to confirm only controls answered "Confirm" in one `confirm_pass_candidate` call, never on silence/skip/blanket instruction, and to say confirmations are local to this machine
- [X] T007 [P] [US1] Write `tests/darnit/server/test_pass_candidates.py` with fixtures modeled on `tests/darnit/server/test_judgment_requests.py` and `tests/darnit/server/test_submit_judgment.py` (isolated `HOME`, a checkout with a judged document, a stored candidate via `submit_judgment_impl`): returns the candidate with title, description, files, reasoning, verbatim `cited_evidence`, model, model_version, source, evidence_digest; `ask_user_batch` has one question per candidate with exactly "Confirm", "Do not confirm", "Skip for now" and no multi-confirm option; unnamed repository is `rejected`; invalid `local_path` is `error`; `control_ids` filters; paging keeps each page under `JUDGMENT_REQUEST_PAGE_BYTES` with `remaining`; the confirmation store, audit cache file, and checkout are byte-identical after the call
- [X] T008 [P] [US1] In `tests/darnit/server/test_pass_candidates.py`, add run-manifest cases: with `run_id` of a run that wrote the judged file, the entry has `remediation: {run_id, path, written: true, edited_after_write: false}`; after editing the file and re-judging, `edited_after_write: true`; an unknown `run_id` gives `status: ok`, no `remediation` blocks, and a `note`
- [X] T009 [P] [US1] In `tests/darnit/server/test_factory.py` (and the tool-list assertions in `tests/integration/test_mcp_server.py` if it enumerates tools), assert every framework server registers `get_pass_candidates` with `structured_output=False`

### Implementation for User Story 1

- [X] T010 [US1] Add `confirmation_procedure(owner, repo, host, local_path) -> list[str]` to `packages/darnit/src/darnit/server/procedures.py`, using `_args`, with the six steps of contracts/procedures.md; update the module docstring to list `get_pass_candidates`
- [X] T011 [US1] Add `get_pass_candidates_impl(owner, repo, host, local_path, control_ids, run_id, *, framework_name) -> str` to `packages/darnit/src/darnit/server/tools/judgments.py`: same path validation, operator config, and `decide_trust` identity check as `get_judgment_requests_impl`; `judgment_audit(...)` for `control_ids`; select results `PENDING` with `pending.kind == "confirmation"`; take the stored candidate from `darnit.trust.confirmations.load_candidates(identity.canonical, checkout=...)` matching control, claim `PASS_CANDIDATE_CLAIM`, and the result's current `evidence_digest`; files from `judged_content(...)` keys; title and description from the effective framework controls (`load_controls_from_effective(merge_configs(framework, operator_config.config))`, as `darnit/tools/audit.py` does for its control listing); `awaiting_judgment` from results `PENDING` with `pending.kind == "llm_judgment"`; page under `JUDGMENT_REQUEST_PAGE_BYTES` with `remaining`; JSON via the same `dump`
- [X] T012 [US1] In `get_pass_candidates_impl`, when `run_id` is given, load the run with `darnit.remediation.manifest.load_run(...)` for `identity.canonical`; for each candidate file in `run.files`, add `remediation` with `edited_after_write` = current `content_digest` of the file != `after_digest`; an unknown run adds `note` and no blocks (depends on T011)
- [X] T013 [US1] Build `ask_user_batch` in `get_pass_candidates_impl`: one entry per candidate on the page, `question` "Confirm the PASS candidate for <control> (<files>)?", short `header`, `multiSelect: false`, options "Confirm" / "Do not confirm" / "Skip for now" with one-line descriptions; no candidate text in the options (depends on T011)
- [X] T014 [US1] Add the async `get_pass_candidates(...)` wrapper (docstring per contracts/get-pass-candidates.md, `asyncio.to_thread`) and register it in `register_judgment_tools` in `packages/darnit/src/darnit/server/tools/judgments.py` with `structured_output=False` and a description that says read only, candidates matching current evidence, follow the returned procedure, confirm only what the operator names (depends on T011-T013)
- [X] T015 [US1] Rewrite the workflow in `packages/darnit/src/darnit/skills/darnit-comply/SKILL.md`: keep steps 1-6; new step 7 "Judge what changed" (call `get_judgment_requests` with no `control_ids` after improving the files and follow its procedure; say why when a control cannot be judged); new step 8 "Confirm" (call `get_pass_candidates` with the repository and the apply's `run_id`, follow its `procedure`); step 9 final audit then PR, reporting the five groups of FR-006 and that confirmations are local; step 7 keeps each `submit_judgment` result with `status: finding` and skips judging that control again unless its files changed after the finding; step 9 reports those findings as their own group; bump `metadata.version`; do not restate the procedure's steps
- [X] T016 [US1] Run `uv run pytest tests/darnit/server/ -q` and any skill-text tests (`grep -rl "SKILL.md" tests/`) and fix failures

**Checkpoint**: Comply offers and confirms candidates for remediated documents; US1 testable on its own.

---

## Phase 4: User Story 2 - Candidates from the first judgments are offered too (Priority: P1)

**Goal**: The same confirmation step runs in `/darnit-audit` and covers candidates for documents the project already had; stale candidates are never offered.

**Independent Test**: spec User Story 2 test (existing SECURITY.md judged pass, nothing remediated, candidate offered and passes once confirmed).

### Tests for User Story 2

- [ ] T017 [P] [US2] In `tests/darnit/server/test_pass_candidates.py`, add: a candidate from a first-audit judgment with no `run_id` is returned without a `remediation` block; after the judged file changes, the control is absent from `candidates` and present in `awaiting_judgment`; after `confirm_pass_candidate` on the returned id, a summary audit reports the control PASS with `concluded_by = "confirmation"`; after a `fail` judgment, the control is absent from `candidates`, present in `awaiting_judgment`, and the confirmation store is unchanged

### Implementation for User Story 2

- [ ] T018 [US2] In `packages/darnit/src/darnit/skills/darnit-audit/SKILL.md`, add a step after judgments: call `get_pass_candidates` with the repository and follow its `procedure`; update the report step to list confirmed, declined, skipped, and awaiting candidates and that confirmations are local; keep the existing gotcha on explicit confirmation; keep and report `finding` results the same way as T015; bump `metadata.version`
- [ ] T019 [US2] Run `uv run pytest tests/darnit/server/test_pass_candidates.py -q` and fix failures

**Checkpoint**: Both skills end with the shared confirmation step.

---

## Phase 5: User Story 3 - Remediation says what a changed control is waiting for (Priority: P2)

**Goal**: `pending_kind` on outcomes, derived `awaiting` on the run, and a "Next steps" section, with outcome kinds, summary, gates, and compliance unchanged.

**Independent Test**: quickstart.md section 2.

### Tests for User Story 3

- [ ] T020 [P] [US3] Write `tests/darnit/remediation/test_outcomes_pending_kind.py`: for every kind in `OUTCOME_KINDS` and every re-check status (PASS, FAIL, WARN, PENDING llm_judgment, PENDING confirmation, ERROR, none), `RemediationOutcome` accepts `pending_kind` exactly per contracts/remediation-outcome.md and rejects every other combination, including a value that differs from `recheck.pending.kind` and a PENDING re-check with no kind; `summarize` output is unchanged; `fixed` still needs a PASS re-check; and `awaiting` and `pending_kind` do not change what the commit and pull request gates in `packages/darnit/src/darnit/remediation/github.py` treat as changed
- [ ] T021 [P] [US3] In the same file, test `RemediationRun.awaiting`: derived from outcomes with sorted ids and empty keys omitted; a supplied value that differs is rejected; a preview has `{}`; JSON round-trip keeps `pending_kind` and `awaiting`
- [ ] T022 [P] [US3] Write `tests/darnit/server/test_procedures_next_steps.py` for `remediation_next_steps(owner, repo, host, local_path, awaiting, run_id)`: names `get_judgment_requests` only when `llm_judgment` ids exist, always names `get_pass_candidates` with the run id when anything awaits, lists ids, holds no evidence, returns `[]` when nothing awaits
- [ ] T023 [P] [US3] Write `tests/darnit_baseline/test_remediation_awaiting.py`: drive `_outcomes` in `packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py` with a stub re-check returning PENDING `llm_judgment`, PENDING `confirmation`, WARN, and PASS for four changed controls; assert kinds, `pending_kind`, the run's `awaiting`, the Markdown "Awaiting" lines and "Next steps" section, and that the commit and pull request gates still see changed files (the changed-outcome check the git tools read)

### Implementation for User Story 3

- [ ] T024 [US3] In `packages/darnit/src/darnit/remediation/plan.py`, add `pending_kind: Literal["llm_judgment", "confirmation"] | None = None` to `RemediationOutcome` and extend `_kind_matches_evidence` per data-model.md; add `awaiting: dict[str, list[str]]` to `RemediationRun`, derived in `_derived_summary` (rename to cover both) with the same supplied-must-equal-derived rule; export nothing new unless tests need it
- [ ] T025 [US3] Add `remediation_next_steps(owner, repo, host, local_path, awaiting, run_id) -> list[str]` to `packages/darnit/src/darnit/server/procedures.py` per contracts/procedures.md
- [ ] T026 [US3] In `packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py`, set `pending_kind=(recheck.get("pending") or {}).get("kind")` in `_rechecked_outcome` when the re-check status is PENDING; in `_outcome_lines` add `- **Awaiting:** a model judgment` / `the operator's confirmation of a PASS candidate`; after the outcomes, add a "Next steps" section from `remediation_next_steps(...)` when `run.awaiting` is not empty (depends on T024, T025)
- [ ] T027 [US3] Check the other readers of outcomes for anything that assumes `changed_not_passing` has no extra field or that misreports it: `packages/darnit-baseline/src/darnit_baseline/tools.py` (around the `outcome.recheck` summary line), `packages/darnit/src/darnit/cli.py` (`darnit run` output), and `packages/darnit/src/darnit/harness/report.py`; where an outcome is printed, show `pending_kind` (FR scope note in spec Assumptions)
- [ ] T028 [US3] Run `uv run pytest tests/darnit/remediation/ tests/darnit_baseline/ tests/darnit/server/ -q` and fix failures

**Checkpoint**: Apply results distinguish waiting from failing without reading prose.

---

## Phase 6: User Story 4 - The replay measures the whole path (Priority: P2)

**Goal**: The #666 replay reports PASS after recorded judgments and confirmations.

**Gate**: Starts only after #666 merges (or is stacked on #666 with the maintainer's agreement). Separate PR.

**Independent Test**: quickstart.md section 3.

### Tests for User Story 4

- [ ] T029 [P] [US4] Add `tests/darnit_baseline/test_comply_replay_recorded.py` (or next to the tests #666 adds): parsing `[judgments."<id>"]` and `[confirmations] controls`; a confirmation without a `pass` judgment is a fixture error; a judgment citing text not in the generated file stops the run naming the control and passages; no module under `packages/` references `comply_replay.toml` (grep-based assertion)

### Implementation for User Story 4

- [ ] T030 [US4] In `scripts/comply_replay.py`, after the post-remediation audit, submit each recorded judgment with `submit_judgment_impl(..., model="recorded", model_version="comply_replay.toml")` under the replay's isolated `HOME`, stop on `rejected`, report `finding`s, then call `confirm_pass_candidates_impl(local_path, controls, owner=..., repo=...)`, then audit again and report PASS after judge-and-confirm and the outcomes with `pending_kind` (contracts/replay-recorded-judgments.md)
- [ ] T031 [US4] Add `pass_after_confirm` to `scripts/comply_replay_expected.json` and fail the replay when it drops, as for the other counts
- [ ] T032 [US4] MAINTAINER TASK: write `[judgments.*]` and `[confirmations]` in `scripts/comply_replay.toml` from the documents the replay's remediation generates for wtf-frontend at 939e838 (print them with the replay's keep-copy option); verdicts are the maintainer's, and a template that still holds placeholders is `fail`
- [ ] T033 [US4] Run the replay, record the three counts, check that removing one confirmation lowers PASS after judge-and-confirm by exactly one, and that editing one recorded passage stops the replay with that control

**Checkpoint**: A regression on the judge-and-confirm path lowers a number in review.

---

## Phase 7: Polish and verification

- [ ] T034 [P] Add a CHANGELOG entry (Unreleased) in `CHANGELOG.md`: `pending_kind` and `awaiting` on remediation results, `get_pass_candidates`, confirmation step in `/darnit-audit` and `/darnit-comply`, comply judges after improving generated files; refs #681
- [ ] T035 [P] Add a 045 line to the Active Technologies list in `CLAUDE.md`, in the style of the 043/044 lines (existing dependencies only; operator-side store unchanged)
- [ ] T036 [P] Check every new or changed file is ASCII-only: `LC_ALL=C grep -rn '[^ -~]' <files>` returns nothing (existing non-ASCII in untouched lines excepted)
- [ ] T037 Run `uv run ruff check .`, `uv run ruff format --check .`, and `uv run python scripts/validate_sync.py --verbose`
- [ ] T038 End-to-end per quickstart.md sections 2, 4, and 5 on fresh copies of wtf-frontend at 939e838 with an isolated `HOME`, platform remediation `manual`, no writes to real repositories: apply result fields; headless comply (SC-002, SC-003; `confirm_pass_candidate` disallowed); interactive comply and `/darnit-audit` (SC-004), the interactive part run by the maintainer
- [ ] T039 Draft (do not file) the follow-up issue on confirmation portability (confirmations count only on the confirming operator's machine; CI and other maintainers see PENDING), ending with the attribution line, for the maintainer to approve
- [ ] T040 Run `uv run pytest tests/ --ignore=tests/integration/ -q`, compare with T001, and write the PR Testing section: base and head SHAs, reference repository and commit, which quickstart sections ran and their results, what was not run and why

---

## Dependencies and Execution Order

- Phase 1 -> Phase 2 -> stories. Phase 2 (spec text) blocks every story.
- US1 (Phase 3) and US3 (Phase 5) are independent: US1 does not read `pending_kind` or `awaiting`; US3 does not need `get_pass_candidates` (its "Next steps" text only names it).
- US2 depends on US1's `get_pass_candidates` (T011-T014).
- US4 depends on #666 merging, and on US3 for printing `pending_kind` (T024, T026).
- Within a story: tests first and failing, then implementation, then the story's test run.
- T010 and T025 both edit `procedures.py`; T011-T014 all edit `judgments.py`; run those in order.

## Parallel Examples

- US1 tests: T006, T007, T008, T009 together (four files).
- US3 tests: T020, T021 (same file, write together), T022, T023 in parallel.
- US1 and US3 implementation can proceed side by side after Phase 2: T010-T015 and T024-T027 touch different files except `procedures.py` (T010, T025: sequence them).
- Polish: T034, T035, T036 in parallel.

## Implementation Strategy

1. **MVP**: Phases 1-3 (spec text and US1). Comply then judges remediated documents and asks the person to confirm; this alone closes most of the #681 gap for an interactive user.
2. Add US2 (audit skill, stale candidates) and US3 (outcome fields), then Phase 7 T034-T040. One PR for Phases 1-5 and 7.
3. US4 as a second PR after #666.
4. Each PR merges only with green CI, a non-author approving review, and the recorded end-to-end run (T038, T040).
