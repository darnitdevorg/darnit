# Architecture Documentation

Reference documentation describing how darnit's framework, sieve pipeline, plugin system, and remediation engine are organized.

These are static reference docs, not in-flight feature specs (those live under `specs/`). Each document was originally maintained as `openspec/specs/<topic>/spec.md`; the content moved here in feature [016-openspec-migration](../../specs/016-openspec-migration/spec.md).

## Framework foundations

- [Framework design](./framework-design.md) -- authoritative framework specification
- [Plugin registry](./plugin-registry.md) -- how plugins register controls, handlers, and tools
- [Handler pipeline](./handler-pipeline.md) -- four-phase sieve handler dispatch
- [Sieve handler authoring](./sieve-handler-authoring.md) -- contract for writing new sieve handlers
- [Shared handlers](./shared-handlers.md) -- built-in handlers usable across implementations
- [Implementation-provided tools](./implementation-provided-tools.md) -- MCP tool exposure model
- [Example plugin](./example-plugin.md) -- canonical worked example

## Audit lifecycle

- [Audit pipeline](./audit-pipeline.md) -- end-to-end audit execution model
- [Audit context collection](./audit-context-collection.md) -- evidence and metadata gathering
- [Context collection](./context-collection.md) -- shared context-collection plumbing
- [Context documentation](./context-documentation.md) -- documenting required project context
- [Repo identity resolution](./repo-identity-resolution.md) -- canonical owner/repo detection
- [Org-project resolution](./org-project-resolution.md) -- mapping multi-project orgs

## Controls and expressions

- [Conditional controls](./conditional-controls.md) -- `when =` clause semantics
- [Control dependencies](./control-dependencies.md) -- inter-control ordering and reuse
- [CEL expressions](./cel-expressions.md) -- universal CEL post-handler evaluation
- [Dot-project integration](./dot-project-integration.md) -- `.project/project.yaml` integration

## Reporting and remediation

- [Framework-agnostic reporting](./framework-agnostic-reporting.md) -- output formatters (Markdown, SARIF, JSON)
- [Remediation manual guidance](./remediation-manual-guidance.md) -- manual-step authoring conventions
- [Remediation audit filtering](./remediation-audit-filtering.md) -- audit -> remediation control filtering
- [GitHub API remediation](./github-api-remediation.md) -- remediation patterns for GitHub-hosted projects

## Templates

- [CI workflow templates](./ci-workflow-templates.md) -- shipped GitHub Actions templates
- [Declarative file templates](./declarative-file-templates.md) -- template specification language
- [External templates](./external-templates.md) -- referencing templates outside the framework
- [Policy doc templates](./policy-doc-templates.md) -- security and governance doc templates
