# Quickstart: Threat Model Remediation Handler

**Branch**: `007-threatmodel-remediation-handler` | **Date**: 2026-03-25

## What This Feature Changes

SA-03.02 remediation now generates a **dynamic, project-specific threat model** instead of dropping a static template. The handler wraps the existing `generate_threat_model` analysis pipeline as a sieve remediation handler.

## Files Modified

| File | Change |
|------|--------|
| `threat_model/remediation.py` | **New file** — sieve handler `generate_threat_model_handler(config, context) -> HandlerResult` |
| `implementation.py` | Register new handler with sieve handler registry |
| `openssf-baseline.toml` | SA-03.02 remediation: replace `file_create` with `generate_threat_model` handler |
| `tests/.../test_remediation.py` | **New file** — handler tests (dynamic generation, fallback, overwrite, dry-run) |

## How It Works

1. User runs `remediate_audit_findings` and SA-03.02 fails
2. Executor resolves SA-03.02's remediation config from TOML
3. Executor calls `generate_threat_model_handler(config, context)`
4. Handler runs the full analysis pipeline: frameworks → assets → threats → chains
5. Handler writes Markdown report to `config["path"]` (default: `THREAT_MODEL.md`)
6. If analysis fails, handler falls back to static template content (pre-resolved by executor)

## Handler Signature

```
generate_threat_model_handler(config: dict, context: HandlerContext) -> HandlerResult
```

**Config fields used**:
- `path`: Output file path (relative to repo)
- `overwrite`: Whether to overwrite existing file (default: false)
- `content`: Pre-resolved template content (fallback source, provided by executor)

**Context fields used**:
- `local_path`: Repository root path
- `owner`: GitHub org/user
- `repo`: Repository name

## Testing Strategy

| Test | What to Verify |
|------|---------------|
| Dynamic generation | Handler produces project-specific threats (not template text) |
| Fallback on error | Handler writes template content when analysis raises an exception |
| Overwrite=false | Handler skips when file exists |
| Overwrite=true | Handler regenerates when file exists |
| Invalid path | Handler returns error result |
| No assets | Handler still writes report (with "no assets" explanation) |
