# Research: Getting Started Guide for Contributors

**Date**: 2026-03-10 | **Feature**: 005-getting-started-guide

## Research Tasks

### R-001: Optimal documentation structure for hub-and-spoke guides

**Decision**: Two sub-directories under `docs/` — `getting-started/` for reference guides and `tutorials/` for step-by-step walkthroughs.

**Rationale**: Separating tutorials (long, sequential, copy-paste) from reference guides (shorter, navigable, topic-focused) matches how contributors actually use docs: they follow a tutorial once, then reference guides repeatedly. This pattern is used by Django, Rust, and Kubernetes documentation.

**Alternatives considered**:
- Single `docs/getting-started/` directory with all content: Rejected because tutorials are 200+ line documents that would clutter the reference index.
- Separate `docs/contributor/` top-level directory: Rejected because `getting-started/` is more discoverable and intuitive.

### R-002: Content migration strategy for existing docs

**Decision**: Consolidate contributor-facing content into new sub-guides. Trim originals to retain user-facing content and link to new locations.

**Rationale**: Avoids stale duplication. Existing docs have overlapping setup instructions in README.md, CONTRIBUTING.md, and IMPLEMENTATION_GUIDE.md.

**Migration map**:

| Source File | Lines (approx) | Content | Destination |
|-------------|-----------------|---------|-------------|
| CONTRIBUTING.md | 9-27 | Fork/clone/setup | `getting-started/environment-setup.md` |
| CONTRIBUTING.md | 29-60 | Branch/commit/PR workflow | `getting-started/development-workflow.md` |
| CONTRIBUTING.md | 62-80 | Code style/testing reqs | `getting-started/development-workflow.md` |
| README.md | 90-107 | Package structure | `getting-started/framework-development.md` |
| README.md | 177-196 | Creating plugins | Link to `getting-started/implementation-development.md` |
| README.md | 403-416 | Dev setup, tests | `getting-started/environment-setup.md` |
| IMPL_GUIDE | 103-178 | TOML quick start | `tutorials/add-new-control.md` |
| IMPL_GUIDE | 182-312 | Package setup + impl class | `tutorials/create-new-implementation.md` |
| IMPL_GUIDE | 389-610 | TOML config + CEL | `getting-started/cel-reference.md` + `getting-started/implementation-development.md` |
| IMPL_GUIDE | 813-1299 | Custom handlers | `getting-started/implementation-development.md` |
| IMPL_GUIDE | 1302-1516 | Remediation + MCP tools | `getting-started/implementation-development.md` |
| IMPL_GUIDE | 1518-1665 | Testing | `getting-started/testing.md` |
| IMPL_GUIDE | 1664-1720 | Common pitfalls | `getting-started/troubleshooting.md` |

**Alternatives considered**:
- Keep all existing docs intact, only add new: Rejected because it creates stale duplication and confusing multiple sources of truth.
- Delete existing docs entirely: Rejected because README.md and CONTRIBUTING.md serve important user-facing and GitHub-convention roles.

### R-003: Mermaid diagram requirements

**Decision**: Three Mermaid diagrams in `getting-started/framework-development.md`:
1. Package structure (shows darnit, darnit-baseline, darnit-testchecks and their relationships)
2. Sieve pipeline flow (4-phase: file_must_exist → exec/pattern → llm_eval → manual)
3. Plugin discovery mechanism (entry points → discovery → protocol calls)

**Rationale**: These three diagrams map to the three most common questions from new contributors: "What's the package layout?", "How does verification work?", and "How does the framework find my plugin?".

**Alternatives considered**:
- ASCII art diagrams: Rejected because Mermaid renders natively on GitHub and is easier to maintain.
- Separate diagrams file: Rejected because inline diagrams provide context right where they're needed.

### R-004: CEL expression reference scope

**Decision**: Dedicated `cel-reference.md` covering syntax rules, available context variables, custom functions, escaping rules, and common pitfalls. Separate from the implementation development guide.

**Rationale**: CEL is a cross-cutting concern used by both framework and implementation developers. Known pitfalls (negation uses `!` not `not`, TOML literal string escaping with `\.` not `\\.`) are non-obvious and warrant dedicated treatment. The existing IMPLEMENTATION_GUIDE.md buries CEL info within TOML configuration sections.

**Alternatives considered**:
- Inline CEL reference within implementation-development.md: Rejected because CEL reference is frequently consulted independently and would bloat that guide.

### R-005: Tutorial completeness standard

**Decision**: Complete copy-paste tutorials showing every file creation/edit, every command, and expected output at each step.

**Rationale**: Per clarification session, tutorials must be fully self-contained. A contributor should be able to follow them without consulting any other document.

**Alternatives considered**:
- Conceptual walkthroughs with code snippets: Rejected in clarification session.
- Both conceptual + full tutorial: Rejected in clarification session for simplicity.

## Unresolved Items

None. All NEEDS CLARIFICATION items were resolved during the spec clarification phase.
