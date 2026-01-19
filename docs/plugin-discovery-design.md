# Plugin Discovery System Design

## Overview

This document describes the design for a unified plugin discovery system that enables:

1. **Framework packages** to define compliance frameworks via TOML + Python adapters
2. **Plugin packages** to provide reusable adapters (checks, remediations) across frameworks
3. **User configs** to reference adapters from any installed package

## Current State Analysis

### Existing Entry Point Groups

| Group | Purpose | Example |
|-------|---------|---------|
| `darnit.implementations` | Legacy: Full compliance implementations | `openssf-baseline = "darnit_baseline:register"` |
| `darnit.frameworks` | Framework TOML path providers | `testchecks = "darnit_testchecks:get_framework_path"` |
| `darnit.adapters` | Adapter classes | `testchecks = "darnit_testchecks.adapters.builtin:TrivialCheckAdapter"` |

### Current Limitations

1. **No automatic adapter discovery** - Adapters must be explicitly referenced by module path
2. **No namespace collision handling** - Two packages could register same adapter name
3. **No adapter metadata** - Can't list available adapters without loading them
4. **No versioning/compatibility** - No way to specify adapter compatibility requirements

---

## Proposed Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Plugin Registry                                    │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │  Frameworks     │  │  Adapters       │  │  Remediations   │              │
│  │  ─────────────  │  │  ─────────────  │  │  ─────────────  │              │
│  │  openssf-base.. │  │  builtin        │  │  builtin        │              │
│  │  testchecks     │  │  kusari         │  │  github-api     │              │
│  │  soc2           │  │  trivy          │  │  file-creator   │              │
│  │  custom-corp    │  │  custom-sca     │  │  custom-fix     │              │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
                    ▼               ▼               ▼
        ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
        │ darnit-       │ │ darnit-       │ │ darnit-       │
        │ baseline      │ │ plugins       │ │ custom        │
        │               │ │               │ │               │
        │ Entry Points: │ │ Entry Points: │ │ Entry Points: │
        │ • frameworks  │ │ • adapters    │ │ • frameworks  │
        │ • adapters    │ │               │ │ • adapters    │
        └───────────────┘ └───────────────┘ └───────────────┘
```

---

## Entry Point Groups

### 1. `darnit.frameworks` - Framework Definitions

Packages that provide complete compliance frameworks (TOML + adapters).

**Entry Point Format:**
```toml
[project.entry-points."darnit.frameworks"]
framework_name = "package.module:get_framework_path"
```

**Contract:**
```python
def get_framework_path() -> Path:
    """Return path to framework TOML file."""
    ...
```

**Examples:**
```toml
# darnit-baseline
[project.entry-points."darnit.frameworks"]
openssf-baseline = "darnit_baseline:get_framework_path"

# darnit-testchecks
[project.entry-points."darnit.frameworks"]
testchecks = "darnit_testchecks:get_framework_path"

# Corporate framework
[project.entry-points."darnit.frameworks"]
acme-security = "acme_compliance:get_framework_path"
```

### 2. `darnit.check_adapters` - Check Adapters

Packages that provide check execution capabilities.

**Entry Point Format:**
```toml
[project.entry-points."darnit.check_adapters"]
adapter_name = "package.module:AdapterClass"
```

**Contract:**
```python
class MyCheckAdapter(CheckAdapter):
    def name(self) -> str: ...
    def capabilities(self) -> AdapterCapability: ...
    def check(self, control_id, owner, repo, local_path, config) -> CheckResult: ...
```

**Examples:**
```toml
# darnit-plugins
[project.entry-points."darnit.check_adapters"]
kusari = "darnit_plugins.adapters.kusari:KusariAdapter"
trivy = "darnit_plugins.adapters.trivy:TrivyAdapter"
semgrep = "darnit_plugins.adapters.semgrep:SemgrepAdapter"

# darnit-baseline
[project.entry-points."darnit.check_adapters"]
openssf-builtin = "darnit_baseline.adapters.builtin:OpenSSFCheckAdapter"
```

### 3. `darnit.remediation_adapters` - Remediation Adapters

Packages that provide remediation capabilities.

**Entry Point Format:**
```toml
[project.entry-points."darnit.remediation_adapters"]
adapter_name = "package.module:AdapterClass"
```

**Contract:**
```python
class MyRemediationAdapter(RemediationAdapter):
    def name(self) -> str: ...
    def capabilities(self) -> AdapterCapability: ...
    def remediate(self, control_id, owner, repo, local_path, config, dry_run) -> RemediationResult: ...
