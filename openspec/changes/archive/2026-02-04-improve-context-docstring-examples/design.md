# Design: Improve Context Docstring Examples

## Context

The `darnit.context` module provides context detection (maintainers, security contacts, etc.) using a sieve pattern. The module docstrings include usage examples that currently use `print()` to show results.

## Goals / Non-Goals

**Goals:**
- Make docstring examples more practical and idiomatic
- Show property access patterns developers would actually use
- Keep examples concise and clear

**Non-Goals:**
- Adding doctest-style executable examples (too complex for this API)
- Changing any actual code behavior
- Updating examples in other modules

## Decisions

### Decision 1: Use variable assignment with explanatory comments

Rather than:
```python
print(f"Maintainers: {result.value}")
```

Use:
```python
maintainers = result.value  # List of detected maintainers
```

**Rationale:** This shows what developers would actually do—capture the value for use elsewhere. Comments explain without executing.

### Decision 2: Keep the conditional structure

The if/else showing high-confidence vs needs-confirmation is valuable for understanding the API. We'll keep it but change what happens in each branch.
