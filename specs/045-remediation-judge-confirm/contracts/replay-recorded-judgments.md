# Contract: replay with recorded judgments and confirmations (test tooling)

Applies to #666's `scripts/comply_replay.py` and `scripts/comply_replay.toml` (#675 is closed). Lands after #666.

## Input (comply_replay.toml)

```toml
[judgments."OSPS-GV-03.01"]
verdict = "pass"
reasoning = "..."
cited_evidence = ["...verbatim passage from the generated CONTRIBUTING.md..."]

[confirmations]
controls = ["OSPS-GV-03.01"]
```

Written by a person from the documents the replay's remediation generates. A `confirmations.controls` entry without a `pass` judgment is a fixture error and stops the replay.

## Steps added after the post-remediation audit

1. For each recorded judgment: `submit_judgment_impl(..., model="recorded", model_version="comply_replay.toml")` against the replay's copy, with the replay's isolated `HOME`.
2. A `rejected` result stops the replay, printing the control and `missing_excerpts`. A `finding` is reported.
3. `confirm_pass_candidates_impl(local_path, confirmations.controls, owner=..., repo=...)`.
4. Audit again.

## Output

- PASS before remediation, PASS after remediation (deterministic), PASS after judge-and-confirm.
- The remediation outcomes, with `pending_kind`.
- `comply_replay_expected.json` gains `pass_after_confirm`; a lower value fails the replay, as for the other counts.

## Invariants

- No module under `packages/` reads `comply_replay.toml` (asserted by a test).
- The confirmation store, audit cache, and run manifests live under the replay's throwaway `HOME`; nothing reaches the operator's real store.
