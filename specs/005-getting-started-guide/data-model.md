# Data Model: Getting Started Guide for Contributors

**Date**: 2026-03-10 | **Feature**: 005-getting-started-guide

## Overview

This feature is documentation-only. There are no database entities, API models, or state machines. The "data model" here describes the document structure and relationships between guide files.

## Document Entities

### Hub Document

- **Entity**: `GETTING_STARTED.md` (repository root)
- **Purpose**: Entry point for all contributors; routes to appropriate sub-guide
- **Relationships**: Links to all `docs/getting-started/*.md` and `docs/tutorials/*.md`
- **Attributes**:
  - Title and brief project description
  - Two learning paths (framework dev, implementation dev)
  - Prerequisites summary
  - Quick links to all sub-guides

### Reference Guides

- **Entity**: `docs/getting-started/*.md` (7 files)
- **Purpose**: Topic-focused reference documents for ongoing consultation
- **Relationships**: Cross-link to each other and to tutorials; linked from hub
- **Files**:
  - `README.md` — Index with learning path navigation
  - `environment-setup.md` — Prerequisites and initial setup
  - `framework-development.md` — Core framework architecture and development
  - `implementation-development.md` — TOML controls, handlers, entry points
  - `cel-reference.md` — CEL expression syntax and pitfalls
  - `testing.md` — Test strategy, running tests, adding tests
  - `development-workflow.md` — Pre-commit checklist, linting, CI
  - `troubleshooting.md` — Common issues and solutions

### Tutorials

- **Entity**: `docs/tutorials/*.md` (2 files)
- **Purpose**: Complete copy-paste walkthroughs followed once during onboarding
- **Relationships**: Linked from hub and from relevant reference guides
- **Files**:
  - `add-new-control.md` — Add a control to OpenSSF Baseline
  - `create-new-implementation.md` — Create a new compliance plugin from scratch

### Modified Existing Documents

- **Entity**: `README.md`, `CONTRIBUTING.md`, `docs/IMPLEMENTATION_GUIDE.md`
- **Purpose**: Trimmed to remove contributor-facing content; updated with links to new guides
- **Relationships**: Link to hub and relevant sub-guides

## Document Navigation Flow

```
GETTING_STARTED.md (hub)
├── "I want to work on the framework" path
│   ├── environment-setup.md
│   ├── framework-development.md (with Mermaid diagrams)
│   ├── testing.md
│   └── development-workflow.md
│
├── "I want to create/modify an implementation" path
│   ├── environment-setup.md
│   ├── implementation-development.md
│   ├── cel-reference.md
│   ├── Tutorial: add-new-control.md
│   ├── Tutorial: create-new-implementation.md
│   ├── testing.md
│   └── development-workflow.md
│
└── Common resources
    ├── troubleshooting.md
    └── development-workflow.md
```

## Validation Rules

- Every sub-guide MUST be reachable from the hub within 1 click
- Every sub-guide MUST link back to the hub
- No contributor-facing content should remain duplicated across original docs and new guides
- All internal links MUST use relative paths
- Mermaid diagrams MUST render in GitHub's Markdown viewer
