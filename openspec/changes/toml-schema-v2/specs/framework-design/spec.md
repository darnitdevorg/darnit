# Framework Design - Delta Specification

This delta modifies the `framework-design` spec to add new TOML schema sections.

## MODIFIED Requirements

### Requirement: TOML Root Structure
The TOML schema root structure SHALL include new sections for plugins, context, and .project/ integration.

```toml
[metadata]
name = "framework-name"           # REQUIRED: Framework identifier
display_name = "Framework Name"   # REQUIRED: Human-readable name
version = "0.1.0"                 # REQUIRED: Framework version
schema_version = "1.0.0"          # REQUIRED: TOML schema version (bumped for breaking changes)
spec_version = "Spec v1.0"        # OPTIONAL: Upstream spec version
description = "..."               # OPTIONAL: Framework description
url = "https://..."               # OPTIONAL: Spec URL

[plugins]                         # NEW: Plugin dependencies
allow_unsigned = false            # Whether to allow unsigned plugins
trusted_publishers = []           # List of trusted Sigstore publishers

[plugins.plugin-name]             # NEW: Specific plugin constraints
version = ">=1.0.0"               # Version constraint

[defaults]
check_adapter = "builtin"         # Default check adapter
remediation_adapter = "builtin"   # Default remediation adapter

[context]                         # NEW: Context variable definitions
# Context collection definitions

[templates]
# Reusable templates for remediation

[controls]
# Control definitions (main content)
```

#### Scenario: Schema version bump
- **WHEN** config uses new schema features (plugins, context, CEL expressions)
- **THEN** `schema_version` SHALL be `"1.0.0"` or higher

#### Scenario: Backward compatible loading
- **WHEN** config has `schema_version = "0.1.0-alpha"`
- **THEN** the framework SHALL load it in compatibility mode
- **AND** SHALL log deprecation warnings for old syntax

### Requirement: Pass Definition with CEL Expression
Pass definitions SHALL support an `expr` field for CEL-based evaluation.

```toml
[controls."OSPS-AC-03.01".passes.deterministic]
# Old style (deprecated but supported):
api_check = "darnit_baseline.checks:check_branch_protection"

# New style with CEL:
exec = ["gh", "api", "/repos/$OWNER/$REPO/branches/$BRANCH/protection"]
expr = "response.body.required_pull_request_reviews != null"
```

#### Scenario: CEL expression in exec pass
- **WHEN** exec pass has both `exec` command and `expr` field
- **THEN** the framework SHALL run the command
- **AND** SHALL evaluate `expr` against the command output

#### Scenario: CEL expression standalone
- **WHEN** pass has only `expr` field referencing context
- **THEN** the framework SHALL evaluate against current context without running commands

### Requirement: Context Variable Definition
The `[context]` section SHALL define variables that may need user input.

```toml
[context.maintainers]
description = "List of project maintainers"
type = "list[string]"
source = "MAINTAINERS.md"           # Try to parse from file first
parser = "markdown_list"            # Parser for the source file
prompt = "Who are the maintainers?" # Ask user if source fails
required = true                     # Block remediation if not resolved
confirm = true                      # Ask user to confirm auto-detected value

[context.security_contact]
description = "Security contact email"
type = "email"
source = ".project/project.yaml"
source_path = "security.contact"    # JSONPath within the source
prompt = "What email should security issues be reported to?"
```

#### Scenario: Context from .project/
- **WHEN** context has `source = ".project/project.yaml"` and `source_path`
- **THEN** the framework SHALL extract the value using the path

#### Scenario: Context with parser
- **WHEN** context has `source` file and `parser`
- **THEN** the framework SHALL use the specified parser to extract values

### Requirement: Remediation Write-Back
Remediation actions SHALL support updating .project/ files.

```toml
[controls."OSPS-VM-02.01".remediation]
[controls."OSPS-VM-02.01".remediation.file_create]
path = "SECURITY.md"
template = "security_policy_standard"

[controls."OSPS-VM-02.01".remediation.project_update]
set = { "security.policy.path" = "SECURITY.md" }
```

#### Scenario: project_update action
- **WHEN** remediation includes `project_update` with `set`
- **THEN** the framework SHALL update `.project/project.yaml` with those values
- **AND** SHALL create the file if it doesn't exist

## ADDED Requirements

### Requirement: Plugin Declaration
Controls MAY reference handlers by name without module paths when plugins are declared.

#### Scenario: Handler by name
- **WHEN** `[plugins.darnit-baseline]` is declared
- **AND** control uses `handler = "create_security_policy"`
- **THEN** the framework SHALL resolve the handler from the plugin's registered handlers

#### Scenario: Explicit module path still works
- **WHEN** control uses `handler = "darnit_baseline.remediation:create_security_policy"`
- **THEN** the framework SHALL load from that explicit path
- **AND** SHALL validate against allowed module prefixes
