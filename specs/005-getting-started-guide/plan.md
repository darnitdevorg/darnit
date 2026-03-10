# Implementation Plan: Getting Started Guide for Contributors

**Branch**: `005-getting-started-guide` | **Date**: 2026-03-10 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/005-getting-started-guide/spec.md`

## Summary

Create a hub-and-spoke contributor documentation system: a short `GETTING_STARTED.md` hub at the repository root linking to focused sub-guides in `docs/getting-started/` and `docs/creating-implementations/`. Consolidate contributor-facing content from README.md, CONTRIBUTING.md, and IMPLEMENTATION_GUIDE.md into the new sub-guides, trimming originals to avoid duplication. Include complete copy-paste tutorials, Mermaid architecture diagrams, CEL reference, and troubleshooting.

## Technical Context

**Language/Version**: Markdown (GitHub-Flavored Markdown with Mermaid diagram support)
**Primary Dependencies**: None (pure documentation)
**Storage**: Filesystem (Markdown files in `docs/` directory)
**Testing**: Manual walkthrough validation; link checking
**Target Platform**: GitHub repository (rendered by GitHub Markdown engine)
**Project Type**: Documentation
**Performance Goals**: N/A
**Constraints**: Must render correctly in GitHub's Markdown renderer; Mermaid diagrams must be GitHub-native
**Scale/Scope**: ~8-12 new Markdown files, ~3-4 existing files trimmed/updated

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Plugin Separation | PASS | Documentation only; no code imports. Guide will document separation rules accurately. |
| II. Conservative-by-Default | PASS | Documentation only; no compliance logic changes. Guide will document conservative principles. |
| III. TOML-First Architecture | PASS | Tutorials will demonstrate TOML-first approach. No Python control registration in examples. |
| IV. Never Guess User Values | PASS | Tutorials will demonstrate explicit user confirmation patterns. |
| V. Sieve Pipeline Integrity | PASS | Architecture diagrams and tutorials will accurately depict the 4-phase pipeline. |

All gates pass. No violations to justify.

## Project Structure

### Documentation (this feature)

```text
specs/005-getting-started-guide/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
# New files to create
GETTING_STARTED.md                              # Hub document at repo root

docs/getting-started/
├── README.md                                   # Index with learning paths
├── environment-setup.md                        # Prerequisites, fork, clone, deps
├── framework-development.md                    # Sieve pipeline, handlers, plugin protocol
├── implementation-development.md               # TOML controls, CEL, entry points
├── cel-reference.md                            # CEL syntax, context vars, pitfalls
├── testing.md                                  # Test strategy, running tests, adding tests
├── development-workflow.md                     # Pre-commit checklist, linting, spec sync
└── troubleshooting.md                          # Common issues and solutions

docs/tutorials/
├── add-new-control.md                          # Copy-paste tutorial: add control to baseline
└── create-new-implementation.md                # Copy-paste tutorial: new plugin from scratch

# Existing files to modify (trim contributor content, add links)
README.md                                       # Trim dev setup sections, link to GETTING_STARTED.md
CONTRIBUTING.md                                 # Trim to lightweight policy, link to sub-guides
docs/IMPLEMENTATION_GUIDE.md                    # Trim to index + conceptual reference, link to sub-guides
```

**Structure Decision**: Hub-and-spoke with two sub-directories under `docs/`: `getting-started/` for onboarding guides and `tutorials/` for copy-paste walkthroughs. Tutorials are separated because they are long, self-contained documents that serve a different purpose than reference guides.

## Complexity Tracking

No constitution violations. Table not needed.
