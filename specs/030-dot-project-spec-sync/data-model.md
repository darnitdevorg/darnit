# Phase 1 Data Model: `.project/` reader reconciliation

## Purpose

This document captures the reconciled dataclass surface of `packages/darnit/src/darnit/context/dot_project.py` after the current feature lands. Every dataclass field is annotated with its reconciliation classification so that a future maintainer can diff this table against the next reconciliation's data-model and see exactly what a downstream consumer might notice.

## Classification vocabulary

- `KEPT` — Field is unchanged: same name, same type, same semantics as pre-reconciliation.
- `KEPT-WITH-RESHAPE` — Same name and type on `ProjectConfig`, but the YAML input value is now accepted in an additional shape (scalar or list). Backward-compatible: existing YAML files that use the old shape parse identically.
- `KEPT-WITH-ALIAS` — Field name and type unchanged on `ProjectConfig`. The corresponding upstream YAML key was renamed (or removed and replaced); the reader continues to accept the old YAML key AND emits a `DeprecationWarning` naming the release in which the alias will be removed.
- `NEW-IGNORED` — Upstream added this field; the reader parses `.project/project.yaml` files that contain it without raising, but the field is not projected onto any `ProjectConfig` attribute. Future feature can promote it to a real attribute.
- `RESHAPED-INTERNAL` — Field is `KEPT-WITH-RESHAPE` on `ProjectConfig`, but a nested dataclass's shape or the `_extra` catch-all changed to accommodate. Rare.

## `ProjectConfig` (packages/darnit/src/darnit/context/dot_project.py:233)

| Field | Type | Classification | Notes |
|-------|------|----------------|-------|
| `name` | `str` | KEPT | Required-ish (validated by `is_valid()`). YAML key `name`. |
| `repositories` | `list[str]` | KEPT | Required-ish. YAML key `repositories`. |
| `description` | `str` | KEPT | YAML key `description`. |
| `schema_version` | `str` | KEPT | YAML key `schema_version`. Value is what the .project.yaml *declares* it targets; not to be confused with `DOT_PROJECT_SPEC_VERSION`. |
| `type` | `str` | KEPT | YAML key `type`. |
| `slug` | `str` | KEPT | YAML key `slug`. |
| `project_lead` | `str` | KEPT-WITH-RESHAPE | YAML key `project_lead`. Accepts scalar (backward-compat) OR list (new upstream). List form collapses to first element; consumers see the primary lead. Non-primary leads are dropped at parse time (documented in reader docstring). |
| `cncf_slack_channel` | `str` | KEPT-WITH-ALIAS | YAML key `cncf_slack_channel` (deprecated upstream). Old key emits `DeprecationWarning`. New upstream `slack_channels` is separately parsed as NEW-IGNORED (see below). |
| `website` | `str` | KEPT | YAML key `website`. |
| `artwork` | `str` | KEPT | YAML key `artwork`. |
| `adopters` | `FileReference \| None` | KEPT | YAML key `adopters`. |
| `mailing_lists` | `list[str]` | KEPT | YAML key `mailing_lists`. |
| `maturity_log` | `list[MaturityEntry]` | KEPT | YAML key `maturity_log`. |
| `audits` | `list[Audit]` | KEPT | YAML key `audits`. |
| `social` | `dict[str, str]` | KEPT | YAML key `social`. |
| `package_managers` | `dict[str, str]` | KEPT-WITH-RESHAPE | YAML key `package_managers`. Each map value accepts scalar (backward-compat) OR list (new upstream). List form collapses to first element per key; consumers see the primary identifier for that registry. |
| `security` | `SecurityConfig \| None` | KEPT | YAML key `security`. |
| `governance` | `GovernanceConfig \| None` | KEPT | YAML key `governance`. |
| `legal` | `LegalConfig \| None` | KEPT | YAML key `legal`. |
| `documentation` | `DocumentationConfig \| None` | KEPT | YAML key `documentation`. |
| `landscape` | `LandscapeConfig \| None` | KEPT | YAML key `landscape`. |
| `extensions` | `dict[str, ExtensionConfig]` | KEPT | Darnit-only extension mechanism. |
| `maintainers` | `list[str]` | KEPT | Comes from `.project/maintainers.yaml` or `.project/project.yaml`. |
| `maintainer_teams` | `list[MaintainerTeam]` | KEPT | Structured maintainers. |
| `maintainer_entries` | `list[MaintainerEntry]` | KEPT | Structured maintainers. |
| `maintainer_org` | `str` | KEPT | Structured maintainers. |
| `maintainer_project_id` | `str` | KEPT | Structured maintainers. |
| `_extra` | `dict[str, Any]` | KEPT | Forward-compat catch-all. New upstream keys land here without any code change. `slack_channels` lands here as NEW-IGNORED. |
| `_source_path` | `Path \| None` | KEPT | Internal; write-back target. |

## New-ignored upstream fields (parsed, not exposed)

Every field the current upstream declares that darnit does not currently attribute onto `ProjectConfig` MUST land in `_extra` (the existing forward-compat catch-all) rather than raise a parse error. Newly-added upstream fields for this reconciliation:

| Upstream field (YAML key) | Upstream shape | Where it lands |
|---------------------------|----------------|----------------|
| `slack_channels` | list of objects (`{workspace, link, name, primary}`) | `_extra["slack_channels"]` — raw parsed value. Not projected onto `ProjectConfig`. |

Any future upstream additions the next reconciliation processes will follow the same pattern.

## Nested dataclasses (no shape changes)

All of the following are `KEPT`, verbatim, from the pre-reconciliation state:

- `FileReference` (path only)
- `MaintainerEntry`, `MaintainerTeam`, `MaintainerLifecycle`, `IdentityType`
- `LandscapeConfig`
- `SecurityContact`, `SecurityConfig`
- `GovernanceConfig`
- `LegalConfig`
- `DocumentationConfig`
- `Audit`
- `MaturityEntry`
- `ExtensionConfig`

## Module-level constants

| Constant | Pre-reconciliation | Post-reconciliation |
|----------|--------------------|---------------------|
| `DOT_PROJECT_SPEC_VERSION` | `"1.1.0"` | `"1.2.0"` |
| `DOT_PROJECT_SPEC_URL` | (unchanged) | (unchanged) |

## Fixture census

`tests/darnit/context/fixtures/full_field_coverage.yaml` populates every `KEPT`, `KEPT-WITH-RESHAPE`, and `KEPT-WITH-ALIAS` field with a representative value. Each cell in the fixture is designed to be recognizable in the golden dict (SC-002's mechanical check) so a maintainer reading a diff can identify which field a change touched.

For fields with the new list-shape option (`project_lead`, `package_managers` values), the fixture uses the LIST form so the "list-to-first-element" collapse is exercised by every CI run.

For `cncf_slack_channel`, the fixture uses the old YAML key so the deprecation warning path is exercised by every CI run. A separate small unit test asserts `warnings.warn(DeprecationWarning)` fires with the right message text.
