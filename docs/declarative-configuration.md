# Declarative Configuration System

The darnit declarative configuration system enables compliance frameworks to be defined via TOML configuration files rather than Python code. This allows:

- **Framework authors** to define compliance frameworks declaratively
- **Framework users** to customize controls for their specific needs
- **Extensibility** through pluggable adapters for check execution

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Framework Package (e.g., darnit-baseline, darnit-testchecks)   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  {framework}.toml                                         │  │
│  │  - metadata (name, version, spec)                         │  │
│  │  - controls (id, level, domain, passes, remediation)      │  │
│  │  - adapters (builtin handlers)                            │  │
│  └───────────────────────────────────────────────────────────┘  │
│  + Python adapters for check execution                          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  User Repository                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  .baseline.toml                                           │  │
│  │  - extends = "framework-name"                             │  │
│  │  - control overrides (status, adapter, config)            │  │
│  │  - custom adapters                                        │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  Effective Configuration (Runtime)                               │
│  - All controls from framework                                   │
│  - User overrides applied                                        │
│  - Adapters resolved and ready                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Framework Definition Format

Framework definitions are TOML files that declare controls, verification passes, and remediation actions.

### Basic Structure

```toml
# {framework-name}.toml

[metadata]
name = "my-framework"
display_name = "My Compliance Framework"
version = "1.0.0"
spec_version = "v2025.1"
description = "Description of this framework"
url = "https://example.com/framework"

[defaults]
check_adapter = "builtin"
remediation_adapter = "builtin"

[adapters.builtin]
type = "python"
module = "my_framework.adapters.builtin"
class = "MyCheckAdapter"

[controls."CTRL-001"]
name = "ControlName"
level = 1
domain = "DOMAIN"
description = "What this control checks"
tags = ["tag1", "tag2"]
security_severity = 7.5
docs_url = "https://example.com/docs/CTRL-001"

[controls."CTRL-001".passes]
deterministic = { file_must_exist = ["README.md"] }

[controls."CTRL-001".remediation]
handler = "create_readme"
safe = true
```

### Metadata Section

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique identifier for the framework |
| `display_name` | string | Yes | Human-readable name |
| `version` | string | Yes | Semantic version of the framework |
| `spec_version` | string | No | Version of the spec this implements |
| `description` | string | No | Brief description |
| `url` | string | No | Link to framework documentation |

### Defaults Section

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `check_adapter` | string | `"builtin"` | Default adapter for running checks |
| `remediation_adapter` | string | `"builtin"` | Default adapter for remediations |

### Adapter Section

Adapters define how checks and remediations are executed.

```toml
[adapters.builtin]
type = "python"
module = "my_framework.adapters.builtin"
class = "MyCheckAdapter"

[adapters.kusari]
type = "command"
command = "kusari"
output_format = "json"

[adapters.custom_script]
type = "script"
command = "./scripts/check.sh"
output_format = "json"
```

| Adapter Type | Description |
|--------------|-------------|
| `python` | Python module with CheckAdapter class |
| `command` | External CLI tool |
| `script` | Shell script |

> **Security Note**: Python adapter modules are validated against a whitelist before loading.
> Only modules with these prefixes can be loaded: `darnit.*`, `darnit_baseline.*`, `darnit_plugins.*`, `darnit_testchecks.*`.
> To use custom adapters, name your package with the `darnit_` prefix (e.g., `darnit_mycompany`).
> See [SECURITY_GUIDE.md](SECURITY_GUIDE.md) for details.

### Control Section

Each control is defined under `[controls."CONTROL-ID"]`:

```toml
[controls."CTRL-001"]
name = "ControlName"           # Required: Human-readable name
level = 1                      # Required: Maturity level (1, 2, or 3)
domain = "SEC"                 # Required: Domain code
description = "..."            # Required: What this control checks
tags = ["security"]            # Optional: Categorization tags
security_severity = 7.5        # Optional: CVSS-like severity (0-10)
docs_url = "https://..."       # Optional: Link to documentation
```

### Verification Passes

Controls define verification passes that determine compliance:

#### Deterministic Pass

File existence and API checks:

