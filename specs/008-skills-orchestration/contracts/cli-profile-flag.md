# Contract: CLI --profile Flag

**Feature**: 008-skills-orchestration | **Date**: 2026-04-04

## Overview

The `--profile` flag is added to CLI commands that operate on controls.

## Affected Commands

```bash
darnit audit --profile <name> [REPO_PATH]
darnit plan --profile <name> [REPO_PATH]
darnit profiles [--impl <name>]          # New command: list profiles
```

## Flag Specification

| Flag | Short | Type | Default | Description |
|------|-------|------|---------|-------------|
| `--profile` | `-p` | string | None | Audit profile name (short or qualified) |

## Behavior

- Same resolution logic as MCP parameter (short name auto-resolves, qualified name for disambiguation)
- Composes with existing `--tags` filter (intersection)
- Composes with existing `--level` filter (intersection)

## `darnit profiles` Command

Lists available profiles across all loaded implementations.

```bash
# List all profiles
darnit profiles

# List profiles for a specific implementation
darnit profiles --impl openssf-baseline
```

Output format:
```
openssf-baseline:
  level1_quick       Level 1 controls only — quick compliance check (12 controls)
  security_critical  High-severity security controls (8 controls)
  access_control     Access control domain controls (3 controls)
```
