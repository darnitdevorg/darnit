# Feature Specification: Getting Started Guide for Contributors

**Feature Branch**: `005-getting-started-guide`
**Created**: 2026-03-10
**Status**: Draft
**Input**: User description: "I want to create/update documents to have an in depth getting started guide for folks who want to work on this project both working on the framework and working on an implementation toml"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Framework Developer Onboarding (Priority: P1)

A new contributor wants to work on the core darnit framework (the plugin system, sieve pipeline, configuration, or MCP tools). They need to understand how to set up their development environment, run tests, understand the architecture, and make changes without breaking the plugin contract.

**Why this priority**: The framework is the foundation. Contributors who can't get started on the framework can't contribute to any part of the project. This is the highest-leverage documentation to write.

**Independent Test**: Can be fully tested by having a developer with no prior project knowledge follow the guide from scratch and successfully make a framework change (e.g., add a test, modify a handler) within 30 minutes.

**Acceptance Scenarios**:

1. **Given** a developer has cloned the repo for the first time, **When** they follow the framework getting started guide, **Then** they can run all tests, linters, and validation scripts successfully within 15 minutes.
2. **Given** a developer wants to modify a built-in handler, **When** they consult the guide's architecture section, **Then** they understand the sieve pipeline, plugin protocol, and separation rules without needing to ask for help.
3. **Given** a developer has made a framework change, **When** they follow the pre-commit checklist in the guide, **Then** all validation gates pass before they submit a PR.

---

### User Story 2 - Implementation Developer Onboarding (Priority: P1)

A new contributor wants to create a new compliance implementation or modify the existing OpenSSF Baseline implementation. They need to understand the TOML control definition format, the plugin protocol, and how to register their implementation.

**Why this priority**: Implementation contributions (new controls, new compliance frameworks) are the primary way the project grows. Making this path clear and well-documented directly drives adoption.

**Independent Test**: Can be fully tested by having a developer follow the guide to add a new control to the existing implementation's TOML file and verify it works end-to-end.

**Acceptance Scenarios**:

1. **Given** a developer wants to add a new control, **When** they follow the implementation guide, **Then** they can define the control in TOML, run the audit, and see the new control appear in results.
2. **Given** a developer wants to create a brand new compliance framework implementation, **When** they follow the guide's "new implementation" walkthrough, **Then** they have a working plugin registered via entry points that the framework discovers.
3. **Given** a developer is writing CEL expressions for control passes, **When** they consult the guide's CEL reference section, **Then** they understand syntax rules, available context variables, and common pitfalls.

---

### User Story 3 - Environment Setup and Troubleshooting (Priority: P2)

A contributor encounters issues during setup (missing dependencies, test failures, authentication issues) and needs to self-diagnose and resolve common problems.

**Why this priority**: Setup friction is the #1 reason contributors abandon projects. A troubleshooting section prevents this and reduces maintainer burden.

**Independent Test**: Can be tested by intentionally omitting a setup step and verifying the troubleshooting section identifies and resolves the issue.

**Acceptance Scenarios**:

1. **Given** a developer's tests fail due to missing authentication, **When** they consult the troubleshooting section, **Then** they find the resolution steps and fix the issue.
2. **Given** a developer is on an unsupported environment configuration, **When** they check the prerequisites section, **Then** they know exactly what versions and tools are required.

---

### User Story 4 - Architecture Understanding (Priority: P2)

A contributor wants to understand the overall architecture before diving into code. They need a mental model of how the framework, implementations, sieve pipeline, and MCP tools fit together.

**Why this priority**: Without architectural understanding, contributors make changes that violate separation rules or misuse the plugin protocol, creating review burden.

**Independent Test**: Can be tested by asking a new contributor to explain the system flow after reading the guide and comparing it to the actual architecture.

**Acceptance Scenarios**:

1. **Given** a developer reads the architecture overview, **When** they are asked to explain how a control is checked end-to-end, **Then** they can describe the flow from TOML definition through sieve orchestration to result output.
2. **Given** a developer reads the separation rules section, **When** they attempt to add an import from an implementation into the framework, **Then** they understand why this is forbidden and how to use the plugin protocol instead.

---

### Edge Cases