```toml
[controls."CTRL-001".passes]
# Check if any of these files exist
deterministic = { file_must_exist = [
    "README.md",
    "README.rst",
    "README.txt",
]}

# Or check via API
deterministic = { api_check = "check_branch_protection" }
```

#### Pattern Pass

Regex pattern matching in files:

```toml
[controls."CTRL-002".passes.pattern]
files = ["**/*.py", "**/*.js"]    # Glob patterns for files to check
pass_if_any = false               # true = pass if pattern found, false = fail if found

[controls."CTRL-002".passes.pattern.patterns]
todo_comment = "#\\s*TODO"        # Named patterns to search for
fixme_comment = "#\\s*FIXME"
```

**Pattern Pass Modes:**
- `pass_if_any = true`: Control passes if ANY pattern is found (detecting required content)
- `pass_if_any = false`: Control passes if NO patterns are found (detecting violations)

#### Manual Pass

For controls requiring human verification:

```toml
[controls."CTRL-003".passes]
manual = { steps = [
    "Navigate to Settings → Security",
    "Verify MFA is enabled for all users",
    "Check that SSO is configured",
]}
```

### Remediation Section

Define automated fixes for controls:

```toml
[controls."CTRL-001".remediation]
handler = "create_readme"         # Function/method name in adapter
safe = true                       # Safe to run without confirmation
requires_api = false              # Requires API access (not just local)
template = "standard"             # Optional: template name for generation

# Or with additional config
[controls."CTRL-001".remediation]
handler = "enable_branch_protection"
config = { required_approvals = 1 }
requires_api = true
```

## User Configuration Format

Users customize framework behavior via `.baseline.toml` in their repository root.

### Basic Structure

```toml
# .baseline.toml
version = "1.0"
extends = "openssf-baseline"

[settings]
cache_results = true
cache_ttl = 300
timeout = 300

[controls."OSPS-AC-01.01"]
status = "n/a"
reason = "MFA handled at organization level"

[controls."OSPS-VM-05.02"]
check = { adapter = "kusari" }
```

### Settings Section

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `cache_results` | bool | `true` | Cache check results |
| `cache_ttl` | int | `300` | Cache time-to-live in seconds |
| `timeout` | int | `300` | Default operation timeout |
| `fail_on_error` | bool | `false` | Fail audit if any check errors |
| `parallel_checks` | bool | `true` | Run independent checks in parallel |
| `max_parallel` | int | `5` | Maximum parallel operations |

### Control Overrides

#### Marking Controls as Not Applicable

```toml
[controls."CTRL-001"]
status = "n/a"
reason = "This control doesn't apply because..."

[controls."CTRL-002"]
status = "disabled"
reason = "Temporarily disabled for migration"
```

**Status Values:**
- `n/a` - Control is not applicable to this project
- `disabled` - Control is explicitly disabled
- `enabled` - Control is explicitly enabled (default)

#### Using Different Adapters

```toml
# Use a different check adapter
[controls."OSPS-VM-05.02"]
check = { adapter = "kusari" }

# With additional configuration
[controls."OSPS-VM-05.02"]
check = { adapter = "kusari", config = { severity = "high" } }
```

#### Custom Adapter Definitions

```toml
[adapters.kusari]
type = "command"
command = "kusari"
output_format = "json"

[adapters.my_scanner]
type = "python"
module = "my_company.security.scanner"

[adapters.custom_script]
type = "script"
command = "./scripts/check-compliance.sh"
output_format = "json"
```

### Control Groups

Apply configuration to multiple controls at once:

```toml
[control_groups.vulnerability-scanning]
controls = ["OSPS-VM-05.02", "OSPS-VM-05.03"]
check = { adapter = "kusari" }
config = { severity_threshold = "medium" }
```

### Custom Controls

Define project-specific controls:

```toml
[controls."CUSTOM-SEC-01"]
name = "InternalSecurityReview"
level = 1
domain = "SA"
description = "Require internal security review sign-off"
check = { adapter = "custom_script" }
```

## Configuration Merge Semantics

When framework and user configurations are merged:

