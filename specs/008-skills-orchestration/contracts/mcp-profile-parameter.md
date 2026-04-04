# Contract: MCP Tool Profile Parameter

**Feature**: 008-skills-orchestration | **Date**: 2026-04-04

## Overview

All audit-related MCP tools accept an optional `profile` parameter that filters the operation to a named audit profile.

## Affected Tools

- `audit_openssf_baseline` — filters which controls are evaluated
- `remediate_audit_findings` — filters which controls are remediated
- `get_pending_context` — filters which context questions are asked
- `list_available_checks` — filters which controls are listed

## Parameter Specification

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `profile` | string | No | None | Audit profile name. Short name (e.g., "onboard") or qualified name (e.g., "gittuf:onboard") |

## Behavior

- When `profile` is `None`: all controls are used (backward compatible)
- When `profile` is a short name: resolved across all loaded implementations; error if ambiguous
- When `profile` is `<impl>:<name>`: resolved against the named implementation only
- When `profile` is not found: return error with list of available profiles

## Error Response Format

When profile resolution fails:

```json
{
  "error": "Profile 'nonexistent' not found",
  "available_profiles": {
    "openssf-baseline": ["level1_quick", "security_critical", "access_control"],
    "gittuf": ["onboard", "verify"]
  }
}
```

When profile is ambiguous:

```json
{
  "error": "Profile 'onboard' is defined by multiple implementations",
  "implementations": ["gittuf", "reproducibility"],
  "hint": "Use 'gittuf:onboard' or 'reproducibility:onboard' to disambiguate"
}
```
