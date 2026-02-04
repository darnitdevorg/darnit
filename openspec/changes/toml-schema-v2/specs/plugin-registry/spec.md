# Plugin Registry Specification

## ADDED Requirements

### Requirement: Plugins section in TOML
The framework SHALL support a `[plugins]` section for declaring plugin dependencies.

#### Scenario: Declare plugin dependency
- **WHEN** TOML contains:
  ```toml
  [plugins.darnit-baseline]
  version = ">=1.0.0"
  ```
- **THEN** the framework SHALL require that plugin to be installed
- **AND** SHALL verify the version constraint

#### Scenario: Plugin not installed
- **WHEN** a declared plugin is not installed
- **THEN** the framework SHALL report an error with installation instructions

#### Scenario: Version mismatch
- **WHEN** installed plugin version does not satisfy the constraint
- **THEN** the framework SHALL report an error with required vs installed versions

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

### Requirement: Plugin signing with Sigstore
The framework SHALL support Sigstore-based plugin verification.

#### Scenario: Signed plugin verification
- **WHEN** a plugin has a Sigstore signature
- **AND** `allow_unsigned = false` in config
- **THEN** the framework SHALL verify the signature via Sigstore
- **AND** SHALL load the plugin only if verification succeeds

#### Scenario: Unsigned plugin with opt-in
- **WHEN** a plugin does not have a signature
- **AND** `allow_unsigned = true` in config
- **THEN** the framework SHALL load the plugin
- **AND** SHALL log a warning about unsigned plugin

#### Scenario: Unsigned plugin blocked
- **WHEN** a plugin does not have a signature
- **AND** `allow_unsigned = false` in config
- **THEN** the framework SHALL refuse to load the plugin
- **AND** SHALL report an error

#### Scenario: Trusted publishers
- **WHEN** config contains `trusted_publishers = ["openssf", "kusari-oss"]`
- **AND** plugin is signed by a key from those publishers
- **THEN** the framework SHALL trust the plugin

#### Scenario: Sigstore unavailable
- **WHEN** Sigstore services are unreachable
- **THEN** the framework SHALL use cached verification results if available
- **AND** SHALL warn if no cached result exists

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

#### Scenario: Signing guide
- **WHEN** plugin developer reads documentation
- **THEN** they SHALL find instructions for signing plugins with Sigstore
