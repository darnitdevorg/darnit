# Quickstart: validating Judge and Confirm After Remediation

Follows the end-to-end verification draft (`docs/design/e2e-verification.md`, not yet in the repository; shared setup: own `HOME` per darnit process, `GH_TOKEN` from `gh auth token`, a fresh copy per phase, platform remediation `manual`, no writes to real repositories). Reference repository: wtf-frontend at 939e838.

## 1. Unit and contract tests

```
uv run pytest tests/darnit/remediation/ tests/darnit/server/ tests/darnit_baseline/ -q
uv run ruff check .
uv run python scripts/validate_sync.py --verbose
```

Expect: every outcome kind round-trips; `pending_kind` set only on `changed_not_passing` with a PENDING re-check; `awaiting` derived; `get_pass_candidates` returns only digest-matching candidates, labels manifest-written files, and refuses an unnamed repository; procedures hold no candidate values.

## 2. Apply result (User Story 3)

Apply remediation on a fresh copy with every planned digest approved (the replay does this). In the fenced JSON block, the six document controls of #681 have `kind: changed_not_passing` and `pending_kind: llm_judgment`; `awaiting.llm_judgment` lists them; the Markdown has a "Next steps" section. OSPS-VM-05.03 has no `pending_kind` (re-check WARN).

## 3. Replay (User Story 4; after #666)

```
uv run python scripts/comply_replay.py   # with recorded judgments and confirmations in comply_replay.toml
```

Expect three PASS counts. Removing one control from `confirmations.controls` lowers PASS after judge-and-confirm by exactly one. Editing one recorded passage makes the replay stop with that control's `missing_excerpts`.

## 4. Headless comply (SC-002, SC-003)

`darnit-e2e` phase 4 with the recorded answers, `confirm_pass_candidate` disallowed. Expect: after remediation the agent calls `get_judgment_requests` and `submit_judgment` for every control in `awaiting.llm_judgment` (or states why not), calls `get_pass_candidates`, and the final report lists each candidate as awaiting confirmation and says confirmations are local. No confirmation is recorded.

## 5. Interactive (SC-004; Layer 3)

In `claude` on a fresh copy: `/darnit-comply openssf-baseline`. Approve the remediation, let the agent improve the files, and at the confirmation step confirm some candidates and decline others. Check that each candidate showed its passages and said whether remediation wrote it and the agent edited it; that the final audit's PASS set is the deterministic set plus exactly the confirmed ones; and that `/darnit-audit` alone on another fresh copy ends with the same confirmation step.