```

### 4. `darnit.implementations` (Legacy)

Keep for backwards compatibility with existing `darnit-baseline` registration.

---

## PluginRegistry API

### Core Class

```python
@dataclass
class PluginRegistry:
    """Central registry for all darnit plugins.

    Discovers and manages:
    - Frameworks (compliance framework definitions)
    - Check adapters (verification implementations)
    - Remediation adapters (fix implementations)

    Thread-safe with lazy loading and caching.
    """

    # ─────────────────────────────────────────────────────────────────────
    # Discovery Methods
    # ─────────────────────────────────────────────────────────────────────

    def discover_all(self) -> None:
        """Discover all plugins from entry points."""

    def discover_frameworks(self) -> Dict[str, FrameworkInfo]:
        """Discover all installed frameworks."""

    def discover_check_adapters(self) -> Dict[str, AdapterInfo]:
        """Discover all installed check adapters."""

    def discover_remediation_adapters(self) -> Dict[str, AdapterInfo]:
        """Discover all installed remediation adapters."""

    # ─────────────────────────────────────────────────────────────────────
    # Framework Access
    # ─────────────────────────────────────────────────────────────────────

    def list_frameworks(self) -> List[str]:
        """List all available framework names."""

    def get_framework_path(self, name: str) -> Optional[Path]:
        """Get the TOML path for a framework."""

    def load_framework(self, name: str) -> Optional[FrameworkConfig]:
        """Load and return a framework configuration."""

    # ─────────────────────────────────────────────────────────────────────
    # Adapter Access
    # ─────────────────────────────────────────────────────────────────────

    def list_check_adapters(self) -> List[str]:
        """List all available check adapter names."""

    def get_check_adapter(self, name: str) -> Optional[CheckAdapter]:
        """Get a check adapter instance by name."""

    def list_remediation_adapters(self) -> List[str]:
        """List all available remediation adapter names."""

    def get_remediation_adapter(self, name: str) -> Optional[RemediationAdapter]:
        """Get a remediation adapter instance by name."""

    # ─────────────────────────────────────────────────────────────────────
    # Registration (for programmatic use)
    # ─────────────────────────────────────────────────────────────────────

    def register_framework(self, name: str, path_func: Callable[[], Path]) -> None:
        """Manually register a framework."""

    def register_check_adapter(self, name: str, adapter: Union[Type[CheckAdapter], CheckAdapter]) -> None:
        """Manually register a check adapter."""

    def register_remediation_adapter(self, name: str, adapter: Union[Type[RemediationAdapter], RemediationAdapter]) -> None:
        """Manually register a remediation adapter."""

    # ─────────────────────────────────────────────────────────────────────
    # Config-based Registration
    # ─────────────────────────────────────────────────────────────────────

    def register_from_config(self, adapters: Dict[str, AdapterConfig]) -> None:
        """Register adapters from TOML config definitions.

        Handles:
        - type = "python" → Load from module path
        - type = "command" → Create CommandCheckAdapter
        - type = "script" → Create ScriptCheckAdapter
        """

    # ─────────────────────────────────────────────────────────────────────
    # Utilities
    # ─────────────────────────────────────────────────────────────────────

    def clear_cache(self) -> None:
        """Clear all caches (for testing)."""

    def get_plugin_info(self) -> Dict[str, Any]:
        """Get summary of all discovered plugins."""
```

### Info Classes

```python
@dataclass
class FrameworkInfo:
    """Metadata about a discovered framework."""
    name: str
    package: str           # Package that provides it
    path_func: Callable[[], Path]
    _path: Optional[Path] = None
    _config: Optional[FrameworkConfig] = None

    @property
    def path(self) -> Path:
        if self._path is None:
            self._path = self.path_func()
        return self._path


@dataclass
class AdapterInfo:
    """Metadata about a discovered adapter."""
    name: str
    package: str           # Package that provides it
    adapter_class: Type
    capabilities: Optional[AdapterCapability] = None
    _instance: Optional[Any] = None

    def get_instance(self) -> Any:
        if self._instance is None:
            self._instance = self.adapter_class()
        return self._instance
```

---

## Adapter Resolution Algorithm

When a framework or user config references an adapter, resolution follows this order:

```
1. Explicit module path (type = "python", module = "...")
   └─► importlib.import_module(module)

