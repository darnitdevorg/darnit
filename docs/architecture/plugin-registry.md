# Plugin Registry Specification

## ADDED Requirements

### Requirement: Operator allow-list
Operator configuration SHALL restrict which installed plugins load with `[plugins] allowed` (framework-design 6.6). A framework TOML `[plugins]` section is not read.

#### Scenario: Plugin left out
- **WHEN** operator configuration contains:
  ```toml
  [plugins]
  allowed = ["openssf-baseline"]
  ```
- **THEN** the framework SHALL NOT load the `darnit.implementations` or `darnit.frameworks` entry points of any other plugin
- **AND** SHALL refuse an audit of a framework not in the list

#### Scenario: No allow-list
- **WHEN** `allowed` is empty or absent
- **THEN** every installed plugin MAY load

### Requirement: Plugin auto-registration
Plugins SHALL auto-register their capabilities when loaded.

#### Scenario: Plugin registers handlers
- **WHEN** a plugin is loaded
- **THEN** the framework SHALL discover and register all handlers decorated with `@register_handler`

#### Scenario: Plugin registers passes
- **WHEN** a plugin is loaded
- **THEN** the framework SHALL discover and register all pass implementations decorated with `@register_pass`

#### Scenario: Plugin registers templates
- **WHEN** a plugin is loaded
- **THEN** the framework SHALL discover and register all templates from the plugin's `templates/` directory

#### Scenario: No manual wiring needed
- **WHEN** a control references a handler by name (e.g., `handler = "create_security_policy"`)
- **THEN** the framework SHALL resolve it from registered handlers
- **AND** SHALL NOT require explicit module path

### Requirement: Plugin manifest
Plugins SHALL declare their capabilities in package metadata.

#### Scenario: Entry point registration
- **WHEN** a plugin is installed via pip
- **THEN** it SHALL register via the `darnit.plugins` entry point group

#### Scenario: Plugin metadata
- **WHEN** a plugin is loaded
- **THEN** its metadata SHALL include:
  - `name` (plugin identifier)
  - `version` (semantic version)
  - `provides` (list of capabilities: handlers, passes, templates)
  - `requires` (minimum darnit framework version)

### Requirement: No plugin signature verification
The framework SHALL NOT claim to verify plugin signatures. Installing a package is the decision to trust its code; verifying a package before installing it is the installer's job (framework-design 6.6, Appendix C).

#### Scenario: Removed signature settings
- **WHEN** operator configuration sets `[plugins] allow_unsigned` or `trusted_publishers`
- **THEN** loading it SHALL fail with a message that the key was removed

### Requirement: Plugin isolation
The framework SHALL isolate plugins to limit security impact.

#### Scenario: Whitelist module prefixes
- **WHEN** a plugin attempts to register a handler
- **THEN** the handler module SHALL match allowed prefixes: `darnit.`, `darnit_*`, or registered plugin namespaces

#### Scenario: Reject unknown modules
- **WHEN** TOML references a handler in an unknown module (e.g., `handler = "malicious.code:exploit"`)
- **THEN** the framework SHALL reject the reference
- **AND** SHALL report a security error

### Requirement: Plugin discovery
The framework SHALL discover plugins from multiple sources.

#### Scenario: Installed packages
- **WHEN** a package with `darnit.plugins` entry point is installed
- **THEN** the framework SHALL discover it automatically

#### Scenario: Local plugins
- **WHEN** repository contains `.darnit/plugins/` directory with Python modules
- **THEN** the framework SHALL load plugins from that directory
- **AND** SHALL treat them as unsigned

### Requirement: Plugin documentation
The framework SHALL provide clear documentation about plugin security.

#### Scenario: Security warning in docs
- **WHEN** documentation describes the plugin system
- **THEN** it SHALL clearly state that plugins execute arbitrary code
- **AND** SHALL advise users to only install trusted plugins

#### Scenario: Publishing guide
- **WHEN** plugin developer reads documentation
- **THEN** they SHALL find instructions for publishing plugins with attestations that installers can verify
