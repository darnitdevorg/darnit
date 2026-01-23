# Framework Implementation Examples

This directory contains two implementations of the same example compliance framework,
demonstrating the difference between the **declarative TOML approach** and the
**traditional Python approach**.

## Quick Comparison

| Aspect | TOML (Declarative) | Python (Imperative) |
|--------|-------------------|---------------------|
| **Lines of Code** | ~300 lines | ~500+ lines |
| **File Count** | 1 file | 2+ files |
| **Logic Required** | None | Yes |
| **Template Variables** | Built-in (`$OWNER`, `$REPO`) | Manual |
| **Dry-run Support** | Automatic | Manual per function |
| **Adding Controls** | Add TOML section | Write check + remediation functions |
| **Maintenance** | Edit config | Edit code, test, deploy |

## Declarative TOML Approach

📁 `declarative-framework/example-framework.toml`

```toml
# A complete control definition in TOML
[controls."EXAMPLE-DO-01"]
name = "ReadmeExists"
description = "Project must have a README file"
tags = { level = 1, domain = "DO", documentation = true }

[controls."EXAMPLE-DO-01".passes]
deterministic = { file_must_exist = ["README.md", "README.rst"] }

[controls."EXAMPLE-DO-01".remediation.file_create]
path = "README.md"
template = "readme_standard"
```

**Advantages:**
- ✅ No programming required
- ✅ Easy to read and modify
- ✅ Automatic dry-run support
- ✅ Built-in variable substitution
- ✅ Templates are reusable
- ✅ Framework loads at runtime (no deployment needed)
- ✅ Flexible tags schema for custom metadata

> **Tags Schema**: The `tags` field is a flexible dictionary that can include:
> - `level`: Maturity level (1, 2, or 3) for filtering
> - `domain`: Domain code (e.g., "DO", "VM", "AC") for categorization
> - `security_severity`: CVSS-like severity score (0.0-10.0)
> - Custom boolean tags (e.g., `security = true`, `documentation = true`) for filtering

**Best for:**
- Simple file existence checks
- Pattern matching in files
- External command execution
- File creation from templates
- API calls with static payloads

## Python Approach

📁 `python-framework/example_framework/implementation.py`

```python
# The same control requires a function
def check_readme_exists(local_path: str) -> CheckResult:
    """Check EXAMPLE-DO-01: README file must exist."""
    readme_patterns = ["README.md", "README", "README.rst", "README.txt"]

    for pattern in readme_patterns:
        if os.path.exists(os.path.join(local_path, pattern)):
            return CheckResult(
                id="EXAMPLE-DO-01",
                name="ReadmeExists",
                status="PASS",
                message=f"README found: {pattern}",
                level=1,
                domain="DO",
                details={"file_found": pattern},
            )

    return CheckResult(
        id="EXAMPLE-DO-01",
        name="ReadmeExists",
        status="FAIL",
        message="No README file found",
        level=1,
        domain="DO",
        details={"searched": readme_patterns},
    )

# Plus a separate remediation function...
def create_readme(local_path: str, owner: str, repo: str, dry_run: bool = True) -> str:
    content = f"""# {repo}
    ...
    """
    # ... implementation ...
```

**Advantages:**
- ✅ Full programming power
- ✅ Complex conditional logic
- ✅ Custom data processing
- ✅ Integration with external systems
- ✅ Dynamic behavior based on context

**Best for:**
- Complex checks with conditional logic
- Data transformation and analysis
- Integration with external APIs
- Custom reporting formats
- Checks that need stateful tracking

## Hybrid Approach (Recommended)

The OpenSSF Baseline implementation uses a **hybrid approach**:

1. **TOML for simple checks**: File existence, pattern matching, API calls
2. **Python for complex checks**: Business logic, data processing, conditional flows
3. **TOML templates + Python handlers**: Best of both worlds

```toml
# TOML: Control definition with tags
[controls."OSPS-VM-02.01"]
name = "SecurityPolicyExists"
description = "Project must have a security policy"
tags = { level = 1, domain = "VM", security_severity = 7.5, security = true }

# TOML: Remediation with Python fallback
[controls."OSPS-VM-02.01".remediation]
handler = "create_security_policy"  # Python fallback
safe = true

# TOML: Declarative file creation (used first)
[controls."OSPS-VM-02.01".remediation.file_create]
path = "SECURITY.md"
template = "security_policy_standard"
```

The system tries declarative first, then falls back to Python handlers.

## How to Choose

Use **TOML** when:
- The check is a simple file/pattern existence
- The remediation creates a file from a template
- The API call has a static payload
- You want easy customization by users

Use **Python** when:
- The check has complex conditional logic
- You need to process or transform data
- The remediation requires dynamic decisions
- You need to integrate with external systems
- Error handling is complex

## File Structure

```
examples/
├── README.md                              # This file
├── declarative-framework/
│   └── example-framework.toml             # Pure TOML implementation
└── python-framework/
    └── example_framework/
        ├── __init__.py                    # Package init + register()
        └── implementation.py              # Full Python implementation
```

## Running the Examples

The declarative framework can be loaded by darnit if added to entry points:

```toml
# pyproject.toml
[project.entry-points."darnit.frameworks"]
example-framework = "example_package:get_framework_path"
```

The Python framework follows the same pattern:

```toml
# pyproject.toml
[project.entry-points."darnit.implementations"]
example-framework = "example_framework:register"
```

## Variable Substitution

Both approaches support these variables (TOML gets them automatically):

| Variable | Description | Example |
|----------|-------------|---------|
| `$OWNER` | Repository owner/org | `myorg` |
| `$REPO` | Repository name | `myproject` |
| `$BRANCH` | Default branch | `main` |
| `$PATH` | Local repo path | `/home/user/myproject` |
| `$YEAR` | Current year | `2024` |
| `$DATE` | Current date (ISO) | `2024-01-15` |
| `$CONTROL` | Control ID | `EXAMPLE-DO-01` |

## Migration Guide

To migrate from Python to TOML:

1. **Identify simple checks**: File existence, pattern matching
2. **Create templates**: Extract content generation to templates
3. **Add TOML controls**: Define checks declaratively
4. **Keep Python handlers**: For complex logic that can't be expressed in TOML
5. **Test both paths**: Verify declarative matches Python behavior

The system automatically falls back to Python when TOML doesn't have
a declarative remediation defined.
