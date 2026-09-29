# Contract: Context Confirmation (MCP tools and payloads)

These are observable by coding agents and skills; `framework-design.md` is updated first.

## get_pending_data (read-only)

Writes nothing. Each question:

```json
{
  "key": "maintainers",
  "input_type": "confirm",
  "prompt": "...",
  "candidate": {
    "value": ["@alice", "@bob"],
    "origin": {"kind": "sieve_hint", "method": "MAINTAINERS.md", "confidence": 0.95},
    "digest": "sha256:...",
    "label": "UNCONFIRMED candidate - show it to the person; do not confirm without their answer"
  },
  "command_template": "confirm_project_data(accept_candidates={\"maintainers\": \"<candidate digest if the person accepts it>\"}, owner=..., repo=...)  OR  confirm_project_data(maintainers=<the person's answer>, owner=..., repo=...)",
  "allowed_values": null,
  "format_hint": "@user1, @user2"
}
```

- `command_template` never contains a candidate value or a configuration example.
- Enum questions list every allowed value in `allowed_values`; the selector options are omitted when there are more than 4.
- `answer_mapping.value_map["Yes"]` is `{"accept_candidates": {"<key>": "<digest>"}}`.

Response also includes:

```json
"stored_unconfirmed": [
  {"key": "security_contact", "value": "security@example.org", "location": ".project/project.yaml:security.contact"},
  {"key": "has_releases", "value": false, "location": ".project/darnit.yaml:context.has_releases"}
]
```

## confirm_project_data (explicit write; only on the person's explicit instruction)

New and changed parameters (all existing ones kept):

| Parameter | Type | Meaning |
|---|---|---|
| `<every context key the framework defines>` | per definition | The person's answer; recorded as confirmed, basis absent. Generated from framework definitions (adds `platform`, `csl_*`, ...). |
| `accept_candidates` | dict[key, digest] | Confirm the current candidate for each key if its digest still matches; basis = candidate value and origin. Mismatch: rejected, nothing written. |
| `confirm_stored` | list[key] | Confirm the currently stored value (review, FR-010). |
| `reject_stored` | list[key] | Delete from `.project/darnit.yaml`; for `project.yaml` values return the file and field to edit, write nothing. |
| `expires_at` | dict[key, date], optional | Optional expiration recorded with the confirmation. |
| `owner`, `repo`, `host` | | Required. Decides the record location: in-repository if trusted by the operator, otherwise operator-side (identity must be operator-named or CI). |

Result lists, per key: `confirmed (in-repository | operator-side)`, `rejected`, `edit required: <file>:<field>`, or `refused: <reason>` (invalid project file, digest mismatch, unknown key, value outside the vocabulary).

Refusals write nothing. A present-but-invalid `project.yaml` or `darnit.yaml` refuses every write and returns the validation errors.

## remediate_audit_findings / remediation preflight

- Dry run writes nothing.
- A template that reads an unusable key returns `confirmation required: <key>` for that control; the preflight lists candidates as data (value, origin, digest) and a placeholder-only command template.

## remediate_community_spec (darnit-csl)

`code_license`, `governance_mode`, `coc_policy`, and other parameters mapping to CSL context keys default to None; when omitted, only confirmed context is used; if neither exists, the tool returns `confirmation required: <key>`.
