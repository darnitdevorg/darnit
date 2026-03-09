# Darnit Project Guidelines

This document provides architectural guidelines and development rules for the darnit project.

## Architecture Overview

Darnit is an AI-powered compliance auditing framework with a plugin architecture that separates the core framework from compliance implementations.

### Package Structure

```
packages/
├── darnit/                  # Core framework (MUST NOT import implementations)
│   └── src/darnit/
│       ├── core/            # Plugin system, discovery, logging
│       ├── sieve/           # 4-phase verification pipeline
│       ├── config/          # Configuration loading and merging
│       ├── tools/           # MCP tool implementations
│       └── server/          # MCP server setup
│
├── darnit-baseline/         # OpenSSF Baseline implementation
│   └── src/darnit_baseline/
│       ├── attestation/     # In-toto attestation support
│       ├── config/          # Project context configuration
│       ├── formatters/      # Output formatting (Markdown, JSON, SARIF)
│       ├── remediation/     # Remediation orchestration
│       ├── rules/           # SARIF rule definitions (from TOML)
│       └── threat_model/    # Threat model generation
│
└── darnit-testchecks/       # Test implementation (for testing)
```

## Separation Rules

### Rule 1: Framework MUST NOT Import Implementations

The `darnit` package must never directly import implementation packages.

```python
# ❌ WRONG - Creates hard dependency
import darnit_baseline
from darnit_baseline.controls import level1

# ✅ CORRECT - Use plugin discovery
from darnit.core.discovery import get_default_implementation
impl = get_default_implementation()
if impl:
    controls = impl.get_all_controls()
```

### Rule 2: Implementations MAY Import Framework

Implementation packages can freely import from the framework.

```python
# ✅ OK - Implementation importing framework
from darnit.core.plugin import ComplianceImplementation, ControlSpec
from darnit.sieve import register_control
```

### Rule 3: Use Protocol Methods for Cross-Package Communication

All framework-to-implementation communication must go through the `ComplianceImplementation` protocol.

```python
# Protocol methods available:
impl.name                        # str: Implementation identifier
impl.display_name                # str: Human-readable name
impl.version                     # str: Implementation version
impl.spec_version                # str: Spec version implemented
impl.get_all_controls()          # List[ControlSpec]: All controls
impl.get_controls_by_level(n)    # List[ControlSpec]: Controls at level n
impl.get_rules_catalog()         # Dict: SARIF rule definitions
impl.get_remediation_registry()  # Dict: Auto-fix mappings
impl.get_framework_config_path() # Path | None: TOML config location
impl.register_controls()         # None: Register TOML controls
```

## Plugin System

### Entry Points

Implementations register via Python entry points in `pyproject.toml`:

```toml
[project.entry-points."darnit.implementations"]
openssf-baseline = "darnit_baseline:register"
```

### Creating a New Implementation

1. Create a new package with the implementation class:

```python
# my_framework/implementation.py
from pathlib import Path
from darnit.core.plugin import ComplianceImplementation, ControlSpec

class MyFrameworkImplementation:
    @property
    def name(self) -> str:
        return "my-framework"

    @property
    def display_name(self) -> str:
        return "My Compliance Framework"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def spec_version(self) -> str:
        return "MySpec v1.0"

    def get_all_controls(self) -> list[ControlSpec]:
        # Return your control definitions
        ...

    def get_framework_config_path(self) -> Path | None:
        return Path(__file__).parent / "my-framework.toml"

    def register_controls(self) -> None:
        pass  # Controls are defined in TOML; no Python registration needed
```

2. Add the registration function:

```python
# my_framework/__init__.py
def register():
    from .implementation import MyFrameworkImplementation
    return MyFrameworkImplementation()
```

3. Register via entry point:

```toml
[project.entry-points."darnit.implementations"]
my-framework = "my_framework:register"
```

## Sieve Pattern

The verification pipeline follows a 4-phase pattern using built-in handlers:

```
file_must_exist → exec/regex → llm_eval → manual
       ↓              ↓           ↓         ↓
  File presence   Commands &   AI-based   Human
  checks          patterns     eval       review
```

Each control can define passes at each phase. The orchestrator stops at the first conclusive result.

## Conservative-by-Default Principles

This is a compliance auditing tool. Incorrect results are worse than incomplete results. Every design decision must follow these rules:

### Never Assume Compliance

