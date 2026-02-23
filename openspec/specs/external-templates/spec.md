## ADDED Requirements

### Requirement: Template file resolution relative to framework TOML
The config loader or remediation executor SHALL resolve `file` paths on `[templates.*]` entries relative to the directory containing the framework TOML file (not the repository being audited). This enables implementation packages to ship template files alongside their TOML config.

#### Scenario: File path resolved relative to TOML directory
- **WHEN** a `[templates.foo]` entry has `file = "templates/foo.tmpl"`
- **AND** the framework TOML is at `packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml`
- **THEN** the executor SHALL read the template from `packages/darnit-baseline/src/darnit_baseline/templates/foo.tmpl`

#### Scenario: Absolute file path used as-is
- **WHEN** a `[templates.foo]` entry has `file = "/etc/templates/foo.tmpl"`
- **THEN** the executor SHALL read the template from `/etc/templates/foo.tmpl` without modification

#### Scenario: File not found produces clear error
- **WHEN** a `[templates.foo]` entry has `file = "templates/missing.tmpl"`
- **AND** the resolved path does not exist
- **THEN** the executor SHALL log a warning identifying the missing file path
- **AND** the executor SHALL return None for that template (same as no content)

### Requirement: Exactly one of file or content must be set
A `[templates.*]` entry SHALL have exactly one of `file` or `content` set. Having both or neither is a validation error caught at config load time.

#### Scenario: Both file and content specified
- **WHEN** a `[templates.foo]` entry has both `file = "templates/foo.tmpl"` and `content = "..."`
- **THEN** the config loader SHALL raise a validation error indicating both cannot be set

#### Scenario: Neither file nor content specified
- **WHEN** a `[templates.foo]` entry has neither `file` nor `content`
- **THEN** the config loader SHALL raise a validation error indicating one must be set

#### Scenario: Only file specified is valid
- **WHEN** a `[templates.foo]` entry has `file = "templates/foo.tmpl"` and no `content`
- **THEN** the config loader SHALL accept the entry as valid

#### Scenario: Only content specified is valid
- **WHEN** a `[templates.foo]` entry has `content = "..."` and no `file`
- **THEN** the config loader SHALL accept the entry as valid

### Requirement: Framework path propagation
The framework TOML file path SHALL be propagated from the config loader through to the remediation executor so that `file` references can be resolved correctly.

#### Scenario: Implementation provides framework path
- **WHEN** an implementation's `get_framework_config_path()` returns a `Path`
- **THEN** the directory of that path SHALL be available to the remediation executor for template file resolution

#### Scenario: No framework path available falls back to local_path
- **WHEN** the framework path is not available (e.g., in-memory config)
- **THEN** the executor SHALL fall back to resolving `file` paths relative to `local_path` (the repo being audited)

### Requirement: Template file extension convention
External template files SHOULD use the `.tmpl` extension. The framework SHALL NOT enforce a specific extension — any text file is acceptable.

#### Scenario: .tmpl file is loaded
- **WHEN** a template entry specifies `file = "templates/security.tmpl"`
- **THEN** the file SHALL be read as UTF-8 text regardless of extension

#### Scenario: Non-.tmpl file is loaded
- **WHEN** a template entry specifies `file = "templates/license-apache.txt"`
- **THEN** the file SHALL be read as UTF-8 text without error

### Requirement: Variable substitution applies to file-sourced templates
Templates loaded from `file` SHALL undergo the same `$OWNER`, `$REPO`, `$BRANCH`, `$YEAR`, `${context.*}`, and `${project.*}` variable substitution as inline `content` templates.

#### Scenario: Variables substituted in file-sourced template
- **WHEN** a template is loaded from a `.tmpl` file containing `$OWNER` and `${context.maintainers}`
- **THEN** the executor SHALL substitute those variables identically to how it handles inline content

### Requirement: Baseline templates migrated to external files
The OpenSSF Baseline implementation SHALL migrate all 52 `[templates.*]` entries from inline `content` to external `.tmpl` files in a `templates/` directory alongside the TOML config.

#### Scenario: Templates directory exists in baseline package
- **WHEN** the darnit-baseline package is installed
- **THEN** a `templates/` directory SHALL exist alongside `openssf-baseline.toml`
- **AND** it SHALL contain one `.tmpl` file per named template

#### Scenario: TOML references file instead of inline content
- **WHEN** `openssf-baseline.toml` defines `[templates.security_policy_standard]`
- **THEN** the entry SHALL use `file = "templates/security_policy_standard.tmpl"` instead of inline `content`
- **AND** the `description` field SHALL be preserved in the TOML entry

#### Scenario: Template content is identical after migration
- **WHEN** a template is migrated from inline `content` to a `.tmpl` file
- **THEN** the file content SHALL be byte-identical to the previous inline content (no added/removed whitespace)
