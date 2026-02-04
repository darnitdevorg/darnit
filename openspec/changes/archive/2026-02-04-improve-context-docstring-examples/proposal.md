# Proposal: Improve Context Docstring Examples

## Why

The module docstrings in `darnit.context` use `print()` statements in their examples, which is output-focused rather than showing practical API usage patterns. Better examples would demonstrate how to access and use the result properties.

## What Changes

- Rewrite example code in `context/__init__.py` docstring to show property access patterns
- Rewrite example code in `context/sieve.py` docstring for consistency
- Focus on practical usage (assigning to variables, conditional logic) rather than printing

## Capabilities

### Modified Capabilities
- `context-module-documentation`: Examples now demonstrate idiomatic usage patterns

## Impact

- `packages/darnit/src/darnit/context/__init__.py`: Update docstring example (~5 lines)
- `packages/darnit/src/darnit/context/sieve.py`: Update docstring example (~5 lines)
