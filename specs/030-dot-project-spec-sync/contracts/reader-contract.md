# Reader Contract: `dot_project` module

## Scope

This contract enumerates every public callable, dataclass attribute, module constant, and warning behavior of `packages/darnit/src/darnit/context/dot_project.py` after the current feature lands. It exists so that the next reconciliation can diff this file against its own contract and immediately see what a downstream consumer might notice.

The reader is a library-internal contract, not an HTTP or RPC surface; "public" means "what darnit's own code and its test suite call into." No stability guarantee is offered to third-party importers.

## Module constants

| Name | Pre-reconciliation | Post-reconciliation | Change class |
|------|--------------------|---------------------|--------------|
| `DOT_PROJECT_SPEC_VERSION` | `"1.1.0"` | `"1.2.0"` | BUMP (per Q3: 1:1 with tracked-hash file) |
| `DOT_PROJECT_SPEC_URL` | `"https://github.com/cncf/automation/tree/main/utilities/dot-project"` | (unchanged) | KEPT |

## Public callables

### `DotProjectReader.load(project_dir: Path) -> ProjectConfig | None`

Signature: **unchanged**.

Behavior deltas:
- Accepts `.project/project.yaml` files that use either scalar or list form for `project_lead` and `package_managers[*]` (previously only scalar was accepted; list would fail YAML-to-dataclass coercion). List form collapses to first element for both.
- On encountering the YAML key `cncf_slack_channel`, emits `warnings.warn(msg, DeprecationWarning, stacklevel=2)` where `msg` names both the old key (`cncf_slack_channel`), the recommended migration (`slack_channels`), and the release in which the alias will be removed. Value still populates `ProjectConfig.cncf_slack_channel`.
- On encountering the YAML key `slack_channels`, silently records the raw parsed value under `ProjectConfig._extra["slack_channels"]`. Not exposed via a `ProjectConfig` attribute.

Return type: **unchanged** (`ProjectConfig | None`).

### `DotProjectReader.parse(...)` and other public methods

Signatures: **unchanged**.

Behavior deltas: same three as `load()` above, since they all funnel through the same parsing helpers.

### `DotProjectWriter.*`

Signatures: **unchanged**. Write path is out of scope for this reconciliation; the reader-side reshape is one-way (writer continues to serialize `project_lead` and `package_managers[*]` as scalars, matching how darnit had authored them pre-reconciliation).

## Public dataclass attributes

See [data-model.md](../data-model.md) for the complete per-field table. Only the following attributes have any post-reconciliation behavior change; all other attributes are `KEPT` verbatim:

| Attribute | Type | Change class | Consumer impact |
|-----------|------|--------------|-----------------|
| `ProjectConfig.project_lead` | `str` | KEPT-WITH-RESHAPE | Accepts a list-form YAML input; consumer reads the first element only. |
| `ProjectConfig.cncf_slack_channel` | `str` | KEPT-WITH-ALIAS | Populated from the old YAML key with a deprecation warning; not populated from the new `slack_channels` key. |
| `ProjectConfig.package_managers` | `dict[str, str]` | KEPT-WITH-RESHAPE | Accepts per-key list-form values; consumer reads the first element per key. |

Consumer impact is bounded to "receives the same value type it did before, possibly a different content when the source YAML used the new list form." No consumer sees a new attribute type or a missing attribute.

## Warning behavior

### `cncf_slack_channel` deprecation

**Trigger**: Presence of the YAML key `cncf_slack_channel` in a `.project/project.yaml` being parsed.

**Channel**: `warnings.warn(message, DeprecationWarning, stacklevel=2)`.

**Exact message text** (subject to review at implementation time):

```
The .project/ specification field `cncf_slack_channel` is deprecated
upstream. This alias is accepted by darnit v0.1.x (spec version 1.2.0)
and will be removed in the next release. Migrate to the `slack_channels`
list form defined in the CNCF spec:
https://github.com/cncf/automation/tree/main/utilities/dot-project
```

The message intentionally names darnit's version identifier (`1.2.0`) so a maintainer grepping a warning traceback can identify which reconciliation introduced the alias.

## Backward compatibility guarantees

For every `.project/project.yaml` file that parses successfully under the pre-reconciliation reader (spec version `1.1.0`), the post-reconciliation reader (spec version `1.2.0`) MUST:

1. Also parse the file successfully (no new hard failures).
2. Produce a `ProjectConfig` whose attribute values equal the pre-reconciliation values for every attribute in the [data-model.md](../data-model.md) table, EXCEPT that a `cncf_slack_channel`-carrying file MAY additionally emit a `DeprecationWarning`.
3. Produce a `_extra` dict that includes any newly-seen upstream keys (specifically `slack_channels` when the file has been updated to use it).

Item (2) is the mechanical property SC-002 hangs on, and the fixture-plus-golden-dict test at `tests/darnit/context/test_full_field_coverage.py` (introduced by this feature) is what checks it.

## Forward compatibility surface

The reader's `_extra: dict[str, Any]` catch-all is the forward-compatibility mechanism. Every future upstream drift that only ADDS fields will land in `_extra` and require no code change. Future drifts that RENAME or RESHAPE fields will require a new reconciliation feature; the reader does NOT attempt to speculatively handle unseen renames.

## Non-goals

- The reader does NOT expose `project_leads: list[str]` as a new attribute (Q1: parse-only).
- The reader does NOT expose `slack_channels: list[SlackChannel]` as a new attribute (Q1: parse-only).
- The reader does NOT round-trip the new list form on write; `DotProjectWriter` continues to emit scalars for `project_lead` and `package_managers[*]`.
- The reader does NOT bump its version identifier past `1.2.0` in this reconciliation; the next reconciliation bumps again per Q3.
