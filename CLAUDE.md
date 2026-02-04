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
│       ├── controls/        # Python-defined control checks
│       ├── checks/          # Legacy check functions
│       ├── remediation/     # Auto-fix actions
│       └── rules/           # SARIF rule catalog
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
impl.get_check_functions()       # Dict: Legacy check functions
impl.get_rules_catalog()         # Dict: SARIF rule definitions
impl.get_remediation_registry()  # Dict: Auto-fix mappings
impl.get_framework_config_path() # Path | None: TOML config location
impl.register_controls()         # None: Register Python controls
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
        from .controls import checks  # noqa: F401
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

The verification pipeline follows a 4-phase pattern:

```
DETERMINISTIC → PATTERN → LLM → MANUAL
     ↓              ↓        ↓       ↓
  Exact checks   Heuristics  AI    Human
  (high conf)    (med conf)  eval  review
```

Each control can define passes at each phase. The orchestrator stops at the first conclusive result.

## Development Guidelines

### Adding New Controls

1. Define the control in the framework TOML file
2. Optionally add Python pass definitions in `controls/level*.py`
3. Register using the `@register_control` decorator

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

### Legacy Code Migration

The `rules/catalog.py` is deprecated. SARIF metadata now reads from TOML:
- Primary source: `openssf-baseline.toml` control definitions
- Fallback: `rules/catalog.py` (for unmigrated controls)

When adding new controls, define all metadata in TOML.

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