2. Entry point lookup (just adapter name)
   └─► Check darnit.check_adapters entry points
   └─► Check darnit.remediation_adapters entry points

3. Config-defined adapter (in same config file)
   └─► [adapters.my_adapter] section

4. Fallback to "builtin"
   └─► Use framework's default builtin adapter
```

### Example Resolution

```toml
# User's .baseline.toml
[controls."OSPS-VM-05.02"]
check = { adapter = "kusari" }  # Just the name
```

Resolution:
1. Check if `kusari` is defined in `.baseline.toml` `[adapters]` section → No
2. Check if `kusari` is defined in framework's `[adapters]` section → No
3. Check `darnit.check_adapters` entry points → Found! `darnit_plugins.adapters.kusari:KusariAdapter`
4. Load and instantiate `KusariAdapter`

---

## Config Reference Syntax

### Framework TOML

```toml
# openssf-baseline.toml

[metadata]
name = "openssf-baseline"
version = "0.1.0"

[defaults]
check_adapter = "builtin"

# Local adapter definition (bundled with framework)
[adapters.builtin]
type = "python"
module = "darnit_baseline.adapters.builtin"
class = "OpenSSFCheckAdapter"

# Reference external adapter by name (from entry points)
[adapters.kusari]
type = "plugin"  # New type: resolve via entry points
name = "kusari"

# Or reference external adapter explicitly
[adapters.custom_sca]
type = "python"
module = "darnit_plugins.adapters.sca"
class = "SCACheckAdapter"

[controls."OSPS-VM-05.02"]
name = "PreReleaseSCA"
check = { adapter = "kusari" }  # Uses entry point
```

### User Config (.baseline.toml)

```toml
# .baseline.toml
extends = "openssf-baseline"

# Reference plugin adapter by name
[controls."OSPS-VM-05.02"]
check = { adapter = "kusari" }

# Or define inline with full path
[adapters.my_scanner]
type = "python"
module = "internal_tools.scanner"
class = "InternalScanner"

[controls."OSPS-SA-03.01"]
check = { adapter = "my_scanner" }
```

---

## Example Plugin Package: darnit-plugins

### Package Structure

```
darnit-plugins/
├── pyproject.toml
├── README.md
└── src/darnit_plugins/
    ├── __init__.py
    └── adapters/
        ├── __init__.py
        ├── kusari.py       # Kusari CLI wrapper
        ├── trivy.py        # Trivy scanner wrapper
        ├── semgrep.py      # Semgrep wrapper
        └── github_api.py   # GitHub API checks
```

### pyproject.toml

```toml
[project]
name = "darnit-plugins"
version = "0.1.0"
description = "Common adapters for darnit compliance frameworks"
dependencies = [
    "darnit>=0.1.0",
]

[project.entry-points."darnit.check_adapters"]
kusari = "darnit_plugins.adapters.kusari:KusariCheckAdapter"
trivy = "darnit_plugins.adapters.trivy:TrivyCheckAdapter"
semgrep = "darnit_plugins.adapters.semgrep:SemgrepCheckAdapter"
github-api = "darnit_plugins.adapters.github_api:GitHubAPICheckAdapter"

[project.entry-points."darnit.remediation_adapters"]
github-api = "darnit_plugins.adapters.github_api:GitHubAPIRemediationAdapter"
```

### Adapter Implementation

```python
# src/darnit_plugins/adapters/kusari.py

from darnit.core.adapters import CheckAdapter, CommandCheckAdapter
from darnit.core.models import AdapterCapability, CheckResult, CheckStatus


class KusariCheckAdapter(CheckAdapter):
    """Adapter for Kusari SBOM/SCA tool.

    Wraps the kusari CLI to provide dependency scanning.
    """

    def __init__(self, command: str = "kusari"):
        self._command = CommandCheckAdapter(
            adapter_name="kusari",
            command=command,
            output_format="json",
        )

    def name(self) -> str:
        return "kusari"

    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            control_ids={
                "OSPS-VM-05.02",  # Pre-release SCA
                "OSPS-VM-05.03",  # Known vulnerabilities
                "OSPS-BR-01.02",  # SBOM generation
            },
            supports_batch=True,
        )

    def check(self, control_id, owner, repo, local_path, config) -> CheckResult:
        # Map control to kusari subcommand
        if control_id == "OSPS-VM-05.02":
            config["scan_type"] = "dependencies"
        elif control_id == "OSPS-VM-05.03":
            config["scan_type"] = "vulnerabilities"
        elif control_id == "OSPS-BR-01.02":
            config["scan_type"] = "sbom"

        return self._command.check(control_id, owner, repo, local_path, config)
