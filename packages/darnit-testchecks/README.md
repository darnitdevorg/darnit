# darnit-testchecks

A test compliance framework for [darnit](https://github.com/kusaridev/baseline-mcp) with trivial checks for testing and demonstration purposes.

## Overview

This package demonstrates how to create a custom compliance framework using the darnit declarative configuration system. It includes:

- **12 trivial controls** across 3 maturity levels
- **Declarative framework definition** in `testchecks.toml`
- **Python check implementations** in the builtin adapter
- **Simple remediations** for basic controls

## Installation

```bash
pip install darnit-testchecks
```

Or for development:

```bash
pip install -e packages/darnit-testchecks
```

## Controls

### Level 1 - Basic Project Setup

| Control ID | Name | Description |
|------------|------|-------------|
| TEST-DOC-01 | HasReadme | Repository must have a README file |
| TEST-DOC-02 | HasChangelog | Repository should have a CHANGELOG file |
| TEST-LIC-01 | HasLicense | Repository must have a LICENSE file |
| TEST-IGN-01 | HasGitignore | Repository should have a .gitignore file |

### Level 2 - Code Quality

| Control ID | Name | Description |
|------------|------|-------------|
| TEST-QA-01 | NoTodoComments | Code should not contain TODO comments |
| TEST-QA-02 | NoPrintStatements | Python code should use logging, not print() |
| TEST-CFG-01 | HasEditorConfig | Repository should have .editorconfig |
| TEST-CFG-02 | HasPreCommitConfig | Repository should have pre-commit hooks |

### Level 3 - Security & CI

| Control ID | Name | Description |
|------------|------|-------------|
| TEST-SEC-01 | NoHardcodedPasswords | No hardcoded secrets in code |
| TEST-SEC-02 | GitignoreSecrets | .gitignore excludes secret files |
| TEST-CI-01 | HasCIConfig | Repository has CI/CD configuration |
| TEST-CI-02 | CIRunsTests | CI configuration runs tests |

## Usage

### Running Checks

```python
from darnit_testchecks import get_framework_path
from darnit_testchecks.adapters import get_test_check_adapter
from darnit.config.merger import load_framework_config

# Load framework
framework = load_framework_config(get_framework_path())
print(f"Loaded {len(framework.controls)} controls")

# Run checks
adapter = get_test_check_adapter()
result = adapter.check(
    control_id="TEST-DOC-01",
    owner="",
    repo="",
    local_path="/path/to/repo",
    config={},
)
print(f"{result.control_id}: {result.status.value} - {result.message}")
```

### User Customization

Users can customize checks with `.baseline.toml`:

```toml
version = "1.0"
extends = "testchecks"

# Skip TODO check - we use TODOs in this project
[controls."TEST-QA-01"]
status = "n/a"
reason = "TODOs are acceptable in this project"

# Skip print statement check for scripts
[controls."TEST-QA-02"]
status = "n/a"
reason = "Print statements OK in CLI scripts"
```

## Creating Your Own Framework

Use this package as a template:

1. Copy the package structure
2. Edit `testchecks.toml` with your controls
3. Implement check functions in `adapters/builtin.py`
4. Update `pyproject.toml` entry points

## License

Apache-2.0
