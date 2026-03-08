# Design: update-dot-project-spec-and-org-repo

## Context

The darnit framework reads `.project/project.yaml` and `.project/maintainers.yaml` following the CNCF `.project/` specification (v1.1.0). The current implementation treats `security.contact` as a plain string and `maintainers.yaml` as a flat list of handles. The upstream spec has evolved: `security.contact` is now a struct (`email` + `advisory_url`) and `maintainers.yaml` supports a teams-based structure with `project_id`, `org`, and nested `teams[].members`.

Additionally, CNCF projects often maintain a shared `.project` repository at the org level (e.g., `my-org/.project`) containing default metadata for all repos in the org. The framework has no mechanism to discover or merge this org-level config, causing audits to miss metadata that projects have already published.

The existing parsing architecture uses dataclasses for the reader layer and Pydantic models for the config schema layer — these are separate but parallel type hierarchies.

## Goals / Non-Goals

**Goals:**
- Support CNCF struct format for `security.contact` while preserving backward compatibility with plain strings
- Support CNCF teams-based `maintainers.yaml` while preserving backward compatibility with flat lists and dict-with-handle formats
- Discover and fetch org-level `.project` repo metadata via `gh` CLI
- Merge org-level defaults with local `.project/` config using section-level precedence (local wins)
- Emit new context variables (`project.security.advisory_url`, `project.maintainer_org`, `project.maintainer_teams`, etc.)
- Gracefully degrade when `gh` CLI is unavailable

**Non-Goals:**
- Supporting non-GitHub hosting platforms for org resolution (GitLab, Bitbucket)
- Deep-merging within sections (field-level merge within security, governance, etc.)
- Automatically writing org-level metadata back to the org `.project` repo
- Caching org data across sessions (disk-based persistence)
- Adding new MCP tools for org `.project` management

## Decisions

### Decision 1: Union types for backward-compatible contact parsing

`SecurityConfig.contact` becomes `SecurityContact | str | None` in the dataclass layer, and `SecurityContactModel | EmailStr | str | None` in the Pydantic layer. The reader dispatches on the YAML value type: dict → `SecurityContact`, string → preserved as-is.

**Alternatives considered:**
- *Always normalize to struct*: Would break existing string comparisons in checks and lose the original format
- *Separate fields (`contact_email`, `contact_struct`)*: Adds API surface without benefit; union type is idiomatic Python

### Decision 2: Flat handles + structured entries as parallel fields

The `ProjectConfig` dataclass carries both `maintainers: list[str]` (flat handles, backward compat) and `maintainer_entries: list[MaintainerEntry]` + `maintainer_teams: list[MaintainerTeam]` (structured data). The flat list is always populated regardless of input format.

**Alternatives considered:**
- *Replace `maintainers` with structured-only*: Breaks all existing consumers that expect `list[str]`
- *Single `maintainers` field with overloaded type*: Type confusion; consumers wouldn't know if they're getting strings or objects

### Decision 3: `gh` CLI for org repo access (not GitHub API directly)

Org resolution uses `gh api` subcommands rather than raw HTTP to GitHub's REST API. This avoids managing authentication tokens, leverages the user's existing `gh auth` session, and follows the pattern already used by exec-based sieve passes.

**Alternatives considered:**
- *Direct `requests`/`httpx` calls*: Requires managing PATs or GITHUB_TOKEN, adds a dependency, duplicates auth logic
- *`git clone --depth 1`*: Slower, creates disk artifacts, harder to fetch individual files
- *GraphQL via `gh api graphql`*: Over-engineered for fetching 2 files

### Decision 4: Section-level merge (not field-level)

When local config has a section (e.g., `security`), the entire local section replaces the org section. No field-level merging within sections.

**Rationale:** Field-level merge creates ambiguity about intent. If a local repo defines `security.policy` but not `security.contact`, it's unclear whether the omission is intentional (no contact) or an oversight (should inherit org contact). Section-level merge is predictable: define the section locally → you own it entirely.

**Alternatives considered:**
- *Field-level deep merge*: Requires tracking which fields were explicitly set vs. defaulted; leads to surprising inheritance behavior
- *No merge (local-only or org-only)*: Loses the value of shared org metadata entirely

### Decision 5: Module-level cache for org resolution

Org resolution results are cached in a module-level dict (`_org_cache: dict[str, ProjectConfig | None]`). The cache lives for the process lifetime with an explicit `clear_cache()` function.

**Alternatives considered:**
- *Instance-level cache on `OrgProjectResolver`*: Doesn't help when multiple mapper instances audit repos from the same org
- *Disk cache / SQLite*: Over-engineered; org data is small and sessions are short
- *LRU cache decorator*: Less control over cache clearing and debugging

### Decision 6: New modules rather than expanding existing files

Org resolution (`dot_project_org.py`) and merge logic (`dot_project_merger.py`) are separate modules rather than additions to `dot_project.py` or `dot_project_mapper.py`.

**Rationale:** Keeps each module focused on a single responsibility. The reader reads local files, the org resolver fetches remote files, the merger combines configs, and the mapper flattens to context variables.

## Risks / Trade-offs

**[`gh` CLI dependency]** → Org resolution silently skips when `gh` is unavailable. Users without `gh` installed see no error but miss org metadata. Mitigation: debug-level logging explains why org resolution was skipped.

**[GitHub API rate limits]** → Each org resolution makes 2-3 API calls (repo check + file fetches). For orgs with many repos audited in sequence, this could hit rate limits. Mitigation: per-owner caching ensures at most 3 calls per unique org per session.

**[Section-level merge loses org field defaults]** → If local defines a sparse `security` section, org's other security fields are lost. Mitigation: this is documented, predictable behavior. Projects that want org defaults for a section should not override that section locally.

**[Base64 decoding of file content]** → GitHub's contents API returns base64-encoded files. If the API response format changes or the file is too large (>1MB), decoding could fail. Mitigation: wrapped in try/except with graceful fallback.

**[Two parallel type hierarchies]** → The dataclass layer (`dot_project.py`) and Pydantic layer (`config/schema.py`) both define security contact types. They serve different purposes (tolerant parsing vs. strict validation) but must stay in sync. Mitigation: tests cover both layers; the dataclass layer is the source of truth for the reader.

## Open Questions

- Should org resolution support fetching from a configurable branch (not just default branch)?
- Should we add a CLI flag or config option to disable org resolution for air-gapped environments?
- Should the Pydantic `SecurityContactModel.advisory_url` use strict `HttpUrl` validation or accept any string?
