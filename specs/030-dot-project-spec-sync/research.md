# Phase 0 Research: `.project/` reader reconciliation

## Upstream drift, resolved

**Tracked upstream commit** (matches `.github/dot-project-spec-hash.txt` `d8ca8361...`):
`979abb1e07fa` (2026-03-05, "support cla-only projects, of which there are few")

**Current upstream commit** (matches SHA-256 fetched from `raw.githubusercontent.com/cncf/automation/main/utilities/dot-project/types.go`):
`641b80619cd5` (2026-06-29, "feat: support multiple project_lead and package_managers values")

**Commits between**:
- `061997e527a9` (2026-06-19, "feat: structured slack_channels list; remove cncf_slack_channel")
- `641b80619cd5` (2026-06-29, "feat: support multiple project_lead and package_managers values")

Two upstream changes. Diff evaluated in `/tmp/cncf-diff/{tracked,current}.go` and summarized below.

## Decision 1: Field-level classification of the drift

| Upstream change | YAML key | Old shape | New shape | Darnit consumes today? | Classification |
|-----------------|----------|-----------|-----------|------------------------|----------------|
| `Project.PackageManagers` value type | `package_managers[k]` | scalar string | scalar OR list (`StringOrSlice`) | Yes (reader, merger, mapper, tests) | RESHAPE |
| `Project.ProjectLead` field (renamed to `ProjectLeads`, reshaped) | `project_lead` | scalar string | scalar OR list (`StringOrSlice`) | Yes (reader, merger, mapper, tests) | RESHAPE (YAML key unchanged; Go field name changed but not observable from YAML) |
| `Project.CNCFSlackChannel` (removed) + new `Project.SlackChannels` | `cncf_slack_channel` (removed); `slack_channels` (added, list of objects) | scalar string | absent (removed); new key is a list of objects with `workspace`/`link`/`name`/`primary` | Yes for old `cncf_slack_channel`; no for new `slack_channels` | REMOVED + NEW-IGNORED |
| Helper type `StringOrSlice` | N/A | N/A | new Go type + YAML-shape helper | N/A | HELPER (implementation detail, not a field) |

**Decision**: One RESHAPE handling path covers `package_managers` values and `project_lead`; one REMOVED-with-deprecation-alias path covers `cncf_slack_channel`; one NEW-IGNORED path covers `slack_channels`.

**Rationale**: Per Q1 (parse-only scope), the reader does not expose newly-added upstream shapes to consumers. `project_lead` and `package_managers` retain their existing scalar-shape attributes on `ProjectConfig`; when a `.project/project.yaml` supplies the list form, the reader accepts the list and collapses to the first element for the existing consumers. `slack_channels` is silently accepted (ignored) at parse time.

**Alternatives considered**:
- *Expose `project_leads` as a new list attribute alongside `project_lead`*: rejected. Violates Q1's parse-only scope. Whoever wants darnit controls to see multiple leads opens a follow-up feature.
- *Break `project_lead` into a list-only attribute (breaking change)*: rejected. Violates FR-003 (public field name and semantics must be preserved).
- *Ignore the shape change and let `dict[str, str]` blow up on the first list-form `package_managers`*: rejected. Fails FR-001 (parse must succeed on the current upstream shape).

## Decision 2: `cncf_slack_channel` rename handling

The old upstream field `CNCFSlackChannel` with YAML key `cncf_slack_channel` is *removed* from the upstream Go struct and *replaced* by `SlackChannels` with YAML key `slack_channels`. This qualifies as a rename+reshape for FR-010's purpose.

**Decision**: The reader continues to accept the old `cncf_slack_channel` YAML key AND populates the existing `config.cncf_slack_channel: str` attribute from it. Encountering the old key triggers `warnings.warn(msg, DeprecationWarning)` where `msg` names both keys and the release in which the alias will be removed. The new `slack_channels` YAML key is silently accepted (parse-only per Q1) and NOT projected onto `config.cncf_slack_channel`.

**Rationale**: Real repositories today have `cncf_slack_channel` in their `.project/project.yaml`; darnit consumers (mapper at `dot_project_mapper.py:110` and merger at `dot_project_merger.py:44`) depend on that value being present. FR-010 gives us one release of grace to warn and then remove. `slack_channels` is a materially different shape (list of structured objects vs. a single string); collapsing it into `cncf_slack_channel` would silently drop information and is exactly the kind of "silently changed semantics" FR-003 prohibits.