1. **Scalar values**: User overrides framework
2. **Objects/dicts**: Deep merge (user keys override, framework keys preserved)
3. **Arrays/lists**: User replaces framework entirely
4. **Special keys**:
   - `status = "n/a"` → Marks control as not applicable
   - `check = {...}` → Replaces entire check configuration
   - `extends = "..."` → Specifies base framework

### Example Merge

```toml
# Framework: openssf-baseline.toml
[controls."OSPS-VM-05.02"]
name = "PreReleaseSCA"
level = 3
check = { adapter = "builtin", handler = "check_sca_workflow" }
remediation = { handler = "add_dependency_review" }

# User: .baseline.toml
[controls."OSPS-VM-05.02"]
check = { adapter = "kusari" }

# Effective (merged):
[controls."OSPS-VM-05.02"]
name = "PreReleaseSCA"                              # from framework
level = 3                                            # from framework
check = { adapter = "kusari" }                       # user override
remediation = { handler = "add_dependency_review" }  # from framework
```

## Creating a Custom Framework

### 1. Package Structure

```
my-framework/
├── myframework.toml           # Framework definition
├── pyproject.toml             # Python package config
├── README.md
└── src/my_framework/
    ├── __init__.py            # Exports get_framework_path()
    └── adapters/
        ├── __init__.py
        └── builtin.py         # Check implementations
```

### 2. Framework Definition

Create `myframework.toml`:

```toml
[metadata]
name = "myframework"
display_name = "My Compliance Framework"
version = "1.0.0"
description = "Custom compliance checks"

[defaults]
check_adapter = "builtin"

[adapters.builtin]
type = "python"
module = "my_framework.adapters.builtin"

[controls."MY-001"]
name = "HasReadme"
level = 1
domain = "DOC"
description = "Repository must have a README"

[controls."MY-001".passes]
deterministic = { file_must_exist = ["README.md", "README.rst"] }
```

### 3. Package Init

Create `src/my_framework/__init__.py`:

```python
from pathlib import Path

__version__ = "1.0.0"

def get_framework_path() -> Path:
    """Return path to framework TOML file."""
    return Path(__file__).parent.parent.parent / "myframework.toml"
```

### 4. Check Adapter

Create `src/my_framework/adapters/builtin.py`:

```python
from pathlib import Path
from typing import Any, Dict, List

from darnit.core.adapters import CheckAdapter
from darnit.core.models import AdapterCapability, CheckResult, CheckStatus


class MyCheckAdapter(CheckAdapter):
    """Check adapter for My Framework."""

    def name(self) -> str:
        return "myframework"

    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            control_ids={"MY-001", "MY-002"},
            supports_batch=True,
        )

    def check(
        self,
        control_id: str,
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
    ) -> CheckResult:
        if control_id == "MY-001":
            return self._check_readme(local_path)
        # ... other controls
        return CheckResult(
            control_id=control_id,
            status=CheckStatus.ERROR,
            message=f"Unknown control: {control_id}",
            level=1,
            source="myframework",
        )

    def _check_readme(self, local_path: str) -> CheckResult:
        repo = Path(local_path)
        for name in ["README.md", "README.rst", "README.txt"]:
            if (repo / name).exists():
                return CheckResult(
                    control_id="MY-001",
                    status=CheckStatus.PASS,
                    message=f"Found {name}",
                    level=1,
                    source="myframework",
                )
        return CheckResult(
            control_id="MY-001",
            status=CheckStatus.FAIL,
            message="No README found",
            level=1,
            source="myframework",
        )

    def check_batch(
        self,
        control_ids: List[str],
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
    ) -> List[CheckResult]:
        return [
            self.check(cid, owner, repo, local_path, config)
            for cid in control_ids
        ]
```

### 5. Package Configuration

Create `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "my-framework"
version = "1.0.0"
dependencies = ["darnit>=0.1.0"]

[project.entry-points."darnit.frameworks"]
myframework = "my_framework:get_framework_path"

[project.entry-points."darnit.adapters"]
myframework = "my_framework.adapters.builtin:MyCheckAdapter"
```

### 6. Usage

