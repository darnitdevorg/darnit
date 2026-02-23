## Why

The OpenSSF Baseline TOML configuration (`openssf-baseline.toml`) is 5,465 lines, of which ~40% (2,176 lines) are multi-line template strings embedded inline. The largest single template (`license_apache`) is 192 lines of verbatim Apache-2.0 license text stored as a TOML `"""` string. This makes the file difficult to navigate, review in diffs, and edit — template content overwhelms the actual control/remediation logic. Externalizing templates to standalone files would cut the TOML to ~3,300 lines and let templates be edited, linted, and diffed as first-class files.

## What Changes

- Add support for external template files (`.tmpl`) referenced from TOML `[templates.*]` sections via a new `file` field as an alternative to inline `content`
- The framework config loader resolves `file` references at load time, making the change transparent to downstream consumers (remediation executor, template variable substitution) — they still see a `content` string
- Migrate the 52 existing `[templates.*]` entries from inline `content` to `.tmpl` files in a `templates/` directory alongside the TOML
- Inline `content` remains supported for small templates — this is additive, not a replacement

## Capabilities

### New Capabilities
- `external-templates`: Support for referencing template content from external `.tmpl` files in framework TOML config, with load-time resolution

### Modified Capabilities
- `framework-design`: The TOML schema gains a `file` field on `[templates.*]` sections as an alternative to `content`

## Impact

- **Config loader** (`packages/darnit/src/darnit/config/`): `FrameworkConfig` / template schema gains `file` field; loader resolves file references relative to the TOML file's directory
- **Framework schema** (`framework_schema.py`): `TemplateConfig` model adds optional `file: str` field with validation (exactly one of `file` or `content` must be set)
- **Baseline package** (`packages/darnit-baseline/`): New `templates/` directory with 52 `.tmpl` files; `openssf-baseline.toml` shrinks by ~2,000 lines
- **Existing tests**: Template-related tests need updated fixtures but no behavior change — resolved templates still produce the same `content` string
- **Plugin authors**: Can use `file` references in their own TOML configs (new capability, no breaking change)
