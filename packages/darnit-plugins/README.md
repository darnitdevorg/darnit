# darnit-plugins

Reusable adapters for darnit compliance frameworks.

## Overview

This package provides check and remediation adapters that can be used by any darnit-compatible compliance framework. Adapters are discovered automatically via Python entry points.

## Installation

```bash
pip install darnit-plugins
```

## Available Adapters

### Check Adapters

| Adapter | Description | Entry Point |
|---------|-------------|-------------|
| `kusari` | Wrapper for Kusari SBOM/SCA CLI tool | `darnit.check_adapters` |
| `echo` | Simple echo adapter for testing | `darnit.check_adapters` |

## Usage

### In Framework TOML

Reference adapters by name in your framework definition:

```toml
# myframework.toml
[controls."CTRL-SCA-01"]
name = "DependencyScanning"
level = 2
domain = "SCA"
description = "Scan dependencies for vulnerabilities"
check = { adapter = "kusari" }

[controls."CTRL-TEST-01"]
name = "TestControl"
level = 1
domain = "TEST"
description = "Test control using echo adapter"
check = { adapter = "echo", config = { status = "PASS" } }
```

### In User Config (.baseline.toml)

Override framework adapters with plugins:

```toml
# .baseline.toml
extends = "openssf-baseline"

[controls."OSPS-VM-05.02"]
check = { adapter = "kusari" }
```

### Programmatic Usage

```python
from darnit.core import get_plugin_registry

# Get registry and discover plugins
registry = get_plugin_registry()
registry.discover_all()

# List available adapters
print(registry.list_check_adapters())
# ['echo', 'kusari', ...]

# Get adapter by name
adapter = registry.get_check_adapter("kusari")
result = adapter.check(
    control_id="OSPS-VM-05.02",
    owner="myorg",
    repo="myrepo",
    local_path="/path/to/repo",
    config={"severity": "high"},
)

print(f"Status: {result.status}")
```

## Creating Custom Adapters

### 1. Implement the Adapter Interface

```python
# my_company/adapters/scanner.py
from darnit.core.adapters import CheckAdapter
from darnit.core.models import AdapterCapability, CheckResult, CheckStatus

class MyScanner(CheckAdapter):
    def name(self) -> str:
        return "my-scanner"

    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            control_ids={"MY-CTRL-01", "MY-CTRL-02"},
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

### 2. Register via Entry Points

```toml
# pyproject.toml
[project.entry-points."darnit.check_adapters"]
my-scanner = "my_company.adapters.scanner:MyScanner"
```

### 3. Use in Framework Config

```toml
# framework.toml
[controls."MY-CTRL-01"]
check = { adapter = "my-scanner" }
```

## Adapter Reference

### KusariCheckAdapter

Wrapper for the [Kusari](https://github.com/kusaridev/kusari) SBOM/SCA tool.

**Supported Controls:**
- `OSPS-VM-05.02` - Pre-release SCA
- `OSPS-VM-05.03` - Known vulnerabilities
- `OSPS-BR-01.02` - SBOM generation
- `*-SCA-*` - Any SCA-related control
- `*-SBOM-*` - Any SBOM-related control

**Configuration:**
```toml
[controls."OSPS-VM-05.02"]
check = { adapter = "kusari", config = { severity = "high" } }
```

**Requirements:**
```bash
pip install kusari  # or brew install kusari
```

### EchoCheckAdapter

Simple adapter that echoes back configuration as results. Useful for testing.

**Configuration:**
```toml
[controls."TEST-001"]
check = { adapter = "echo", config = { status = "PASS", message = "Test passed" } }
```

**Options:**
- `status`: Return status (PASS, FAIL, ERROR, SKIP, MANUAL)
- `message`: Result message
- `delay`: Seconds to sleep (for timeout testing)
- `level`: Control level (1, 2, 3)

## Entry Point Groups

| Group | Purpose |
|-------|---------|
| `darnit.check_adapters` | Check adapter classes |
| `darnit.remediation_adapters` | Remediation adapter classes |
| `darnit.frameworks` | Framework TOML providers |

## License

Apache-2.0