- What happens when a developer follows the guide on Windows vs macOS vs Linux?
- How does the guide handle contributors who only want to work on documentation, not code?
- What if a developer has an older version of a required tool?
- How does the guide address contributors who want to work on tests only?
- What if the developer doesn't have access to a GitHub account for fork-based workflow testing?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The guide MUST include a prerequisites section listing all required tools, minimum versions, and installation instructions.
- **FR-002**: The guide MUST provide step-by-step environment setup instructions that work from a fresh clone to running tests in under 15 minutes.
- **FR-003**: The guide MUST explain the project's package structure and the separation rules between framework and implementation packages.
- **FR-004**: The guide MUST include a framework development section covering the sieve pipeline, built-in handlers, plugin protocol, and how to add or modify framework features. The architecture section MUST include Mermaid diagrams showing the package structure, sieve pipeline flow, and plugin discovery mechanism.
- **FR-005**: The guide MUST include an implementation development section covering TOML control definitions, pass types, CEL expressions, handler registration, and entry point configuration.
- **FR-006**: The guide MUST document the pre-commit validation workflow (linting, testing, spec sync, doc generation).
- **FR-007**: The guide MUST include a troubleshooting section covering at least 5 common setup and development issues with solutions.
- **FR-008**: The guide MUST provide a complete copy-paste tutorial for adding a new control to the existing OpenSSF Baseline implementation, showing every file change, command to run, and expected output step-by-step.
- **FR-009**: The guide MUST provide a complete copy-paste tutorial for creating a minimal new compliance implementation from scratch, showing every file, command, and expected output step-by-step.
- **FR-010**: The guide MUST include a CEL expression reference covering syntax rules, available context variables, custom functions, and common pitfalls.
- **FR-011**: The guide MUST document the project's testing strategy, including how to run framework tests vs implementation tests and how to add new tests.
- **FR-012**: The guide MUST be structured so that framework developers and implementation developers can navigate directly to their relevant sections without reading the entire guide.
- **FR-013**: The guide MUST use a hub-and-spoke structure: a short GETTING_STARTED.md hub document that links to focused sub-guides (e.g., framework development, implementation development, troubleshooting) in the docs/ directory.
- **FR-014**: Contributor-facing content currently in README.md, CONTRIBUTING.md, and IMPLEMENTATION_GUIDE.md MUST be moved into the appropriate new sub-guides, with the originals trimmed and updated to link to the new location.

### Key Entities

- **Getting Started Guide**: The primary document (or set of linked documents) that serves as the contributor onboarding hub.
- **Framework**: The core darnit package containing the plugin system, sieve pipeline, configuration, and MCP tools.
- **Implementation**: A compliance framework plugin (like darnit-baseline) that defines controls and remediation in TOML.
- **Control**: A compliance check defined in TOML with metadata, passes, and optional remediation steps.
- **Sieve Pipeline**: The 4-phase verification pipeline (file_must_exist, exec/pattern, llm_eval, manual).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new contributor with no prior project knowledge can set up their development environment and run all tests successfully within 15 minutes by following the guide.
- **SC-002**: A new contributor can add a new control to the existing implementation and verify it works within 30 minutes by following the guide.
- **SC-003**: A new contributor can create a minimal new compliance implementation plugin and have it discovered by the framework within 45 minutes by following the guide.
- **SC-004**: 90% of common setup issues are resolvable by consulting the troubleshooting section without asking a maintainer.
- **SC-005**: The guide reduces onboarding-related questions in issues and discussions by 50% within 3 months of publication.
- **SC-006**: The guide covers both framework and implementation development paths with clear navigation so contributors can find their relevant section within 1 minute.

## Clarifications

### Session 2026-03-10

- Q: Should the guide be a single monolithic document, a hub-and-spoke set of linked documents, or integrated into existing docs? → A: Hub-and-spoke (a short GETTING_STARTED.md hub that links to focused sub-guides in docs/)
- Q: Should existing docs (README, CONTRIBUTING, IMPLEMENTATION_GUIDE) be kept unchanged, consolidated into the new guides, or left to coexist with overlap? → A: Consolidate — move contributor-facing content from existing docs into new sub-guides, trim originals to avoid stale duplication
- Q: How deep should the worked examples (FR-008, FR-009) be — conceptual walkthroughs, complete copy-paste tutorials, or both? → A: Complete copy-paste tutorials — every file, command, and expected output shown step-by-step
- Q: Should the architecture section include visual diagrams? → A: Yes, Mermaid diagrams (GitHub-native, text-based, version-controlled)

## Assumptions

- Contributors have basic familiarity with version control and command-line tools.
- The primary development environment is macOS or Linux; Windows support via WSL is acceptable but not the primary target.
- Contributors have access to a GitHub account for fork-based workflow and API testing.
- The guide will be written in Markdown and live in the repository's docs/ directory.
- Existing documentation (README, CONTRIBUTING, IMPLEMENTATION_GUIDE) will be trimmed of contributor-facing content that moves into the new sub-guides, with links replacing the removed sections. Originals retain their primary-audience focus (users for README, high-level contribution policy for CONTRIBUTING).
- The guide targets the current project toolchain for dependency management, linting, and testing.

## Dependencies

- Existing documentation in the repository's root and docs/ directory will serve as source material.
- The guide depends on the current project architecture being stable (no major restructuring planned).
