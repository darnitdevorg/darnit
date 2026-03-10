# Quickstart: Getting Started Guide for Contributors

**Date**: 2026-03-10 | **Feature**: 005-getting-started-guide

## Implementation Quickstart

### What to build

A hub-and-spoke documentation system for contributor onboarding:

1. **Hub**: `GETTING_STARTED.md` at repo root — short routing document with two learning paths
2. **Reference guides**: 8 files in `docs/getting-started/` — topic-focused, cross-linked
3. **Tutorials**: 2 files in `docs/tutorials/` — complete copy-paste walkthroughs
4. **Existing doc updates**: Trim README.md, CONTRIBUTING.md, IMPLEMENTATION_GUIDE.md

### Implementation order

1. Create `docs/getting-started/` and `docs/tutorials/` directories
2. Write `docs/getting-started/environment-setup.md` (foundation for all paths)
3. Write `docs/getting-started/framework-development.md` (with Mermaid diagrams)
4. Write `docs/getting-started/implementation-development.md` (TOML controls, handlers)
5. Write `docs/getting-started/cel-reference.md` (CEL syntax and pitfalls)
6. Write `docs/getting-started/testing.md` (test strategy and commands)
7. Write `docs/getting-started/development-workflow.md` (pre-commit, linting, CI)
8. Write `docs/getting-started/troubleshooting.md` (common issues)
9. Write `docs/tutorials/add-new-control.md` (copy-paste tutorial)
10. Write `docs/tutorials/create-new-implementation.md` (copy-paste tutorial)
11. Write `docs/getting-started/README.md` (index with learning paths)
12. Write `GETTING_STARTED.md` (hub document)
13. Trim README.md (remove contributor dev setup, link to hub)
14. Trim CONTRIBUTING.md (keep policy, link to sub-guides)
15. Trim IMPLEMENTATION_GUIDE.md (keep conceptual reference, link to sub-guides)
16. Validate all links work

### Key decisions

- **Hub-and-spoke**: Short hub routes to focused sub-guides
- **Consolidate**: Move content from existing docs, don't duplicate
- **Copy-paste tutorials**: Every file, command, and expected output shown
- **Mermaid diagrams**: Package structure, sieve pipeline, plugin discovery
- **CEL reference**: Dedicated document for CEL syntax (cross-cutting concern)

### Files created/modified

| Action | File | Purpose |
|--------|------|---------|
| Create | `GETTING_STARTED.md` | Hub document |
| Create | `docs/getting-started/README.md` | Sub-guide index |
| Create | `docs/getting-started/environment-setup.md` | Setup instructions |
| Create | `docs/getting-started/framework-development.md` | Framework dev guide |
| Create | `docs/getting-started/implementation-development.md` | Implementation dev guide |
| Create | `docs/getting-started/cel-reference.md` | CEL reference |
| Create | `docs/getting-started/testing.md` | Testing guide |
| Create | `docs/getting-started/development-workflow.md` | Workflow guide |
| Create | `docs/getting-started/troubleshooting.md` | Troubleshooting |
| Create | `docs/tutorials/add-new-control.md` | Tutorial: add control |
| Create | `docs/tutorials/create-new-implementation.md` | Tutorial: new implementation |
| Modify | `README.md` | Trim contributor content, add links |
| Modify | `CONTRIBUTING.md` | Trim to policy, add links |
| Modify | `docs/IMPLEMENTATION_GUIDE.md` | Trim to index/reference, add links |