```python
from darnit.config.merger import load_framework_config, load_effective_config
from my_framework import get_framework_path
from my_framework.adapters import MyCheckAdapter

# Load framework
framework = load_framework_config(get_framework_path())
print(f"Loaded {len(framework.controls)} controls")

# Run checks
adapter = MyCheckAdapter()
result = adapter.check("MY-001", "", "", "/path/to/repo", {})
print(f"{result.control_id}: {result.status.value}")
```

## API Reference

### Loading Configuration

```python
from darnit.config.merger import (
    load_framework_config,
    load_user_config,
    load_effective_config,
    merge_configs,
)

# Load framework from TOML
framework = load_framework_config(Path("framework.toml"))

# Load user config from repository
user_config = load_user_config(Path("/path/to/repo"))

# Load and merge both
effective = load_effective_config(
    framework_path=Path("framework.toml"),
    repo_path=Path("/path/to/repo"),
)

# Or merge manually
effective = merge_configs(framework, user_config)
```

### Working with Effective Config

```python
# Get controls by level
level1_controls = effective.get_controls_by_level(1)

# Get controls by domain
security_controls = effective.get_controls_by_domain("SEC")

# Get excluded (n/a) controls with reasons
excluded = effective.get_excluded_controls()
for control_id, reason in excluded.items():
    print(f"{control_id}: {reason}")

# Check if control is applicable
ctrl = effective.controls["CTRL-001"]
if ctrl.is_applicable():
    # Run check
    pass
```

### Check Adapter Interface

```python
from darnit.core.adapters import CheckAdapter
from darnit.core.models import AdapterCapability, CheckResult, CheckStatus

class MyAdapter(CheckAdapter):
    def name(self) -> str:
        """Return adapter identifier."""
        return "myadapter"

    def capabilities(self) -> AdapterCapability:
        """Return supported controls and features."""
        return AdapterCapability(
            control_ids={"CTRL-001", "CTRL-002"},
            supports_batch=True,
        )

    def check(
        self,
        control_id: str,
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
    ) -> CheckResult:
        """Run check for a single control."""
        # Implementation
        return CheckResult(
            control_id=control_id,
            status=CheckStatus.PASS,
            message="Check passed",
            level=1,
            source=self.name(),
        )

    def check_batch(
        self,
        control_ids: List[str],
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
    ) -> List[CheckResult]:
        """Run checks for multiple controls."""
        return [self.check(cid, owner, repo, local_path, config) for cid in control_ids]
```

### Remediation Adapter Interface

```python
from darnit.core.adapters import RemediationAdapter
from darnit.core.models import RemediationResult

class MyRemediationAdapter(RemediationAdapter):
    def name(self) -> str:
        return "myadapter"

    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            control_ids={"CTRL-001"},
            supports_batch=False,
        )

    def remediate(
        self,
        control_id: str,
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
        dry_run: bool = True,
    ) -> RemediationResult:
        """Apply remediation for a control."""
        if dry_run:
            return RemediationResult(
                control_id=control_id,
                success=True,
                message="Would create README.md",
                changes_made=[],
                source=self.name(),
            )

        # Apply actual changes
        Path(local_path, "README.md").write_text("# Project\n")
        return RemediationResult(
            control_id=control_id,
            success=True,
            message="Created README.md",
            changes_made=["README.md"],
            source=self.name(),
        )
```

## Plugin System

The darnit plugin system enables cross-package adapter sharing. Any installed package can provide adapters that can be used by any framework.

### Entry Point Groups

| Entry Point Group | Purpose | Example |
|-------------------|---------|---------|
| `darnit.frameworks` | Framework TOML providers | `openssf-baseline = "darnit_baseline:get_framework_path"` |
| `darnit.check_adapters` | Check adapter classes | `kusari = "darnit_plugins.adapters.kusari:KusariCheckAdapter"` |
| `darnit.remediation_adapters` | Remediation adapter classes | `github-api = "darnit_plugins.adapters:GitHubRemediationAdapter"` |

### Using Adapters from Other Packages

Once an adapter package is installed, any framework can reference its adapters by name:

