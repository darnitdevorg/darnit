# Testing Guide

This guide covers how to run tests, understand the test structure, and add new tests.

## Running Tests

### All tests (excluding integration)

```bash
uv run pytest tests/ --ignore=tests/integration/ -q
```

### Framework tests only

```bash
uv run pytest tests/darnit/ -v
```

### Implementation tests only

```bash
uv run pytest tests/darnit_baseline/ -v
```

### A specific test file

```bash
uv run pytest tests/darnit/sieve/test_orchestrator.py -v
```

### A specific test function

```bash
uv run pytest tests/darnit/sieve/test_orchestrator.py::test_deterministic_pass -v
```

### Integration tests

Integration tests require GitHub API access (`gh auth login`) and network connectivity:

```bash
uv run pytest tests/integration/ -v
```

These are excluded from the default test run because they're slower and require external access.

## Test Structure

```
tests/
├── darnit/                      # Framework tests
│   ├── core/                    # Plugin system, discovery
│   ├── sieve/                   # Sieve pipeline, handlers, orchestrator
│   ├── config/                  # Configuration loading
│   └── tools/                   # MCP tool tests
│
├── darnit_baseline/             # Implementation tests
│   ├── controls/                # Control definition tests
│   ├── formatters/              # Output formatting tests
│   └── remediation/             # Remediation tests
│
└── integration/                 # End-to-end tests (require network)
```

**Convention**: Test file names mirror source file names with a `test_` prefix. For example:
- `packages/darnit/src/darnit/sieve/orchestrator.py` → `tests/darnit/sieve/test_orchestrator.py`

## What to Test

### When modifying the framework (`packages/darnit/`)

- **Sieve handlers**: Test PASS, FAIL, INCONCLUSIVE, and ERROR outcomes
- **Orchestrator**: Test phase ordering, early termination, evidence propagation
- **Plugin discovery**: Test entry point loading, missing implementations, graceful degradation
- **CEL evaluation**: Test expression evaluation with various context variables
- **Configuration**: Test TOML parsing, config merging, validation

### When modifying an implementation (`packages/darnit-baseline/`)

- **Control definitions**: Verify controls load from TOML correctly
- **Remediation**: Test dry-run and actual execution paths
- **Formatters**: Test output in each format (Markdown, JSON, SARIF)
- **Custom handlers**: Test handler logic with mocked contexts

## Writing a New Test

### Basic test structure

```python
"""Tests for my_module."""

import pytest
from darnit.sieve.handler_registry import HandlerContext, HandlerResult, HandlerResultStatus


def test_handler_passes_when_file_exists(tmp_path):
    """Handler should return PASS when the expected file exists."""
    # Arrange
    (tmp_path / "README.md").write_text("# My Project")
    context = HandlerContext(
        local_path=str(tmp_path),
        owner="test-org",
        repo="test-repo",
        default_branch="main",
        control_id="TEST-01",
        project_context={},
        gathered_evidence={},
        shared_cache={},
        dependency_results={},
    )
    config = {"files": ["README.md"]}

    # Act
    result = my_handler(config, context)

    # Assert
    assert result.status == HandlerResultStatus.PASS
    assert result.confidence == 1.0


def test_handler_returns_inconclusive_when_no_files(tmp_path):
    """Handler should return INCONCLUSIVE when no files to check."""
    context = HandlerContext(
        local_path=str(tmp_path),
        owner="test-org",
        repo="test-repo",
        default_branch="main",
        control_id="TEST-01",
        project_context={},
        gathered_evidence={},
        shared_cache={},
        dependency_results={},
    )
    config = {"files": []}

    result = my_handler(config, context)

    assert result.status == HandlerResultStatus.INCONCLUSIVE
```

### Using pytest fixtures

The project uses `tmp_path` (built-in pytest fixture) for filesystem tests. For tests needing a mock repository structure:

```python
@pytest.fixture
def mock_repo(tmp_path):
    """Create a minimal repository structure."""
    (tmp_path / "README.md").write_text("# Test Project")
    (tmp_path / "SECURITY.md").write_text("# Security Policy")
    (tmp_path / ".github").mkdir()
    return tmp_path
```

### Testing CEL expressions

```python
from darnit.sieve.cel_evaluator import evaluate_cel

def test_cel_expression_with_json_output():
    context = {
        "output": {
            "json": {"enabled": True},
            "exit_code": 0,
        }
    }
    result = evaluate_cel('output.json.enabled == true', context)
    assert result is True
```

## Test Conventions

- Use descriptive test names: `test_<what>_<when>_<expected>`
- One assertion per test when practical
- Use `tmp_path` for filesystem operations (auto-cleaned up)
- Mock external services (GitHub API, network calls)
- Keep tests fast — no network calls in unit tests

## Next Steps

- [Development Workflow](development-workflow.md) — Pre-commit checklist
- [Framework Development](framework-development.md) — Understanding the codebase
- Back to [Getting Started](README.md)
