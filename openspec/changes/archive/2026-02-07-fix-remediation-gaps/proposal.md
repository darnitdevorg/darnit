## Why

Running the baseline audit end-to-end against real repositories reveals a gap between what the audit flags and what the remediation system can actually fix. Of 62 OSPS controls, only 12 (19%) have any remediation path. Many of these gaps can't be fully automated (MFA enforcement, license choice), but a significant number can be addressed with straightforward file creation, templates, or clear guidance. The current system also doesn't communicate to the AI which gaps are "not yet automatable" vs "broken", leading to confusion about what remediation should accomplish.

The goal is not to automate everything at once, but to establish a clear, incremental flow that:
1. Classifies every control's remediation status explicitly
2. Adds simple file-create remediations where they're obvious wins
3. Provides informative "manual" remediation guidance where automation isn't feasible yet
4. Makes the system easy to extend over time with plugins and new automation

## What Changes

### Tier 1: Fix broken/missing remediations for easy wins

- **Add `file_create` remediations** for controls where the fix is "create a standard file with a template":
  - `OSPS-DO-01.01` (HasReadme) — generate README.md template
  - `OSPS-LE-01.01` / `OSPS-LE-03.01` (HasLicense / LicenseInRepo) — generate LICENSE file (MIT default, configurable)
  - `OSPS-SA-03.02` (ThreatModel) — generate THREAT_MODEL.md template (not a full analysis, just the starting structure)
  - `OSPS-BR-07.01` (GitignoreSecrets) — generate/augment .gitignore with secret patterns

- **Wire `generate_threat_model` MCP tool to write files**: Add optional `output_path` parameter so it can persist results to disk, not just return content to the AI.

### Tier 2: Improve existing remediations

- **`status_checks` (OSPS-QA-03.01)**: The registry references `configure_status_checks` but no implementation exists. Add a basic implementation that configures required status checks via the GitHub API, accepting check names as context.

- **`file_create` overwrite behavior**: The "File already exists" error is correct but confusing in audit output. Improve the messaging to clearly distinguish "already compliant" from "error" — if the file exists and the control checks for file existence, that's a pass, not an error.

### Tier 3: Add `manual` remediation guidance for non-automatable controls

For controls that can't be automated (yet), add explicit `remediation.manual` blocks in the TOML with:
- A clear explanation of what the user needs to do
- Links to relevant documentation
- Context keys that would enable future automation

This covers domains like:
- **AC**: MFA enforcement, workflow permissions (require org admin access)
- **BR**: Release signing, SBOM generation (require toolchain setup)
- **QA**: Automated tests, subproject security (require project-specific knowledge)
- **VM**: Private reporting, security advisories (require GitHub security features)

### Tier 4: Improve context gathering for remediations that need it

- **Maintainers discovery**: Enhance context collection to check CODEOWNERS, README maintainer sections, MAINTAINERS.md, and git log for likely maintainers — surfacing auto-detected values with confidence scores (the framework already supports this pattern).

## Capabilities

### New Capabilities

- `remediation-manual-guidance`: Specification for how manual remediation blocks work in TOML — what fields they support, how they're surfaced to the AI, and how they differ from automated remediations.

### Modified Capabilities

- `framework-design`: The remediation architecture gains a new remediation type (`manual`) and the `generate_threat_model` tool gains file-writing capability. The `file_create` executor improves its messaging for already-existing files.

## Impact

- **TOML changes** (`openssf-baseline.toml`): Add ~15-20 new remediation blocks (mix of `file_create` and `manual`)
- **Templates** (`openssf-baseline.toml`): Add 4-5 new file templates (README, LICENSE, THREAT_MODEL, .gitignore patterns)
- **Framework code** (`packages/darnit/`): Remediation executor gains `manual` type support; `file_create` improves existing-file messaging
- **Baseline code** (`packages/darnit-baseline/`): Threat model tool gains `output_path` param; `configure_status_checks` gets a basic implementation; context collection for maintainers is enhanced
- **No breaking changes**: All additions are backward-compatible