```toml
# In your framework.toml or .baseline.toml
[controls."OSPS-VM-05.02"]
check = { adapter = "kusari" }  # Uses kusari from darnit-plugins

[controls."OSPS-SA-03.01"]
check = { adapter = "trivy" }   # Uses trivy from another plugin package
```

### Adapter Resolution Order

When you reference an adapter by name, darnit resolves it in this order:

1. **Explicit module path** - If the config specifies `type = "python"` with a `module`
2. **Local config** - `[adapters.name]` section in the same TOML file
3. **Entry points** - `darnit.check_adapters` entry points from installed packages
4. **Fallback** - Uses framework's default "builtin" adapter

### Creating a Plugin Package

1. **Create adapters:**

```python
# my_plugins/adapters/scanner.py
from darnit.core.adapters import CheckAdapter
from darnit.core.models import AdapterCapability, CheckResult, CheckStatus

class MyScanner(CheckAdapter):
    def name(self) -> str:
        return "my-scanner"

    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            control_ids={"MY-CTRL-*"},  # Supports wildcard patterns
            supports_batch=True,
        )

    def check(self, control_id, owner, repo, local_path, config) -> CheckResult:
        # Your check logic here
        return CheckResult(
            control_id=control_id,
            status=CheckStatus.PASS,
            message="Check passed",
            level=1,
            source="my-scanner",
        )
```

2. **Register via entry points:**

```toml
# pyproject.toml
[project.entry-points."darnit.check_adapters"]
my-scanner = "my_plugins.adapters.scanner:MyScanner"
```

3. **Use in any framework:**

```toml
# .baseline.toml
[controls."MY-CTRL-01"]
check = { adapter = "my-scanner" }
```

### Using the Plugin Registry Programmatically

```python
from darnit.core import get_plugin_registry

# Get registry and discover plugins
registry = get_plugin_registry()
registry.discover_all()

# List what's available
print("Frameworks:", registry.list_frameworks())
print("Check adapters:", registry.list_check_adapters())

# Get an adapter by name
adapter = registry.get_check_adapter("kusari")
if adapter:
    result = adapter.check("CTRL-001", "", "", "/path/to/repo", {})

# Get plugin summary
summary = registry.get_plugin_summary()
print(f"Found {summary['counts']['check_adapters']} check adapters")
```

### Example: darnit-plugins Package

The `darnit-plugins` package demonstrates the plugin pattern:

```
darnit-plugins/
├── pyproject.toml              # Entry point registration
├── src/darnit_plugins/
│   └── adapters/
│       ├── kusari.py           # Kusari CLI wrapper
│       └── echo.py             # Simple testing adapter
```

Entry points in `pyproject.toml`:
```toml
[project.entry-points."darnit.check_adapters"]
kusari = "darnit_plugins.adapters.kusari:KusariCheckAdapter"
echo = "darnit_plugins.adapters.echo:EchoCheckAdapter"
```

## Examples

### Example: OpenSSF Baseline Framework

See `packages/darnit-baseline/openssf-baseline.toml` for a production framework with 47 controls.

### Example: Test Checks Framework

See `packages/darnit-testchecks/` for a minimal example framework with:
- 12 controls across 3 levels
- File existence checks
- Pattern matching checks
- Remediation implementations
- Complete test suite

### Example: User Configuration

```toml
# .baseline.toml - Real-world example
version = "1.0"
extends = "openssf-baseline"

[settings]
cache_results = true
timeout = 600

# Use Kusari for dependency scanning
[adapters.kusari]
type = "command"
command = "kusari"
output_format = "json"

# Skip MFA check - handled at org level
[controls."OSPS-AC-01.01"]
status = "n/a"
reason = "MFA enforced via SSO at organization level"

# Skip release-related controls for pre-1.0 project
[controls."OSPS-BR-02.01"]
status = "n/a"
reason = "Pre-1.0 project, no releases yet"

[controls."OSPS-LE-02.02"]
status = "n/a"
reason = "Pre-1.0 project, no releases yet"

# Use Kusari for SCA controls
[control_groups.sca]
controls = ["OSPS-VM-05.02", "OSPS-VM-05.03"]
check = { adapter = "kusari" }
```

## MCP Server Integration

