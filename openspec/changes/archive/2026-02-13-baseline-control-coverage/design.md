## Context

The OpenSSF Baseline implementation (`openssf-baseline.toml`) defines 62 controls across 8 domains. The current breakdown:

- **Automated remediation**: 14 controls (22%) — 13 `file_create`, 1 `api_call`
- **Manual-only remediation**: 34 controls (55%) — `handler = "manual"` with step-by-step instructions
- **No remediation at all**: 14 controls (23%)

The framework already supports `api_call`, `file_create`, `exec`, `pattern`, and context-driven remediation declaratively in TOML. This change fills in the gaps by applying those existing capabilities to more controls — no framework (`packages/darnit/`) changes needed.

All changes are scoped to `packages/darnit-baseline/openssf-baseline.toml` and new integration tests.

## Goals / Non-Goals

**Goals:**
- Convert manual-only remediations to automated where feasible using `api_call`, `file_create`, or `exec`
- Add `file_create` remediations for missing documentation/policy controls (DO, LE, VM domains)
- Add `api_call` remediations for GitHub repository settings (AC, VM domains)
- Add `file_create` remediations for CI workflow templates (QA, BR domains)
- Add new context definitions to support workflow generation preferences
- Add automated checks (exec, pattern) where controls are currently manual-only but could be verified programmatically
- Target: raise automated remediation from 22% to 60%+

**Non-Goals:**
- Modifying the darnit framework code (`packages/darnit/`)
- Adding new handler types or new built-in pass types
- Complex multi-step remediations requiring chained handler execution
- Controls that are inherently process-oriented (e.g., "contributors must be vetted") — these stay manual
- Achieving 100% automation — some controls genuinely require human judgment

## Decisions

### 1. GitHub API remediations use `api_call` handler with `gh` CLI

**Decision**: Use the `api_call` handler with `method`, `endpoint`, and `payload_template` fields, matching the existing OSPS-AC-03.01 pattern.

**Rationale**: The `api_call` handler already works and the `gh` CLI handles authentication. The alternative — `exec` with raw `gh api` commands — would require duplicating payload handling and lose the structured dry-run support.

**Controls affected**: OSPS-AC-01.01 (MFA), OSPS-AC-02.01 (forking), OSPS-AC-03.02 (branch deletion protection), OSPS-QA-01.01 (repo visibility), OSPS-QA-03.01 (status checks), OSPS-QA-07.01 (PR approval), OSPS-VM-03.01 (vulnerability reporting), OSPS-VM-04.01 (security advisories).

### 2. CI workflow templates are GitHub Actions YAML created via `file_create`

**Decision**: Create GitHub Actions workflow YAML files in `.github/workflows/` using `file_create` with new templates. Each workflow template targets a specific concern (CI testing, SBOM, SAST, SCA, release signing).

**Rationale**: GitHub Actions is by far the most common CI for OSS projects in the OpenSSF ecosystem. The templates should be minimal but functional — users can customize after creation. The `ci_provider` context key already exists; we add a guard so workflows are only created when `ci_provider == "github"`.

**Alternative considered**: Language-specific templates (Go CI, Python CI, etc.). Rejected for v1 — too many permutations. Start with generic templates that work across languages.

**New templates**: `ci_test_workflow`, `sbom_workflow`, `sast_workflow`, `sca_workflow`, `release_signing_workflow`.

### 3. Policy/documentation templates use `file_create` with variable substitution

**Decision**: Add templates for SUPPORT.md, dependency management policy, end-of-support policy, and VEX policy. Templates use `$VARIABLE` substitution (e.g., `$PROJECT_NAME`, `$OWNER`, `$REPO`).

**Rationale**: Most documentation controls fail simply because the file doesn't exist. A reasonable template that the user can customize is better than manual steps telling them to "create a file."

**Controls affected**: OSPS-DO-03.01 (SUPPORT.md — already has check, needs remediation), OSPS-DO-04.01 (support scope), OSPS-DO-05.01 (end-of-support), OSPS-DO-06.01 (dependency management), OSPS-VM-01.01 (disclosure process), OSPS-VM-04.02 (VEX policy), OSPS-VM-05.01 (SCA policy), OSPS-VM-06.01 (SAST policy).

### 4. New context keys scoped to tooling preferences

**Decision**: Add 3 new context definitions:
- `sbom_tool`: enum (`syft`, `cyclonedx`, `trivy`, `other`) — which SBOM tool to use in generated workflows
- `sast_tool`: enum (`codeql`, `semgrep`, `sonarqube`, `other`) — which SAST tool to use
- `preferred_license`: string — project's license identifier for template variable substitution

**Rationale**: Without these, generated CI workflows would hardcode a specific tool. Asking the user's preference produces more useful output. Kept to 3 keys to avoid context fatigue.

**Alternative considered**: Auto-detecting tool preference from existing config files. Deferred — adds complexity for marginal benefit in v1.

### 5. Automated checks added only where deterministic

**Decision**: Add `exec` or `pattern` passes only for controls where the check is unambiguous:
- GitHub API checks (repo visibility, fork settings, vulnerability reporting enabled)
- File pattern checks (workflow permissions, CI config presence)
- License format validation (SPDX identifier in LICENSE)

**Rationale**: Automated checks that produce false positives erode trust. Only add checks where the result is binary and verifiable. Controls requiring judgment (e.g., "documentation is adequate") stay manual or get LLM passes in a future change.

### 6. Batch controls by domain for implementation

**Decision**: Implement changes domain-by-domain rather than by change type (all checks, then all remediations). Order: AC → VM → QA → BR → DO → LE → GV → SA.

**Rationale**: Domain batching keeps related TOML changes together, makes code review easier, and allows testing a complete domain before moving to the next. AC and VM have the highest-value API remediations. QA is the largest gap (13 controls).

## Risks / Trade-offs

**[GitHub API rate limits]** → API-based checks and remediations depend on `gh` CLI auth and rate limits. Mitigation: checks already have `timeout` fields; add sensible defaults (30s). Remediation is user-triggered so rate limits are unlikely.

**[Template staleness]** → CI workflow templates (e.g., CodeQL setup) may become outdated as tools evolve. Mitigation: templates are intentionally minimal; use `@latest` or stable version tags where possible. Templates are a starting point, not a maintained config.

**[Over-automation]** → Some "automated" remediations change repository settings that maintainers may not want. Mitigation: the remediation system already has `dry_run_supported = true` and `safe` flags. API remediations that change settings are marked `safe = false` so the MCP agent confirms before executing.

**[Context fatigue]** → Adding too many context prompts before the user can run an audit. Mitigation: limited to 3 new context keys, all optional with sensible defaults.

## Open Questions

- Should CI workflow templates include language-specific variants (Go, Python, Rust, JS)? Deferred for now — start generic.
- Should we add `exec` checks that call external tools (trivy, scorecard)? These add external dependencies. Deferred for v1 — keep checks to `gh` CLI and file system only.