```

---

## Implementation Plan

### Phase 1: Core Plugin Registry

**Files to create/modify:**

1. **`packages/darnit/src/darnit/core/registry.py`** (NEW)
   - `PluginRegistry` class
   - `FrameworkInfo`, `AdapterInfo` dataclasses
   - Entry point discovery functions
   - Global registry instance and accessor

2. **`packages/darnit/src/darnit/core/adapters.py`** (MODIFY)
   - Update `AdapterRegistry` to use `PluginRegistry`
   - Add `type = "plugin"` support for entry point references
   - Deprecate direct entry point handling (delegate to PluginRegistry)

3. **`packages/darnit/src/darnit/core/__init__.py`** (MODIFY)
   - Export `PluginRegistry`, `get_plugin_registry`

### Phase 2: Framework Discovery Integration

**Files to modify:**

1. **`packages/darnit/src/darnit/config/merger.py`** (MODIFY)
   - Add `load_framework_by_name(name)` function
   - Use `PluginRegistry` to resolve framework paths
   - Support `extends = "framework-name"` with entry point lookup

2. **`packages/darnit/src/darnit/config/framework_schema.py`** (MODIFY)
   - Add `type = "plugin"` to `AdapterType` enum
   - Document entry point reference format

### Phase 3: Audit Integration

**Files to modify:**

1. **`packages/darnit/src/darnit/tools/audit.py`** (MODIFY)
   - Use `PluginRegistry` for adapter resolution
   - Add `--list-plugins` option to show available plugins
   - Support adapter name references without full module paths

### Phase 4: Example Plugin Package

**Files to create:**

1. **`packages/darnit-plugins/`** (NEW)
   - Scaffold package with kusari adapter example
   - Demonstrate entry point registration
   - Include usage documentation

---

## Backwards Compatibility

### Preserved Behaviors

1. **`darnit.implementations` entry points** - Still discovered via `discover_implementations()`
2. **Explicit module paths** - `type = "python", module = "..."` still works
3. **Inline adapter definitions** - `[adapters.name]` in TOML still works
4. **`AdapterRegistry`** - Existing API preserved, now backed by `PluginRegistry`

### Migration Path

1. **Existing frameworks** - No changes required, entry points still work
2. **New adapter packages** - Use new `darnit.check_adapters` entry points
3. **User configs** - Can reference adapters by name once plugins installed

---

## Testing Strategy

### Unit Tests

```python
class TestPluginRegistry:
    def test_discover_frameworks(self):
        """Should discover frameworks from entry points."""

    def test_discover_check_adapters(self):
        """Should discover check adapters from entry points."""

    def test_adapter_resolution_order(self):
        """Should resolve adapters in correct priority order."""

    def test_config_defined_adapter(self):
        """Should use config-defined adapter over entry point."""

    def test_plugin_type_reference(self):
        """Should resolve type='plugin' via entry points."""
```

### Integration Tests

```python
class TestCrossPackageAdapters:
    def test_framework_uses_plugin_adapter(self):
        """Framework should be able to use adapter from another package."""

    def test_user_config_overrides_with_plugin(self):
        """User config should override adapter with plugin."""
```

---

## Open Questions

1. **Namespace collisions**: What happens if two packages register `kusari` adapter?
   - **Proposed**: Last-loaded wins, log warning
   - **Alternative**: Require qualified names (`darnit-plugins:kusari`)

2. **Version compatibility**: Should adapters declare framework compatibility?
   - **Proposed**: Optional `compatible_frameworks` in adapter metadata
   - **Alternative**: Leave to package dependencies

3. **Lazy vs eager loading**: When should adapters be instantiated?
   - **Proposed**: Lazy (on first use) with optional eager via `discover_all()`

---

## Summary

This design enables a pluggable architecture where:

- **Framework authors** can reference adapters from any installed package
- **Plugin authors** can provide reusable adapters via entry points
- **Users** can mix and match adapters in their `.baseline.toml`
- **Backwards compatibility** is preserved for existing implementations

The key addition is the **`PluginRegistry`** that unifies discovery across all plugin types and provides a consistent API for resolution.
