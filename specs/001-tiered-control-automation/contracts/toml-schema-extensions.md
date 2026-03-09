# Contract: TOML Schema Extensions

**Date**: 2026-03-08
**Scope**: Changes to the TOML configuration schema for confidence
and context field configuration.

## Implementation Config Section

New optional fields in the implementation's TOML `[config]` section:

```toml
[config]
# Confidence threshold for auto-accepting context fields.
# Fields with confidence >= this value are auto-accepted.
# Fields below this value prompt the user for confirmation.
# Default: 0.8. Set to 1.0 to force manual confirmation for all.
auto_accept_confidence = 0.8
```

## Context Field Definitions

New optional section for per-field confidence configuration:

```toml
# Per-field confidence overrides
[config.context.maintainers]
auto_detect = true
confidence = 0.9          # Canonical: parsed from CODEOWNERS
detection_method = "codeowners_parse"

[config.context.security_contact]
auto_detect = true
confidence = 0.9          # Canonical: parsed from SECURITY.md
detection_method = "security_md_parse"

[config.context.governance_model]
auto_detect = true
confidence = 0.4          # Heuristic: inferred from repo structure
detection_method = "repo_structure_inference"

[config.context.ci_provider]
auto_detect = true
confidence = 0.95         # Canonical: detected from workflow files
detection_method = "workflow_file_detection"
```

## Backward Compatibility

- All new fields are optional with sensible defaults.
- Existing TOML configs without `auto_accept_confidence` default
  to 0.8.
- Existing context fields without explicit `confidence` use the
  detection method's default confidence (canonical=0.9, heuristic=0.4).
- `auto_detect = false` overrides confidence — field is never
  auto-detected regardless of confidence settings.