- A control that has not been **explicitly verified as passing** is NOT compliant. Period.
- "Needs Verification" / WARN means "we don't know" — treat it the same as FAIL for compliance calculations.
- Never report a level as "Compliant" if any control at that level is unverified, errored, or pending.
- It is always better to report a false negative (say something fails when it passes) than a false positive (say something passes when it doesn't).

### Never Guess User-Specific Values

- Do NOT auto-detect and auto-apply values like maintainers, security contacts, or governance models. These require explicit user confirmation.
- The TOML `auto_detect = false` flag means the sieve MUST NOT run for that key. No exceptions.
- When a tool returns "Context Confirmation Required," that is a hard stop — ask the user. Do not fill in values from git history, repo owner, or any heuristic source.
- Sieve auto-detection is acceptable only for keys where `auto_detect = true` in the TOML definition.

### Err on the Side of Caution

- When in doubt about a control's status, return WARN (needs verification), not PASS.
- When in doubt about a user's intent, ask. Do not proceed with assumptions.
- When designing prompts that an LLM will see, assume the LLM will blindly execute any suggested command. Never put guessed values in executable code snippets.

## Development Guidelines

### Adding New Controls

1. Define the control in `openssf-baseline.toml` with passes and metadata
2. Optionally add plugin Python handlers for complex logic
3. Run `uv run python scripts/validate_sync.py --verbose` to verify sync

### Testing

```bash
# Run all tests
uv run pytest tests/ -v

# Run only framework tests
uv run pytest tests/darnit/ -v

# Run only implementation tests
uv run pytest tests/darnit_baseline/ -v
```

### Linting

```bash
# Check for issues
uv run ruff check .

# Auto-fix issues
uv run ruff check --fix .

# Format code
uv run ruff format .
```

## Spec-Implementation Synchronization

The framework design is governed by the authoritative specification at:
`openspec/specs/framework-design/spec.md`

### Sync Enforcement Rules

1. **TOML is Source of Truth**: Control metadata (descriptions, severity, help URLs) should be defined in `openssf-baseline.toml`, not in Python code.

2. **Spec Changes Require Validation**: When modifying framework behavior:
   - Update the spec first
   - Run `uv run python scripts/validate_sync.py --verbose`
   - Ensure pass types in code match spec definitions

3. **Generated Docs Must Stay Fresh**: After spec changes:
   - Run `uv run python scripts/generate_docs.py`
   - Commit any changes to `docs/generated/`

4. **CI Enforces Sync**: PRs are blocked if:
   - TOML configs don't validate against framework schema
   - Pass types in spec don't match implementation
   - Generated docs would change

### Validation Commands

```bash
# Validate spec-implementation sync
uv run python scripts/validate_sync.py --verbose

# Regenerate docs from spec
uv run python scripts/generate_docs.py

# Check if docs are stale
git diff docs/generated/
```

### TOML-First Architecture

All controls are defined in `openssf-baseline.toml`. The `rules/catalog.py` file
is a deprecated fallback that remains for backward compatibility but is not
actively used. All new controls must be defined entirely in TOML.

## TOML Schema Features

### CEL Expressions

Controls can use CEL (Common Expression Language) for pass logic:

```toml
[[controls."OSPS-AC-01.01".passes]]
handler = "exec"
command = ["gh", "api", "/orgs/{org}/settings"]
output_format = "json"
expr = 'output.json.two_factor_requirement_enabled == true'
```

Available context variables:
- `output.stdout`, `output.stderr`, `output.exit_code`, `output.json` (for exec)
- `response.status_code`, `response.body`, `response.headers` (for API)
- `files`, `matches` (for pattern pass)
- `project.*` (from .project/ context)

Custom functions: `file_exists(path)`, `json_path(obj, path)`

### Context System

The framework supports project context from `.project/project.yaml`:

```yaml
# .project/project.yaml
name: my-project
security:
  policy:
    type: SECURITY.md
governance:
  maintainers:
    - "@alice"
    - "@bob"
```

Context is injected into sieve orchestrator and available to CEL expressions.

### Handler Registration

Plugins register handlers using the `register_handlers()` method:

```python
class MyImplementation:
    def register_handlers(self) -> None:
        from darnit.core.handlers import get_handler_registry
        from . import tools

        registry = get_handler_registry()
        registry.set_plugin_context(self.name)

        registry.register_handler("my_tool", tools.my_tool)

        registry.set_plugin_context(None)
```

Handlers can then be referenced by short name in TOML:

```toml
[mcp.tools.my_tool]
handler = "my_tool"  # Short name instead of full module path
```

### Plugin Security

Plugins support Sigstore verification:

```toml
# .baseline.toml
[plugins]
allow_unsigned = false
trusted_publishers = ["https://github.com/kusari-oss"]
```

Default trusted publishers: `kusari-oss`, `kusaridev`

## Common Patterns

### Checking for Protocol Methods

Use `hasattr()` for backward compatibility when adding new protocol methods:

```python
impl = get_default_implementation()
if impl and hasattr(impl, "new_method"):
    impl.new_method()
```

### Graceful Degradation

Always handle missing implementations gracefully:

```python
impl = get_default_implementation()
if impl:
    result = impl.get_all_controls()
else:
    logger.warning("No implementation found")
    result = []
```

## Active Technologies
- Python >=3.11 (project targets 3.11/3.12) + darnit (core framework), darnit-baseline (001-tiered-control-automation)
- TOML config files, `.project/` YAML context, local filesystem (001-tiered-control-automation)

## Recent Changes
- 001-tiered-control-automation: Added Python >=3.11 (project targets 3.11/3.12) + darnit (core framework), darnit-baseline