Darnit frameworks can be exposed via MCP (Model Context Protocol) servers for integration with AI assistants like Claude Code, Cursor, and others.

### Claude Code Configuration

Add a darnit-based MCP server to Claude Code by editing your settings:

**Global configuration** (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "darnit": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/baseline-mcp", "python", "main.py"]
    }
  }
}
```

**Project-specific configuration** (`.claude/settings.json` in your repo):

```json
{
  "mcpServers": {
    "openssf-baseline": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/baseline-mcp", "python", "main.py"]
    }
  }
}
```

### Creating a Custom MCP Server

To expose your own framework via MCP:

#### 1. Create the Server Entry Point

```python
# my_framework_mcp/main.py
"""MCP server for My Compliance Framework."""

from mcp.server.fastmcp import FastMCP
from pathlib import Path
from typing import Optional
import json

from darnit.core import get_plugin_registry
from darnit.core.models import CheckStatus
from darnit.config.merger import (
    load_effective_config_by_name,
    load_effective_config,
)

# Create MCP server
mcp = FastMCP("My Compliance Framework")


@mcp.tool()
def audit_my_framework(
    local_path: str = ".",
    level: int = 3,
    output_format: str = "markdown",
) -> str:
    """
    Run compliance audit against My Framework.

    Args:
        local_path: Path to the repository to audit
        level: Maximum maturity level to check (1, 2, or 3)
        output_format: Output format (markdown, json, sarif)

    Returns:
        Formatted audit report
    """
    # Discover plugins
    registry = get_plugin_registry()
    registry.discover_all()

    # Load framework + user overrides
    config = load_effective_config_by_name(
        framework_name="my-framework",
        repo_path=Path(local_path),
    )

    # Get adapter and run checks
    results = []
    for control_id, control in config.controls.items():
        if control.level > level:
            continue

        adapter_name = config.get_check_adapter(control_id)
        adapter = registry.get_check_adapter(adapter_name)

        if adapter:
            result = adapter.check(
                control_id=control_id,
                owner="",
                repo="",
                local_path=local_path,
                config=control.check.config if control.check else {},
            )
            results.append(result)

    # Format output
    if output_format == "json":
        return json.dumps([r.to_dict() for r in results], indent=2)

    # Default: markdown
    passed = sum(1 for r in results if r.status == CheckStatus.PASS)
    total = len(results)

    lines = [
        f"# My Framework Audit Results",
        f"",
        f"**Compliance**: {passed}/{total} controls passed",
        f"",
        "## Results",
        "",
    ]

    for result in results:
        status_emoji = "✅" if result.status == CheckStatus.PASS else "❌"
        lines.append(f"- {status_emoji} **{result.control_id}**: {result.message}")

    return "\n".join(lines)


@mcp.tool()
def list_my_framework_controls() -> str:
    """List all controls in My Framework."""
    registry = get_plugin_registry()
    registry.discover_all()

    config = load_effective_config_by_name("my-framework", None)

    controls = []
    for control_id, control in sorted(config.controls.items()):
        controls.append({
            "id": control_id,
            "name": control.name,
            "level": control.level,
            "domain": control.domain,
        })

    return json.dumps(controls, indent=2)


if __name__ == "__main__":
    mcp.run()
```

#### 2. Package Configuration

```toml
# pyproject.toml
[project]
name = "my-framework-mcp"
version = "0.1.0"
dependencies = [
    "darnit",
    "my-framework",  # Your framework package
    "mcp",
]

[project.scripts]
my-framework-mcp = "my_framework_mcp.main:mcp.run"
```

#### 3. Register with Claude Code

```json
{
  "mcpServers": {
    "my-framework": {
      "command": "uvx",
      "args": ["my-framework-mcp"]
    }
  }
}
```

Or for local development:

```json
{
  "mcpServers": {
    "my-framework": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/my-framework-mcp", "python", "main.py"]
    }
  }
}
```

### MCP Tools Best Practices

When creating MCP tools for your framework:

1. **Use descriptive docstrings** - These become the tool descriptions visible to AI assistants

2. **Provide sensible defaults** - Most parameters should have reasonable defaults

3. **Return structured output** - Use markdown for human-readable output, JSON for structured data

4. **Handle errors gracefully** - Return error messages rather than raising exceptions

5. **Support dry-run modes** - For remediation tools, always support previewing changes

6. **Auto-detect context** - Detect owner/repo from git when not provided

### Example: Multi-Framework Server

You can expose multiple frameworks from a single MCP server:

```python
from mcp.server.fastmcp import FastMCP
from darnit.core import get_plugin_registry

