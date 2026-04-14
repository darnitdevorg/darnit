# Quickstart: Multi-File Threat Model

## Generate a threat model

Via MCP tool:
```
generate_threat_model
```

Or programmatically:
```python
from darnit_baseline.threat_model.remediation import generate_threat_model_handler

result = generate_threat_model_handler(
    config={"path": "docs/threatmodel/SUMMARY.md", "overwrite": False},
    context=handler_context,
)
```

Output is written to:
```
docs/threatmodel/
├── SUMMARY.md              ← Start here
├── data-flow.md
├── raw-findings.json
└── findings/
    ├── python-sink-dangerous_attr.md
    ├── python-sink-ssrf.md
    └── ...
```

## Read the summary

Open `docs/threatmodel/SUMMARY.md`. The "Top Risks" table shows each vulnerability class with its instance count and how many are mitigated:

```
| Class                    | STRIDE    | Instances | Severity | Mitigated | Details |
|--------------------------|-----------|-----------|----------|-----------|---------|
| Command Injection via... | Tampering | 27        | CRITICAL | 8/27      | [→]     |
```

Click through to any class's detail file to see every instance.

## Record a mitigation decision

1. Find the fingerprint of the finding you want to address. It's in:
   - The raw export (`raw-findings.json`, `fingerprint` field), or
   - Computed from the finding's rule ID + file path + code snippet

2. Create or edit `.project/threatmodel/mitigations.yaml`:

```yaml
version: "1"

entries:
  - fingerprint: "sha256:a1b2c3d4e5f6g7h8"
    status: mitigated
    note: "Input validated at api/validators.py:42"
    reviewer: "@yourname"
    reviewed_at: "2026-04-13"
    query_id: "python.sink.dangerous_attr"
    file_hint: "src/handler.py"
```

3. Regenerate the threat model. The finding now shows as "Mitigated" in the summary and detail file.

## Commit and review

Both `docs/threatmodel/` and `.project/threatmodel/mitigations.yaml` are committed to version control. Mitigation decisions appear in PR diffs for team review.

## Stale entries

If you delete or rename code that a sidecar entry references, the next regeneration flags that entry as `stale: true`. The entry is never auto-deleted — check the sidecar periodically and remove entries you no longer need.

## Legacy migration

If your repo already has a `THREAT_MODEL.md` at the root, the generator:
- Writes the new layout to `docs/threatmodel/` (does not touch the old file)
- Logs a warning with a migration note
- You can remove the old file when ready

The baseline audit (OSPS-SA-03.02) accepts both locations.
