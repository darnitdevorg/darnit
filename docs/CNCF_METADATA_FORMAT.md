# CNCF Metadata Format Support

Darnit natively supports the emergent Cloud Native Computing Foundation (CNCF) specification for project metadata configuration. The overarching goal of the CNCF Project Metadata initiative is to provide a single, universal `.project/project.yaml` metadata schema across open-source initiatives.

## Implementation Details

While Darnit originally serialized project variables into the custom `x-openssf-baseline` block, we've updated `darnit.config.context_storage` to additionally support `.project/project.yaml`'s newly formatted `extensions` mapping constraint in order to provide true cross-compatibility:

```yaml
name: "darnit"
description: "AI-powered compliance auditing framework"
extensions:
  openssf_baseline:
    config:
      context:
        is_library: true
        has_releases: false
        has_subprojects: true
```

### Data Serialization and Round-Trips

1. When a user provides manual parameters via CLI interactive prompts, the values are evaluated by the prompt schemas.
2. Changes to these contexts fall-through the backend serialization handlers (`save_context_value`) wherein it writes the schema *both* equivalently to the legacy `x-openssf-baseline` format AND maps it dynamically to the `.project/project.yaml` `extensions.openssf_baseline.config.context` keys block.
3. Reading (`load_context`) remains retro-compatible through robust YAML parsing logic.

*Note: The upstream drafting for the CNCF specification is still active; Darnit's storage wrappers will remain un-versioned relative to strict CNCF formatting schemas until their V1 specifications are definitively finalized.*