mcp = FastMCP("Multi-Framework Compliance Server")

@mcp.tool()
def audit(
    framework: str = "openssf-baseline",
    local_path: str = ".",
) -> str:
    """
    Run compliance audit.

    Args:
        framework: Framework to audit against (openssf-baseline, my-framework, etc.)
        local_path: Path to repository
    """
    registry = get_plugin_registry()
    registry.discover_all()

    available = registry.list_frameworks()
    if framework not in available:
        return f"Unknown framework: {framework}. Available: {', '.join(available)}"

    # ... run audit ...

@mcp.tool()
def list_frameworks() -> str:
    """List available compliance frameworks."""
    registry = get_plugin_registry()
    registry.discover_all()
    return json.dumps(registry.list_frameworks(), indent=2)
```

## Future: Shared Execution Context

> **Status**: Planned enhancement. See TODOs in source code.

Currently, each control check runs independently. A future enhancement will enable tools like OpenSSF Scorecard to run once and provide results for multiple controls.

### Proposed Design

```toml
# Adapter declares it supports caching
[adapters.scorecard]
type = "command"
command = "scorecard"
cache_key = "scorecard"      # Results cached under this key
batch_controls = true        # Single run serves multiple controls

# Multiple controls extract from the same cached result
[controls."OSPS-AC-03.01"]
check = { adapter = "scorecard", extract = "checks.BranchProtection" }

[controls."OSPS-QA-02.01"]
check = { adapter = "scorecard", extract = "checks.CITests" }

[controls."OSPS-QA-03.01"]
check = { adapter = "scorecard", extract = "checks.CI-Tests" }
```

### Implementation Locations

TODOs have been added to track this enhancement:

| File | Component | Description |
|------|-----------|-------------|
| `darnit/core/adapters.py` | `CheckAdapter` class | Add `ExecutionContext` parameter |
| `darnit/core/adapters.py` | `check_batch()` method | Shared result caching pattern |
| `darnit/core/models.py` | `ExecutionContext` class | New class definition (commented) |
| `darnit/config/framework_schema.py` | `CheckConfig` | Add `extract` field |
| `darnit/config/framework_schema.py` | `CommandAdapterConfig` | Add `cache_key`, `batch_controls` |

### Workaround for Now

Adapters can implement internal caching:

```python
class ScorecardAdapter(CheckAdapter):
    _cached_result = None
    _cached_path = None

    def check(self, control_id, owner, repo, local_path, config):
        # Cache scorecard run per repo path
        if self._cached_path != local_path:
            self._cached_result = self._run_scorecard(local_path)
            self._cached_path = local_path

        return self._extract_control(control_id, self._cached_result)
```

## Troubleshooting

### Common Issues

**TOML Syntax Errors**

Multi-line inline tables are not valid TOML:
```toml
# WRONG
pattern = {
    files = ["*.py"],
    patterns = { todo = "TODO" },
}

# CORRECT
[controls."CTRL-001".passes.pattern]
files = ["*.py"]

[controls."CTRL-001".passes.pattern.patterns]
todo = "TODO"
```

**Framework Not Found**

Ensure `get_framework_path()` returns the correct path:
```python
def get_framework_path() -> Path:
    # Path relative to package location
    return Path(__file__).parent.parent.parent / "framework.toml"
```

**Adapter Not Recognized**

Check entry points in `pyproject.toml`:
```toml
[project.entry-points."darnit.frameworks"]
myframework = "my_framework:get_framework_path"

[project.entry-points."darnit.adapters"]
myframework = "my_framework.adapters:MyAdapter"
```

### Debug Mode

Enable debug logging to troubleshoot configuration loading:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

from darnit.config.merger import load_framework_config
framework = load_framework_config(path)
```
