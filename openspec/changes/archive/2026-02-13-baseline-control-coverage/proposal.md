## Why

The OpenSSF Baseline implementation has 62 controls, but only 22% have automated remediation (all but one using `file_create`). 77% of controls either have no remediation or manual-only remediation, meaning the MCP agent must guide users through steps rather than fixing issues directly. The QA domain is the biggest gap — all 13 controls are manual-only. Several controls that could use GitHub API calls (`api_call`), workflow file creation, or `exec` commands currently fall back to manual guidance. Additionally, many checks are manual-only when automated detection is possible (e.g., checking for CI workflows, license formats, dependency manifests).

## What Changes

- **Add automated checks** for controls currently relying on manual-only verification — file existence checks, pattern matching in config files, and GitHub API queries
- **Add automated remediations** using `api_call` (GitHub API), `file_create` (templates for workflows, policies), and `exec` (CLI commands) for controls currently stuck at manual remediation
- **Expand context gathering** — add new context definitions where user input improves remediation quality (e.g., preferred CI workflows, SBOM tooling preferences)
- **Improve existing checks** — convert vague pattern passes to more precise detection, add `use_locator` where file paths are duplicated

## Capabilities

### New Capabilities
- `github-api-remediation`: Automated GitHub API remediation actions for repository settings — branch protection rules, vulnerability reporting, discussions, fork settings, and repository visibility. Covers AC and VM domain controls.
- `ci-workflow-templates`: CI/CD workflow file templates for automated testing, SBOM generation, SAST scanning, SCA checks, and release signing. Covers QA and BR domain controls.
- `policy-doc-templates`: Policy and documentation templates for security policies, support scope, dependency management, and end-of-support documentation. Covers DO, LE, and VM domain controls.

### Modified Capabilities
- `context-collection`: Add new context keys for CI workflow preferences, SBOM tooling, and SAST tooling to support automated workflow generation.

## Impact

- **TOML config**: `packages/darnit-baseline/openssf-baseline.toml` — major changes adding/updating pass definitions and remediation blocks across ~40 controls
- **Templates**: New templates section in TOML for CI workflow files, policy documents, and API payloads
- **Context system**: New context definitions in TOML `[context.*]` section
- **No framework changes**: All improvements use existing TOML-declarative capabilities (file_create, api_call, pattern passes, context system). No changes to `packages/darnit/`.
- **Test coverage**: New integration tests validating remediation actions produce expected outputs
