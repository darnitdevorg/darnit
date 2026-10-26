# Contract: procedures (darnit.server.procedures)

Same rules as the existing procedures (#671): calls name only what the caller passed; an unnamed repository is a placeholder; no step holds a candidate value, a cited passage, or a detected value.

## confirmation_procedure(owner, repo, host, local_path) -> list[str]

Returned by `get_pass_candidates`. Steps, in order:

1. Show every candidate on the page before asking anything: control id and title, what it requires (description), the files, the reasoning, and each cited passage verbatim. Label each "PASS candidate: not compliant until you confirm it".
2. For a candidate with a `remediation` block, say that darnit's remediation wrote the document, whether it was edited afterwards (say so if you edited it in this session), and that the judgment being confirmed is your own. Ask whether the document reflects the project's actual practice, not whether the text reads well.
3. Ask with `ask_user_batch` verbatim through the question tool (AskUserQuestion in Claude Code); without one, ask in plain text, one candidate at a time. Do not pre-fill, recommend, or offer to confirm all.
4. Call `confirm_pass_candidate(control_ids=[<only the controls the person answered Confirm for>], <owner, repo, host, local_path>)` once. Confirm nothing on silence, "Skip for now", "Do not confirm", or an instruction that names no candidate the person was shown.
5. If `remaining` is not empty, call `get_pass_candidates(..., control_ids=<remaining>)` and repeat.
6. Tell the person what was confirmed, declined, and skipped, and that confirmations are recorded for them on this machine only: CI or another maintainer will see those controls PENDING until they confirm there.

## remediation_next_steps(owner, repo, host, local_path, awaiting, run_id) -> list[str]

Returned in the apply report when `awaiting` is not empty:

- If `llm_judgment` ids exist: "Improve the generated files first if you plan to, then call `get_judgment_requests(<args>)` and follow its procedure; the candidates it produces are confirmed in the next step."
- Always when anything awaits: "Then call `get_pass_candidates(<args>, run_id=<run_id>)` and follow its procedure."

## Comply and audit flows (skills)

`/darnit-comply` (after "enhance generated files") and `/darnit-audit` (after judgments) each add one step: call `get_pass_candidates` with the repository and, in comply, the apply's `run_id`, and follow its `procedure`. The skills do not restate the steps.
