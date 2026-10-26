# Contract: get_pass_candidates (MCP tool)

Registered on every framework server beside `get_judgment_requests`, `submit_judgment`, and `confirm_pass_candidate` (framework-design 5.4). Read only: records nothing.

```
get_pass_candidates(
  owner: str, repo: str, host: str = "github.com", local_path: str = ".",
  control_ids: list[str] | None = None, run_id: str | None = None
) -> str  # JSON text, structured_output=False, like get_judgment_requests
```

## Success

```json
{
  "status": "ok",
  "procedure": ["1. ...", "2. ...", "..."],
  "candidates": [
    {
      "control_id": "OSPS-GV-03.01",
      "title": "...",
      "description": "...",
      "files": ["CONTRIBUTING.md"],
      "reasoning": "...",
      "cited_evidence": ["...verbatim..."],
      "model": "...",
      "model_version": "...",
      "source": "mcp_agent",
      "evidence_digest": "sha256:...",
      "remediation": {"run_id": "01...", "path": "CONTRIBUTING.md", "written": true, "edited_after_write": true}
    }
  ],
  "ask_user_batch": [
    {"question": "Confirm the PASS candidate for OSPS-GV-03.01 (CONTRIBUTING.md)?", "header": "GV-03.01",
     "multiSelect": false,
     "options": [{"label": "Confirm", "description": "..."},
                 {"label": "Do not confirm", "description": "..."},
                 {"label": "Skip for now", "description": "..."}]}
  ],
  "awaiting_judgment": ["OSPS-DO-03.01"],
  "remaining": []
}
```

- `candidates`: controls left `PENDING` with `pending.kind = "confirmation"` by an audit of `local_path` for the named repository, optionally limited to `control_ids`, sorted by id. Each entry's candidate matches the current evidence digest.
- `remediation`: present only when `run_id` is given and a judged file is in that run's manifest; `edited_after_write` compares the file's current content digest with the manifest's `after_digest`.
- `ask_user_batch`: one question per candidate on this page, no default, no option that confirms more than one candidate.
- `awaiting_judgment`: controls still `PENDING (llm_judgment)` (never judged, or the content changed since); judge them with `get_judgment_requests` first.
- Pages stay under 40,000 bytes; `remaining` lists candidates not on this page.

## Refusals and errors

- Repository not named (identity not trusted-eligible): `{"status": "rejected", "rejection": {"reason": "name the audited repository ..."}}`, as `get_judgment_requests`.
- Invalid `local_path`, unreadable operator configuration, audit failure: `{"status": "error", "error": "..."}`.
- Unknown `run_id`: `status: ok`, no `remediation` blocks, and `"note": "run <id> not found for <repository>"`.

## Invariants

- Never writes the confirmation store, the audit cache, or the repository.
- Never returns a candidate whose digest differs from the current evidence.
- Never returns candidate values inside `procedure` text; the procedure holds placeholders and the caller-supplied repository only (as `judgment_procedure`).
