# darnit

Generic compliance audit framework with plugin architecture.

## Overview

**darnit** is the core framework that provides:

- **Plugin System**: Discover and load compliance implementations via Python entry points
- **Configuration Management**: `.project.yaml` for project metadata and file locations
- **Progressive Verification**: "Sieve" model for efficient compliance checking
- **Remediation Framework**: Auto-fix infrastructure for compliance gaps
- **MCP Server Tools**: Ready-to-use tools for AI assistant integration

## Installation

```bash
pip install darnit
```

## Usage

### Discover Implementations

```python
from darnit.core.discovery import get_default_implementation

# Get the default installed compliance implementation
impl = get_default_implementation()
if impl:
    controls = impl.get_all_controls()
```

### Configuration Management

```python
from darnit.config.loader import load_project_config, save_project_config
from darnit.config.discovery import discover_files

# Discover existing documentation files
discovered = discover_files("/path/to/repo")

# Load project configuration
config = load_project_config("/path/to/repo")
```

## Creating Implementations

To create a new compliance implementation:

1. Create a package with entry point `darnit.implementations`
2. Implement the `ComplianceImplementation` protocol
3. Register controls and checks

```toml
# pyproject.toml
[project.entry-points."darnit.implementations"]
my-standard = "my_package:register"
```

```python
# my_package/__init__.py
def register():
    from .implementation import MyImplementation
    return MyImplementation()
```

See [darnit-baseline](../darnit-baseline) for a complete example.

## Package Structure

```
darnit/
├── core/           # Plugin system, models, discovery
├── config/         # Project configuration (.project.yaml)
├── sieve/          # Progressive verification pipeline
├── remediation/    # Auto-fix framework
├── server/         # MCP server tool implementations
└── tools/          # MCP tool helpers and utilities
```

## License

Apache-2.0
