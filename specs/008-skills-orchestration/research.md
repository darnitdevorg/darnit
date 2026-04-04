# Research: Skills-Based Orchestration Layer with Audit Profiles

**Feature**: 008-skills-orchestration | **Date**: 2026-04-04

## R1: Claude Code Skill System — How Skills Work

**Decision**: Skills are `.md` files registered in the project's settings or CLAUDE.md. They are prompt templates that Claude Code loads and executes as structured workflows.

**Rationale**: Claude Code skills are the native mechanism for defining reusable workflows. They're loaded when the user invokes a slash command (e.g., `/audit`). The skill prompt gives Claude structured instructions, and Claude then uses available tools (MCP, Bash, etc.) to execute the steps. No Python runtime code is needed for the orchestration — the skill is pure prompt engineering.

**Key findings**:
- Skills are defined as markdown files with instructions Claude follows
- Skills can accept arguments (e.g., `/audit --profile onboard`)
- Skills have access to all tools available in the conversation (MCP tools, Bash, Read, Write, etc.)
- Skills can include conditional logic ("if the audit shows failures, then...")
- Skills can prompt the user for input and wait for responses
- Skills are registered via the project's skill configuration

**Alternatives considered**:
- Custom Python CLI wrapper: Rejected — adds runtime code, doesn't integrate with Claude Code's tool ecosystem
- MCP resource-based workflow: Rejected — MCP resources are read-only, can't drive multi-step flows

## R2: Profile Filtering Integration Points

**Decision**: Profile filtering happens at the control selection layer, before controls enter the sieve pipeline. The `run_sieve_audit()` function already accepts a `controls` parameter for pre-filtered control lists.

**Rationale**: The sieve orchestrator doesn't need to know about profiles. Profiles are a selection mechanism — they determine which controls to evaluate. The existing `controls` parameter on `run_sieve_audit()` (audit.py:316) already supports passing a pre-filtered list. Profile resolution (name → control IDs) happens in a new utility function, and the filtered list is passed through the existing parameter.

**Key findings**:
- `run_sieve_audit()` accepts `controls: list[str] | None` — when None, all controls are used
- The existing tag-based filtering in `filtering/filters.py` provides a model for profile tag filters
- Profile resolution needs: (1) load profiles from TOML, (2) resolve control IDs from explicit list or tag filter, (3) intersect with any additional `--tags` filters
- Context gathering already accepts `control_ids` parameter in `get_pending_context()`
- Remediation already filters by control ID in `remediate_audit_findings`

**Alternatives considered**:
- Adding profile awareness to the sieve orchestrator: Rejected — violates separation of concerns, sieve should remain profile-agnostic
- Tag-only approach (no explicit control lists): Rejected — issue #140 specifically requires explicit control ID lists as the primary mechanism, with tags as an alternative

## R3: TOML Schema for Audit Profiles

**Decision**: Add `[audit_profiles.<name>]` sections to framework TOML with `description`, `controls` (list of IDs), and optional `tags` (filter dict).

**Rationale**: Follows the existing TOML-first architecture. Profile metadata lives alongside control definitions in the same file. The schema is minimal — a profile is a name, a description, and a way to select controls.

**Key findings**:
- Schema extension to `FrameworkConfig` in `framework_schema.py`
- New `AuditProfileConfig` Pydantic model with: `description: str`, `controls: list[str] = []`, `tags: dict[str, Any] = {}`
- At least one of `controls` or `tags` must be non-empty (validation rule)
- Profile names must be valid Python identifiers (used as TOML keys)
- Resolution order: explicit `controls` list first, then `tags` filter, then intersection with `--tags` CLI filter

**Example TOML**:
```toml
[audit_profiles.level1_quick]
description = "Level 1 controls only — quick compliance check"
tags = { level = 1 }

[audit_profiles.security_critical]
description = "High-severity security controls"
tags = { security_severity_gte = 8.0 }

[audit_profiles.access_control]
description = "Access control domain controls"
controls = ["OSPS-AC-01.01", "OSPS-AC-02.01", "OSPS-AC-03.01"]
```

**Alternatives considered**:
- Separate profiles TOML file: Rejected — adds file management complexity, profiles are tightly coupled to controls
- Profile inheritance (`extends = "base"`): Rejected — out of scope per spec, flat independent profiles are simpler

## R4: Skill-MCP Integration Pattern

**Decision**: Each skill calls MCP tools by name in its prompt instructions. Claude executes the tools and interprets results inline.

**Rationale**: Skills don't need a programmatic API to MCP tools — Claude Code already has access to all registered MCP tools. The skill prompt simply instructs Claude: "Call `audit_openssf_baseline` with these parameters" and Claude does it. For PENDING_LLM controls, Claude reads the consultation request from the audit results and provides its own judgment.

**Key findings**:
- Skills reference MCP tools by their registered names (e.g., `audit_openssf_baseline`, `get_pending_context`, `confirm_project_context`)
- Skills can inspect MCP tool output and make decisions based on content
- For PENDING_LLM: the audit tool returns results with `status: "PENDING_LLM"` and `evidence.llm_consultation` — the skill instructs Claude to resolve these using its own reasoning
- For WARN controls: the skill instructs Claude to explain each WARN to the user and suggest manual verification steps
- Error handling: if an MCP tool fails, the skill instructs Claude to report the error and suggest alternatives

**Alternatives considered**:
- Wrapper Python functions that call MCP tools: Rejected — unnecessary indirection, Claude already has direct MCP access
- Hardcoded tool sequences: Rejected — skills should be adaptive (e.g., skip context collection if no WARNs)

## R5: Profile Resolution and Disambiguation

**Decision**: Profile names are resolved by scanning all loaded implementations. If exactly one match, use it. If multiple matches, require `<impl>:<profile>` syntax.

**Rationale**: Most deployments use a single implementation (openssf-baseline). Requiring the prefix every time would be unnecessarily verbose. The disambiguation rule handles the multi-implementation case gracefully.

**Key findings**:
- `get_audit_profiles()` returns `dict[str, AuditProfile]` where keys are profile names
- Resolution function: `resolve_profile(name, implementations) -> (impl_name, AuditProfile)`
- If `name` contains `:`, split into `impl:profile` and resolve directly
- If `name` has no `:`, scan all implementations for matching profile name
- If exactly one match: return it
- If zero matches: raise error with list of all available profiles
- If multiple matches: raise error listing which implementations define it

**Alternatives considered**:
- Always require prefix: Rejected — too verbose for the common single-implementation case
- Global unique namespace with registration-time collision detection: Rejected — implementations can't coordinate naming
