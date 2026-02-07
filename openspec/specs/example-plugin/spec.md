## ADDED Requirements

### Requirement: Package satisfies ComplianceImplementation protocol
The `darnit-example` package SHALL export a `register()` function that returns an object satisfying the `ComplianceImplementation` protocol. The implementation SHALL pass `isinstance(register(), ComplianceImplementation)`.

#### Scenario: Protocol compliance check
- **WHEN** `register()` is called
- **THEN** the returned object satisfies all required protocol properties (`name`, `display_name`, `version`, `spec_version`) and methods (`get_all_controls`, `get_controls_by_level`, `get_rules_catalog`, `get_remediation_registry`, `get_framework_config_path`, `register_controls`)

#### Scenario: Entry point discovery
- **WHEN** the package is installed via `uv sync`
- **THEN** darnit's plugin discovery system finds it under the `darnit.implementations` entry point group with key `example-hygiene`

### Requirement: Package defines 8 controls across 2 levels
The implementation SHALL define exactly 8 controls: 6 at level 1 and 2 at level 2. Control IDs SHALL follow the `PH-{DOMAIN}-NN` format.

#### Scenario: Level 1 controls
- **WHEN** `get_controls_by_level(1)` is called
- **THEN** 6 controls are returned with IDs `PH-DOC-01`, `PH-DOC-02`, `PH-DOC-03`, `PH-SEC-01`, `PH-CFG-01`, `PH-CFG-02`

#### Scenario: Level 2 controls
- **WHEN** `get_controls_by_level(2)` is called
- **THEN** 2 controls are returned with IDs `PH-QA-01`, `PH-CI-01`

#### Scenario: Total control count
- **WHEN** `get_all_controls()` is called
- **THEN** exactly 8 `ControlSpec` instances are returned

### Requirement: TOML-defined controls use file_must_exist pass
Controls `PH-DOC-01`, `PH-DOC-02`, `PH-SEC-01`, `PH-CFG-01`, `PH-CFG-02`, and `PH-QA-01` SHALL be defined declaratively in the TOML configuration file using `file_must_exist` deterministic passes.

#### Scenario: TOML control for README
- **WHEN** the sieve evaluates `PH-DOC-01` against a directory containing `README.md`
- **THEN** the deterministic pass returns `PASS`

#### Scenario: TOML control for missing file
- **WHEN** the sieve evaluates `PH-CFG-01` against a directory without `.gitignore`
- **THEN** the deterministic pass returns `FAIL`

### Requirement: Python controls use factory function pattern
Controls `PH-DOC-03` and `PH-CI-01` SHALL be defined in Python using the factory function pattern (`_create_*_check() -> Callable[[CheckContext], PassResult]`) and registered via `register_control()`.

#### Scenario: README description check passes
- **WHEN** `PH-DOC-03` is evaluated against a README with substantive content (>20 chars beyond title)
- **THEN** the deterministic pass returns `PASS`

#### Scenario: README description check fails for title-only
- **WHEN** `PH-DOC-03` is evaluated against a README containing only a heading
- **THEN** the deterministic pass returns `FAIL`

#### Scenario: CI config detection via glob
- **WHEN** `PH-CI-01` is evaluated against a directory with `.github/workflows/ci.yml`
- **THEN** the deterministic pass returns `PASS`

#### Scenario: CI config missing
- **WHEN** `PH-CI-01` is evaluated against a directory with no CI configuration files
- **THEN** the deterministic pass returns `FAIL`

### Requirement: Multi-phase sieve demonstration
Control `PH-SEC-01` SHALL define deterministic, pattern, and manual passes to demonstrate the multi-phase sieve pipeline. Control `PH-DOC-03` SHALL define deterministic, pattern (custom analyzer), and manual passes.

#### Scenario: Security policy found by file existence
- **WHEN** `PH-SEC-01` is evaluated and `SECURITY.md` exists
- **THEN** the deterministic pass returns `PASS` and subsequent passes are not needed

#### Scenario: README quality pattern analysis
- **WHEN** `PH-DOC-03` pattern pass runs against a README with "Installation" and "Usage" sections
- **THEN** the pattern pass returns `PASS`

### Requirement: Remediation actions create missing files
The package SHALL provide remediation actions `create_readme` and `create_gitignore` that create template files. Both SHALL support `dry_run` mode and SHALL skip creation if the target file already exists.

#### Scenario: Dry run does not write
- **WHEN** `create_readme(path, dry_run=True)` is called
- **THEN** no file is created and the result status is `"dry_run"`

#### Scenario: File creation
- **WHEN** `create_readme(path, dry_run=False)` is called on a directory without README.md
- **THEN** a README.md file is created with the project name as title

#### Scenario: Skip existing file
- **WHEN** `create_gitignore(path, dry_run=False)` is called on a directory that already has `.gitignore`
- **THEN** the existing file is not modified and the result status is `"skipped"`

### Requirement: Handler registration with plugin context
The implementation SHALL provide a `register_handlers()` method that registers at least one handler with the framework's handler registry. The handler SHALL be tagged with the plugin name `"example-hygiene"`.

#### Scenario: Handler appears in registry
- **WHEN** `register_handlers()` is called
- **THEN** the handler `"example_hygiene_check"` is present in the handler registry with plugin context `"example-hygiene"`

### Requirement: Framework config path resolves to existing file
`get_framework_config_path()` SHALL return a `Path` object pointing to `example-hygiene.toml` that exists on disk.

#### Scenario: Config path exists
- **WHEN** `get_framework_config_path()` is called
- **THEN** the returned path has filename `example-hygiene.toml` and `path.exists()` is `True`

### Requirement: Framework integration with minimal changes
The package SHALL integrate into the darnit workspace with only two framework-side changes: adding `"darnit_example."` to `ALLOWED_MODULE_PREFIXES` in handlers.py, and adding `darnit-example` to the root `pyproject.toml` workspace sources and ruff config.

#### Scenario: Module prefix allowlisted
- **WHEN** handler resolution attempts to load a `darnit_example.*` module
- **THEN** the security allowlist permits the import

### Requirement: Documentation cross-references
The package README SHALL map each section of `docs/IMPLEMENTATION_GUIDE.md` to its corresponding example file. The implementation guide SHALL reference `packages/darnit-example/` as a working companion example.

#### Scenario: Guide references example
- **WHEN** a reader opens `docs/IMPLEMENTATION_GUIDE.md`
- **THEN** a callout after Prerequisites points to `packages/darnit-example/` and the Key file paths table includes example package entries
