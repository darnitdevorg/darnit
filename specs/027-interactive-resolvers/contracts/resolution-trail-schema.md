# Contract: `resolution_trail` Schema in `HarnessReport`

**Feature**: 027-interactive-resolvers | **Consumers**: report readers, downstream aggregators, CI dashboards, audit-trail verification tools.

## 1. Location in the report

- **RT-1**: Every `PendingFeedbackEntry` in `HarnessReport.pending_feedback` gains a `resolution_trail` field. Every entry, always emitted (even when empty), so consumers can rely on the shape.
- **RT-2**: The report gains a top-level `resolvers_used: list[str]` field. Contents: the `name` of every resolver that was configured for the run, in chain order.
- **RT-2a**: Every `PendingFeedbackEntry` gains an `answer_authority: "asserted" | null` field. Set to `"asserted"` whenever `answered == true`; `null` otherwise. Enforces FR-009 / SC-003 at the report shape level -- downstream consumers can filter for `answer_authority == "asserted"` to identify human-provided values without inspecting the trail.

## 2. `resolution_trail` field shape

Type: `list[ResolutionTrailEntry]`

Empty list when no resolver was offered the question (e.g., the question was answered by an `AnswerSource` before reaching the resolver chain, OR no resolvers were configured for the run).

Non-empty list contains one entry per resolver that was offered the question, in the order they were offered.

## 3. `ResolutionTrailEntry` JSON shape

```json
{
  "resolver_name": "interactive_terminal",
  "outcome": "answered",
  "error_summary": null
}
```

- **RT-3**: `resolver_name: string` -- the `name` attribute of the resolver. Non-empty.
- **RT-4**: `outcome: string` -- one of `"answered"`, `"skipped"`, `"errored"`. Closed set.
- **RT-5**: `error_summary: string | null` -- present ONLY when `outcome == "errored"`. Contains a redacted, 200-char-truncated `str(exc)` of the exception the resolver raised. `null` otherwise.

## 4. Cross-field invariants

- **RT-6**: `outcome == "errored"` implies `error_summary` is a non-empty string.
- **RT-7**: `outcome == "answered"` implies the parent `PendingFeedbackEntry.answered == true`, `answer` is set, and `answer_authority == "asserted"`.
- **RT-8**: Exactly zero or one entries in `resolution_trail` for a given `PendingFeedbackEntry` have `outcome == "answered"` (first non-None wins, no subsequent resolvers were offered).
- **RT-9**: If any entry has `outcome == "answered"`, it is the LAST entry in the list.
- **RT-9a**: `PendingFeedbackEntry.answered == false` implies `answer_authority == null`. The two fields are cross-validated by a Pydantic model validator; a report with `answered: false, answer_authority: "asserted"` is a schema violation.

## 5. Redaction guarantee

- **RT-10**: `error_summary` MUST pass through the same `_redact_secrets` regex table used by feature 026's `_dispatch_llm_step`. Credential patterns (`sk-ant-*`, `Authorization: Bearer *`, `x-api-key: *`, `api_key=*`) are replaced with placeholder strings before the trail entry is constructed.
- **RT-11**: `error_summary` is truncated to 200 characters AFTER redaction. Truncation is a hard character bound; no attempt is made to preserve word boundaries.

## 6. Markdown rendering

`HarnessReport.to_markdown()` renders the trail as a nested list under each pending question:

```markdown
### Pending questions

- **OSPS-GV-01.01** -- security_contact
  - Question: Who is the security contact for this project?
  - Resolution trail:
    - `interactive_terminal`: skipped
    - `gh_issue_comment`: errored -- HTTP 404 on repo lookup
    - `slack_dm`: answered
```

Empty trails are omitted in Markdown (no `Resolution trail:` header) to avoid noise. JSON always emits the field.

## 7. Backwards compatibility

- **RT-12**: A HarnessReport JSON produced by feature 027 is a strict SUPERSET of one produced by feature 026 alone. Consumers reading a 026-era report will not see `resolution_trail` or `resolvers_used`; consumers reading a 027-era report will see them (possibly empty).
- **RT-13**: A consumer that ignores unknown fields on `PendingFeedbackEntry` (Pydantic `extra="allow"` or plain dict access with `.get()`) will process both eras without change.
- **RT-14**: A consumer with `extra="forbid"` on their own model of `PendingFeedbackEntry` will need to add `resolution_trail` and `resolvers_used` fields. This is documented as a schema-evolution break for that specific consumer style; it is not enforced by darnit.

## 8. Example: three-resolver trail

Question offered to three resolvers -- first errors, second skips, third answers:

```json
{
  "control_id": "OSPS-GV-01.01",
  "context_key": "security_contact",
  "question": "Who is the security contact for this project?",
  "answered": true,
  "answer": "security@example.com",
  "answer_authority": "asserted",
  "resolution_trail": [
    {
      "resolver_name": "gh_issue_comment",
      "outcome": "errored",
      "error_summary": "HTTP 404 while fetching /repos/foo/bar: repository not found"
    },
    {
      "resolver_name": "interactive_terminal",
      "outcome": "skipped",
      "error_summary": null
    },
    {
      "resolver_name": "slack_dm",
      "outcome": "answered",
      "error_summary": null
    }
  ]
}
```

An auditor reading this can reconstruct: "we asked GitHub first (errored, no such repo), then the terminal (operator skipped), then Slack (came back with an answer)." All in the report; no log spelunking required.
