# CNCF Project Metadata

The context storage module natively supports reading and writing standard CNCF `.project` fields as well as baseline-specific extensions to maintain context provenance across evaluations.

## Internal Storage Format & Mapping

The project interacts with two types of metadata configurations depending on the schema specification:

### 1. Legacy Formats (`.project.yaml` `x-openssf-baseline` blocks)
Fallback configurations natively dump untracked dynamic keys or existing nested maps into an `x-openssf-baseline: context` property list.

### 2. CNCF `.project` Storage (`.project/project.yaml`)
Native mappings conform with standard CNCF structures.

For example, when saving the **Security Contact** configuration in the CLI, the module updates the underlying `.project/project.yaml` structure:
```yaml
security:
  contact: support@example.com
```

Simultaneously, `context_storage.py` maps the user confirmation and context tracking (data provenance) within the `x-openssf-baseline` extension block:

```yaml
x-openssf-baseline:
  context:
    security_contact:
      value: support@example.com
      source: "user_confirmed"
      confidence: 1.0
      confirmed_at: "2026-04-15"
```
## Supported Keys
Native Keys mapped directly to the `project.yaml` struct:
- `security_contact` → `security.contact`

All unmapped parameters (e.g. `ci_provider`, `has_releases`, etc...) are reliably populated within the runtime dictionary dynamically and nested under `context`.
