# Contract: Context Field Protocol

**Date**: 2026-03-08
**Scope**: Protocol for context auto-detection with confidence scoring.

## ContextField Model

```python
@dataclass
class ContextField:
    name: str                # e.g., "maintainers", "security_contact"
    value: Any               # Detected or user-provided value
    source: str              # "canonical" | "heuristic" | "user_confirmed" | "user_provided"
    confidence: float        # 0.0 to 1.0
    detection_method: str    # e.g., "codeowners_parse", "git_history_inference"
    auto_accepted: bool      # True if confidence >= threshold
```

## Context Collection Flow

```
1. Load config.auto_accept_confidence (default 0.8)
2. For each context field with auto_detect = true:
   a. Run detection method
   b. Assign confidence based on source type:
      - Canonical file match → 0.9+
      - API response exact match → 0.85+
      - Heuristic inference → 0.3–0.6
   c. Compare confidence to threshold
   d. If >= threshold: auto_accept, source = "canonical"
   e. If < threshold: queue for user confirmation
3. For each field with auto_detect = false:
   - Skip auto-detection entirely
   - Queue for user input (source = "user_provided")
4. Present queued fields to user
5. User confirms or overrides
6. Return final context with all fields resolved
```

## MCP Tool Integration

The context collection flow integrates with existing MCP tools:

- `confirm_project_context`: Enhanced to show confidence levels
  and auto-accepted fields, allowing user to review and override.
- `get_project_config`: Returns context fields with source and
  confidence metadata.
- `init_project_config`: Triggers the collection flow above.

## Implementer Contract

Implementations provide context detection by defining:

1. TOML config with field definitions and confidence settings
2. Detection functions that return `(value, confidence, method)` tuples
3. The framework handles threshold comparison and user prompting

Implementations MUST NOT auto-accept fields that are configured
with `auto_detect = false`, regardless of confidence settings.