**Alternatives considered**:
- *Populate `cncf_slack_channel` from `slack_channels[0].name` as a bridge*: rejected. Silently converts a structured object into a scalar string, dropping `workspace`, `link`, `primary`. Consumers reading the CEL context map `project.cncf_slack_channel` would see a value that doesn't correspond to what the repo owner declared.
- *Remove `cncf_slack_channel` attribute immediately*: rejected. Breaks existing consumers with no grace window (Q2 requires exactly one release).

## Decision 3: `DOT_PROJECT_SPEC_VERSION` bump target

Current value: `"1.1.0"` (declared in `dot_project.py:39`).

**Decision**: Bump to `"1.2.0"`.

**Rationale**: Semver-like scheme where MINOR indicates additive-with-optional-deprecation upstream change. The reconciliation:
- Adds acceptance of list-shape `project_lead` and `package_managers` values (additive, backward-compatible with scalar).
- Adds deprecation warning on `cncf_slack_channel` (additive; existing readers still work).
- Silently accepts new upstream fields (additive; no consumer-visible change).

Nothing about this is a breaking change for existing consumers, so a MAJOR bump is inappropriate. A PATCH bump would suggest no change worth a maintainer's attention, contradicting Q3's rule ("bump on every drift the reconciliation processes"). MINOR fits.

**Alternatives considered**:
- *Mirror upstream's `schema_version` field value*: rejected. Upstream's `Project.SchemaVersion` is a per-file *declaration* by the .project.yaml author about which schema they target, not a version of the schema itself. The upstream repo publishes no separate version identifier for `types.go`.
- *Use the upstream commit SHA as the version*: rejected. Opaque to maintainers; the tracked-hash file already carries the SHA. `DOT_PROJECT_SPEC_VERSION` should be maintainer-legible; the SHA belongs in commit messages and a maintenance note.
- *Bump to `1.1.1` (PATCH)*: rejected per Q3.

## Decision 4: Deprecation-warning delivery channel

**Decision**: `warnings.warn(message, DeprecationWarning, stacklevel=2)`.

**Rationale**: Deprecation warnings are the Python-native mechanism for signaling "this input still works but will stop working in a future release." Consumers can filter them (`warnings.filterwarnings`), escalate them (`-W error::DeprecationWarning`), or capture them in tests (`pytest.warns(DeprecationWarning)`) uniformly. `logger.warning(...)` mixes deprecation signal with runtime operational logging and does not participate in Python's `-W` filter machinery. Structured events (a new logging shape) would be over-engineered for a one-line signal that already has a standard-library home.

`stacklevel=2` places the warning at the caller of the reader method rather than inside `dot_project.py` itself, matching the convention Python libraries use to help downstream consumers see which of their own lines triggered the deprecated code path.

**Alternatives considered**:
- *`logger.warning(...)`*: rejected. Non-filterable through standard Python conventions; noisy at INFO log levels; mixes deprecation state with operational state.
- *A darnit-specific structured event*: rejected. No consumer of `dot_project.py` currently reads structured events, so a new event stream needs its own consumer — out of scope.

## Decision 5: Mechanical verification of SC-002 (no downstream behavior flips)

**Decision**: A golden-file fixture test.

Add `tests/darnit/context/fixtures/full_field_coverage.yaml`: a single `.project/project.yaml` populated with representative values for every field darnit reads today (per the cross-walk against `dot_project.py`, `dot_project_merger.py`, `dot_project_mapper.py`). Add a test that:
1. Loads the fixture through `DotProjectReader.load(...)`.
2. Feeds the resulting `ProjectConfig` through `dot_project_mapper.get_context(...)` to produce the flat CEL context.
3. Asserts the flat context matches a golden dict inlined in the test source.

The golden dict is authored once, from the pre-reconciliation output, and MUST match byte-for-byte after the reconciliation lands.

**Rationale**: A golden-file test gives SC-002 mechanical teeth without inventing new comparison machinery. Because the flat CEL context is the shape every control consumes, testing at that boundary covers every downstream reader with a single fixture. A snapshot mismatch is a maintainer signal that the reconciliation silently changed a consumer-visible value.

**Alternatives considered**:
- *Semantic per-field assertions* (assert one field at a time): rejected. Verbose and easy to miss a field.
- *Control-invocation regression* (run representative controls before/after): rejected. Higher blast radius, slower test, and a control's status can flip for reasons unrelated to `.project/`.
- *Property-based generation of fixtures*: rejected. Over-engineered for a maintenance reconciliation.

## Deferred (out of scope for this feature)

- Any future feature that wants `project_leads: list[str]` exposed to controls.
- Any future feature that wants `slack_channels: list[SlackChannel]` exposed to controls.
- The nightly cron / notification proposal from spec §Assumptions (out-of-band process; separate feature).
