"""The steps a coding agent follows after a data or judgment tool returns.

One source for the procedure text that ``get_pending_data``,
``confirm_project_data``, and ``get_judgment_requests`` return, so every
skill and client follows the same steps (framework-design 5.4, 7.10).
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
