# Upstream diff summary

**Tracked upstream commit**: `979abb1e07fa` (2026-03-05, "support cla-only projects, of which there are few").
**Current upstream commit**: `641b80619cd5` (2026-06-29, "feat: support multiple project_lead and package_managers values").

SHA-256 of `types.go`:

- Tracked: `d8ca8361c0aff434e9d7288851717f88f149785419ca062a520cdd506ae6b27e` (matches `.github/dot-project-spec-hash.txt` pre-reconciliation).
- Current: `860df23ecfd970b3d603098b6597a787e7ee6954b8592cdd17e431198eff70b4` (target after `--update-hash`).

Raw blobs are snapshotted at `/tmp/cncf-diff/tracked.go` and `/tmp/cncf-diff/current.go` for the duration of this reconciliation.

## Field-level classification

| Upstream change | YAML key(s) affected | Old shape | New shape | Darnit consumes today? | Classification | Reader task(s) |
|-----------------|----------------------|-----------|-----------|------------------------|----------------|----------------|
| `Project.PackageManagers` value type | `package_managers[*]` | scalar string | scalar OR list (`StringOrSlice`) | Yes (reader, merger, mapper, tests) | RESHAPE | T005 |
| `Project.ProjectLead` field (renamed to `ProjectLeads`, reshaped in Go; YAML key unchanged) | `project_lead` | scalar string | scalar OR list (`StringOrSlice`) | Yes (reader, merger, mapper, tests) | RESHAPE | T004 |
| `Project.CNCFSlackChannel` removed | `cncf_slack_channel` | scalar string | (removed) | Yes | RENAMED (alias-with-warning) | T006 |
| New `Project.SlackChannels` | `slack_channels` | (absent) | list of objects `{workspace, link, name, primary}` | No (new field, not consumed) | NEW-IGNORED (lands in `_extra`) | T007 |
| `StringOrSlice` helper type | N/A | N/A | new Go helper | N/A | HELPER-ONLY (implementation detail) | T003 (Python coercer) |

Matches [data-model.md](./data-model.md) Decision 1 verbatim.

## Reader work summary

- One new private helper: `_coerce_scalar_or_list` (T003).
- Two RESHAPE routings: `project_lead` (T004), `package_managers[*]` (T005).
- One RENAMED-with-alias path: `cncf_slack_channel` triggers `DeprecationWarning` (T006).
- One NEW-IGNORED path: `slack_channels` lands in `_extra` (T007).
- Version bump: `DOT_PROJECT_SPEC_VERSION` `"1.1.0"` -> `"1.2.0"` (T008).
- Reconciliation-history docstring note (T009).
- Tracked-hash refresh (T010).

## Consumer surface touched

Cross-walk against downstream consumers to confirm no consumer sees a new attribute type or missing attribute (spec FR-003, plan Structure Decision):

- `packages/darnit/src/darnit/context/dot_project_merger.py` reads `project_lead`, `cncf_slack_channel`, `package_managers` -- all three attributes remain `str` / `str` / `dict[str, str]` on `ProjectConfig`. No signature change.
- `packages/darnit/src/darnit/context/dot_project_mapper.py` produces `project.project_lead`, `project.cncf_slack_channel`, `project.package_managers` keys in the CEL context -- all three still emit with pre-reconciliation types and semantics.
- `packages/darnit/src/darnit/config/schema.py` (Pydantic mirror) declares matching field types; no change required.
