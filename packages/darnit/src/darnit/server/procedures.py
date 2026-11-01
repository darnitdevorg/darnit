"""The steps a coding agent follows after a data or judgment tool returns.

One source for the procedure text that ``get_pending_data``,
``confirm_project_data``, ``get_judgment_requests``, ``get_pass_candidates``,
and ``remediate_audit_findings`` return, so every skill and client follows
the same steps (framework-design 5.4, 7.10, 15.9).
Calls name only what the caller passed (the repository and checkout);
an unnamed repository is a placeholder, never a value read from the
checkout, and no step holds a candidate or detected value.
"""

from __future__ import annotations

import json

_OWNER = "<owner of the audited repository>"
_REPO = "<name of the audited repository>"


def _args(owner: str | None, repo: str | None, host: str | None, local_path: str) -> str:
    parts = [
        f"owner={json.dumps(owner) if owner else _OWNER}",
        f"repo={json.dumps(repo) if repo else _REPO}",
    ]
    if host and host != "github.com":
        parts.append(f"host={json.dumps(host)}")
    parts.append(f"local_path={json.dumps(local_path)}")
    return ", ".join(parts)


def data_next_step(owner: str | None, repo: str | None, local_path: str) -> str:
    """The call that follows a ``confirm_project_data`` call (``get_pending_data`` takes no host)."""
    return (
        f"Next: call get_pending_data({_args(owner, repo, None, local_path)}) for the remaining questions "
        "and follow its procedure; when it returns status complete, re-run the audit."
    )


def data_collection_procedure(owner: str | None, repo: str | None, local_path: str) -> list[str]:
    """Ordered steps for collecting project data from the person (``get_pending_data`` takes no host)."""
    args = _args(owner, repo, None, local_path)
    return [
        "1. For each question with a candidate, show the person candidate.value and candidate.origin, "
        "labelled UNCONFIRMED. A candidate is never a fact or a default answer.",
        "2. Ask every question at once: pass ask_user_batch verbatim to your question tool (AskUserQuestion "
        "in Claude Code). A typed answer under Other is the person's answer. If a client has no question "
        "tool, ask in plain text, listing every allowed_values entry. format_hint is a format, never an "
        "answer. Do not pre-fill or suggest answers.",
        '3. "Skip for now", or a person who says skip or does not know, leaves that key out. For '
        '"Answer in chat", ask that one question in plain text.',
        f"4. Record the answers in one call: confirm_project_data({args}, <key>=<the person's answer>). "
        "Yes/No questions take true/false. For a Yes on a candidate pass "
        'accept_candidates={"<key>": "<that question\'s candidate.digest>"}, filled in only after the '
        "person said yes. Pass only what the person said, never a detected value.",
        f"5. Call get_pending_data({args}) again and repeat from step 1 until status is complete.",
        "6. If stored_unconfirmed is not empty, show every entry (key, value, location) labelled "
        "unconfirmed, ask which to keep and which to reject, and make one confirm_project_data call with "
        "confirm_stored and reject_stored holding only the keys the person named. For an edit required "
        "result, tell the person which file and field to edit.",
        "7. Tell the person what was confirmed, rejected, left to edit, and skipped, and which controls "
        "the confirmed keys affect (affects_controls).",
        "Confirm a not-applicable claim or a PASS candidate only when the operator explicitly names it.",
    ]


def judgment_procedure(owner: str, repo: str, host: str, local_path: str) -> list[str]:
    """Ordered steps for judging the controls on a ``get_judgment_requests`` page."""
    args = _args(owner, repo, host, local_path)
    return [
        "1. For each request, judge the control from its prompt and analysis_hints, using only the "
        "files it lists (keys into files).",
        f'2. Call submit_judgment(control_id=<its control_id>, verdict="pass" or "fail", '
        "reasoning=<your reasoning>, cited_evidence=[<passages copied verbatim from those files' "
        f"content>], model=<your model>, model_version=<your model version>, {args}) once per request. "
        "A paraphrased citation is rejected.",
        "3. A pass verdict becomes a PASS candidate that stays non-compliant until the operator "
        "confirms it; a fail verdict is a suggestive finding. Never report your verdict as the audit "
        "result.",
        f"4. If remaining is not empty, call get_judgment_requests({args}, control_ids=<remaining>) "
        "and repeat; stop when remaining is empty.",
        "5. Controls in skipped already have a stored PASS candidate: do not request or judge them again.",
        "Confirm a PASS candidate only when the operator explicitly names it.",
    ]


def confirmation_procedure(owner: str, repo: str, host: str, local_path: str) -> list[str]:
    """Ordered steps for asking the operator about the PASS candidates on a ``get_pass_candidates`` page."""
    args = _args(owner, repo, host, local_path)
    return [
        "1. Show every candidate on the page before asking anything: control_id and title, what it "
        "requires (description), the files, the reasoning, and each cited_evidence passage verbatim. "
        'Label each "PASS candidate: not compliant until you confirm it".',
        "2. For a candidate with a remediation block, say that darnit's remediation wrote the document, "
        "whether it was edited afterwards (say so if you edited it), and that the judgment to confirm is "
        "your own. Ask whether the document reflects the project's actual practice, not whether the "
        "text reads well.",
        "3. Ask with ask_user_batch verbatim through your question tool (AskUserQuestion in Claude Code); "
        "without one, ask in plain text, one candidate at a time. Do not pre-fill, recommend, or offer "
        "to confirm all.",
        f"4. Call confirm_pass_candidate(control_ids=[<only the controls the person answered "
        f'"Confirm" for>], {args}) once. Confirm nothing on silence, "Skip for now", "Do not confirm", '
        "or an instruction that names no candidate the person was shown.",
        f"5. If remaining is not empty, call get_pass_candidates({args}, control_ids=<remaining>) and "
        "repeat from step 1.",
        "6. Tell the person what was confirmed, declined, and skipped, and that confirmations are "
        "recorded for them on this machine only: CI or another maintainer sees those controls PENDING "
        "until they confirm there. Controls in awaiting_judgment need a judgment first.",
    ]


def remediation_next_steps(
    owner: str | None, repo: str | None, host: str | None, local_path: str, awaiting: dict[str, list[str]], run_id: str
) -> list[str]:
    """What follows an apply whose changed controls await a judgment or a confirmation (15.4, 15.9)."""
    if not awaiting:
        return []
    args = _args(owner, repo, host, local_path)
    steps = []
    if awaiting.get("llm_judgment"):
        steps.append(
            f"Awaiting a model judgment: {', '.join(awaiting['llm_judgment'])}. Improve the generated files "
            f"first if you plan to, then call get_judgment_requests({args}) and follow its procedure; the "
            "PASS candidates it produces are confirmed in the next step."
        )
    if awaiting.get("confirmation"):
        steps.append(f"Awaiting the operator's confirmation: {', '.join(awaiting['confirmation'])}.")
    steps.append(
        f'Then call get_pass_candidates({args}, run_id="{run_id}") and follow its procedure. Until the '
        "operator confirms, these controls are not compliant."
    )
    return steps
