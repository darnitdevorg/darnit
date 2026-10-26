# Research: Judge and Confirm After Remediation

Base: `fix/question-picker` (#672, top of the #669-#672 stack), which adds `get_judgment_requests`, subset re-gathering, `darnit.server.procedures`, and `pending.kind` on summary rows.

## R1. Where an outcome carries what it awaits (FR-008, FR-009)

- **Decision**: Add `pending_kind: Literal["llm_judgment", "confirmation"] | None = None` to `RemediationOutcome` (`packages/darnit/src/darnit/remediation/plan.py`). The model validator requires it to be set exactly when `kind == "changed_not_passing"` and the re-check status is `PENDING`, and to equal `recheck.pending.kind`. `_rechecked_outcome` in the baseline orchestrator sets it.
- **Rationale**: Clarified as option A (spec, Clarifications). The re-check dict already holds `pending` (`_RECHECK_FIELDS`), but nothing validates it or exposes it at the top level, and the Markdown report prints only the status. A typed, validated field is what "readable without parsing report text" requires. `OUTCOME_KINDS`, `summarize`, and the commit/PR gates are unchanged, so FR-009 holds by construction.
- **Alternatives**: Read `outcome.recheck["pending"]["kind"]` with no new field (rejected: unvalidated, and a client must know the nested shape); a new outcome kind (rejected in clarification).

## R2. How the apply result names the next step (FR-010)

- **Decision**: `RemediationRun` gains `awaiting: dict[str, list[str]]`, derived from `outcomes` like `summary` (keys `llm_judgment` and `confirmation`, control ids sorted; empty dict when none), and the Markdown report gains a short "Next steps" section whose text comes from `darnit.server.procedures.remediation_next_steps(...)`.
- **Rationale**: Same pattern as `summary`: derived, validated, never hand-set. Ids only, so the result does not grow by evidence (the result is already over the agent's tool-output limit; separate issue).
- **Alternatives**: Put the ids only in Markdown (rejected: text, not data).

## R3. Where the confirmation step gets the candidates (FR-002, FR-003)

- **Decision**: A new read-only, framework-neutral MCP tool `get_pass_candidates`, registered beside `get_judgment_requests`, `submit_judgment`, and `confirm_pass_candidate` (`darnit/server/tools/judgments.py`). It audits `local_path` like `get_judgment_requests`, and returns, per control left `PENDING` with `pending.kind = "confirmation"` (a stored candidate whose digest matches the current evidence): control id, the control's title and description from the framework TOML, the judged file paths, the stored candidate's reasoning, cited passages, model, model version, and source; plus `procedure`, `ask_user_batch`, and the ids still awaiting a judgment. Pages under 40,000 bytes with `remaining`, like `get_judgment_requests`.
- **Rationale**: The person must see the cited passages (FR-003). Summary rows deliberately omit excerpts; the `json` audit is too large; `get_judgment_requests(include_judged=True)` returns full file contents and the judgment procedure, not the stored candidate. A candidate whose digest no longer matches is, by the 5.4 store table, `PENDING (llm_judgment)`, so the tool never offers a stale candidate (User Story 2, scenario 3) without extra logic.
- **Alternatives**: Extend `get_judgment_requests` with candidate blocks (rejected: mixes two procedures, resends full files); a listing mode on `confirm_pass_candidate` (rejected: a tool that writes should not also be the way to read).

## R4. Telling the person a document was generated and edited (FR-004)

- **Decision**: `get_pass_candidates` takes an optional `run_id`. For a candidate whose judged file is in that run's manifest, the entry carries `remediation: {run_id, path, written: true, edited_after_write: <current content digest != manifest after_digest>}`. The confirmation procedure tells the agent to state, for such a candidate, that remediation wrote the document, whether it was edited afterwards (by the agent in this session, which the agent knows, or by someone else), and that the judgment being confirmed is the agent's own.
- **Rationale**: The manifest is already the single record of what remediation wrote (15.6), so "generated" is a fact, not the agent's recollection. Whether the agent itself made the edit is known only to the agent, so the procedure asks it to say so.
- **Alternatives**: Have the agent remember what it wrote (rejected: not checkable); record agent edits in the manifest (rejected: the manifest records only executor writes, 15.6, 15.7).

## R5. The confirmation procedure and question shape (FR-003, FR-005, FR-007)

- **Decision**: `darnit.server.procedures.confirmation_procedure(owner, repo, host, local_path)`, returned by `get_pass_candidates`:
  1. Show every candidate in text first: control, requirement, files, the reasoning, and each cited passage verbatim; for a generated document, say so (R4); label each "PASS candidate, not compliant until you confirm".
  2. Ask with the question tool using `ask_user_batch`: one question per candidate, options "Confirm", "Do not confirm", "Skip for now", no default, no "confirm all" option.
  3. Call `confirm_pass_candidate(control_ids=[only the ids the person chose Confirm for], ...)` once; never on silence, skip, or a blanket instruction that names no candidate.
  4. Tell the person what was confirmed, and that confirmations are recorded for them on this machine; CI or another maintainer sees those controls PENDING until confirmed there (FR-006).
- **Rationale**: Mirrors `data_collection_procedure` (#671), so both skills defer to one text (FR-007). Short questions that refer to candidates already shown in full keep the question tool's limits.
- **Alternatives**: A multi-select "which do you confirm" question (rejected: a pre-ticked or select-all UI makes blanket confirmation easy).

## R6. Where the post-remediation steps live in the flow (FR-001, FR-006)

- **Decision**: framework-design gains 15.9 "After remediation: judge and confirm" (comply order: apply, improve the generated files, judge with `get_judgment_requests` unfiltered, confirmation step, final audit, then the pull request), and 5.4 gains `get_pass_candidates`. `/darnit-comply` and `/darnit-audit` each gain a short step that defers to the tools' procedures.
- **Rationale**: Judging after the agent's edits is required by the digest binding (spec, Edge Cases). An unfiltered `get_judgment_requests` re-judges every control whose candidate the edits made stale, not only those in `awaiting.llm_judgment`. The final audit runs before the pull request so the PR body's before/after is the confirmed state.
- **Alternatives**: Judge only `awaiting.llm_judgment` ids (rejected: misses candidates the agent's edits invalidated).

## R7. Replay with recorded judgments and confirmations (FR-011 to FR-014)

- **Decision**: #675 is closed; the replay is #666's `scripts/comply_replay.py` with `scripts/comply_replay.toml`. Extend the TOML with `[judgments."<control>"]` (`verdict`, `reasoning`, `cited_evidence`) and `confirm = [...]`. After the post-remediation audit, the replay calls `submit_judgment_impl` in-process with `model = "recorded"` and `model_version = "comply_replay.toml"` (FR-013, within existing fields), then `confirm_pass_candidates_impl` for `confirm`, under the replay's throwaway `HOME`, then audits again. It reports PASS before, after remediation, and after judge-and-confirm; the expected-results file gains the third number. A rejected recorded judgment is reported with its control and missing passages and fails the replay.
- **Rationale**: Same path a model's judgment takes (FR-012). Nothing in `packages/` reads the TOML (FR-014; a test asserts no product module references it). Generated content is deterministic from templates and the recorded answers, so recorded citations verify.
- **Gate**: This phase lands after #666. A person (the maintainer) writes the recorded verdicts from the generated documents; an honest verdict on a template that still holds placeholders is `fail`, and that is a finding about the templates, not something to paper over.
- **Alternatives**: Store recorded judgments in the operator store directly (rejected: bypasses citation checks).

## R8. Out of scope, confirmed

- `darnit run` / `darnit harness`: only their reports must show `pending_kind` where they print outcomes.
- OSPS-VM-05.03 WARN after remediation; tool output sizes; confirmation portability (follow-up issue).
