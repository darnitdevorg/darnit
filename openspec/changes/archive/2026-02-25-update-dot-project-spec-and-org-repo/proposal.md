# Proposal: update-dot-project-spec-and-org-repo

> **Note**: This content will be written to `openspec/changes/update-dot-project-spec-and-org-repo/proposal.md` once plan mode exits.

## Why

The darnit framework's `.project/` reader targets CNCF spec v1.1.0 but has structural gaps against the actual `cncf/automation` types.go — notably `security.contact` is now a struct (not a string) and `maintainers.yaml` uses a teams-based structure. Additionally, CNCF projects maintain a dedicated `.project` repository at the org level (e.g., `project-copacetic/.project`) containing shared metadata across all repos in the org. Darnit has no support for fetching or merging this org-level config, which means audits of CNCF project repos miss rich metadata that's already published.

## What Changes

- **Update `security.contact` parsing**: Support the CNCF struct format (`email` + `advisory_url`) alongside the legacy plain-string format for backward compatibility
- **Update `maintainers.yaml` parsing**: Support the CNCF teams-based format (`project_id`, `org`, `teams[].name`, `teams[].members`) alongside existing flat-list and dict-with-handle formats
- **Add org-level `.project` repo resolver**: Discover and fetch `project.yaml` and `maintainers.yaml` from `{owner}/.project` GitHub repos via `gh` CLI
- **Add config merge logic**: Merge org-level `.project` repo defaults with local `.project/` directory config (local overrides org at the section level)
- **Update context mapper**: Emit new context variables for advisory URL, maintainer org, and maintainer teams
- **Wire into audit pipeline**: Pass owner/repo to the mapper so org-level resolution happens automatically during audits

## Capabilities

### New Capabilities
- `org-project-resolution`: Discovering, fetching, caching, and merging org-level `.project` repository metadata with local repo config during audits

### Modified Capabilities
- `dot-project-integration`: Updating the `.project/` reader to handle CNCF spec structural changes (`security.contact` struct, teams-based `maintainers.yaml`) and adding new context variable mappings

## Impact

- **Framework package** (`packages/darnit/`):
  - `context/dot_project.py` — new dataclasses (`SecurityContact`, `MaintainerTeam`, `MaintainerEntry`), updated parsing
  - `context/dot_project_mapper.py` — new context variables, `owner` parameter, org merge integration
  - `context/dot_project_org.py` — new module for org `.project` repo resolution
  - `context/dot_project_merger.py` — new module for config merge logic
  - `context/inject.py` — pass owner to mapper
  - `config/schema.py` — `SecurityContactModel` Pydantic model, updated `SecurityConfig.contact` type
- **Tests**: New test files for org resolver and merger; updated tests for struct contact and teams maintainers
- **No breaking changes to MCP tools or TOML controls** — all changes are backward compatible at the context variable level
- **External dependency**: `gh` CLI for org repo fetching (graceful degradation if unavailable)
