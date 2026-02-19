## ADDED Requirements

### Requirement: Auto-detect all project languages
The auto-detection subsystem SHALL detect all programming languages present in the repository and expose them as a `languages` context key containing a list of strings. This is in addition to the existing `primary_language` key which continues to return a single string.

#### Scenario: Single-language repository
- **WHEN** auto-detection runs on a repository containing only `go.mod`
- **THEN** the context SHALL include `languages = ["go"]`
- **AND** SHALL include `primary_language = "go"`

#### Scenario: Multi-language repository
- **WHEN** auto-detection runs on a repository containing `go.mod` and `package.json`
- **THEN** the context SHALL include `languages = ["go", "javascript"]`
- **AND** SHALL include `primary_language = "go"` (first match by detection order)

#### Scenario: TypeScript refinement in languages list
- **WHEN** auto-detection runs on a repository containing `package.json` and `tsconfig.json`
- **THEN** the `languages` list SHALL include `"typescript"` rather than `"javascript"`

#### Scenario: Multi-language with TypeScript
- **WHEN** auto-detection runs on a repository containing `go.mod`, `package.json`, and `tsconfig.json`
- **THEN** the context SHALL include `languages = ["go", "typescript"]`
- **AND** SHALL include `primary_language = "go"`

#### Scenario: No manifest files found
- **WHEN** auto-detection runs on a repository with no recognized manifest files
- **THEN** the context SHALL include `languages = []`
- **AND** SHALL include `primary_language = null`

#### Scenario: languages detection scans same manifest set as primary_language
- **WHEN** auto-detection runs
- **THEN** the `languages` detection SHALL use the same manifest-to-language mapping as `primary_language` detection: `go.mod` → go, `Cargo.toml` → rust, `pyproject.toml`/`setup.py`/`setup.cfg` → python, `pom.xml`/`build.gradle`/`build.gradle.kts` → java, `package.json` → javascript (refined to typescript if `tsconfig.json` exists)

### Requirement: languages context key is available in when clauses and templates
The `languages` context key SHALL be available for use in `when` clause evaluation and in template variable substitution, following the same patterns as other auto-detected context values.

#### Scenario: languages available in when clause
- **WHEN** a handler invocation declares `when = { languages = "go" }`
- **AND** the auto-detected `languages` list contains `"go"`
- **THEN** the `when` condition SHALL evaluate to true

#### Scenario: languages available in template substitution
- **WHEN** a remediation template references `${context.languages}`
- **AND** the auto-detected `languages` list is `["go", "typescript"]`
- **THEN** the template SHALL substitute `"go typescript"` (space-separated list)

### Requirement: languages context key is stored and flattened
The context storage layer SHALL support the `languages` key in both storage (`.project/project.yaml` or `.baseline.toml`) and flattening (for `when` clause evaluation).

#### Scenario: languages persisted in context storage
- **WHEN** `languages` is auto-detected as `["go", "typescript"]`
- **THEN** the value SHALL be storable in `.project/project.yaml` under the platform context
- **AND** SHALL be retrievable via `load_context()`

#### Scenario: languages included in flattened context
- **WHEN** `flatten_user_context()` is called
- **AND** the context includes `languages = ["go", "typescript"]`
- **THEN** the flattened dict SHALL include `"languages": ["go", "typescript"]`
- **AND** the list value SHALL be preserved (not converted to string)
