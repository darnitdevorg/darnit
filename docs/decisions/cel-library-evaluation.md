# CEL Library Evaluation for Darnit Framework

**Date**: 2026-02-04
**Status**: Decision Made
**Decision**: Use `cel-python` (celpy) for CEL expression support

## Context

The darnit framework needs a Python library to evaluate [Common Expression Language (CEL)](https://cel.dev/) expressions for the TOML schema v2 work. CEL is a non-Turing complete expression language designed for safe execution of user-provided expressions.

## Options Evaluated

### Option 1: cel-python (celpy)

**Package**: `cel-python` on PyPI, imports as `celpy`
**Source**: [cloud-custodian/cel-python](https://github.com/cloud-custodian/cel-python)

| Attribute | Value |
|-----------|-------|
| Version | 0.5.0 (Jan 31, 2026) |
| Implementation | Pure Python |
| Python Support | >=3.10 |
| Dependencies | Minimal (optional google-re2) |
| Maintainer | Cloud Custodian project |
| Maturity | Established, production use in Cloud Custodian |

**Pros**:
- Pure Python - no native compilation required
- Minimal dependencies
- Established project with production use
- Multi-step compile/program/evaluate pattern for efficiency
- Active maintenance (recently updated)

**Cons**:
- Slower than Rust-backed option (milliseconds vs microseconds)
- google-re2 doesn't build on Python 3.13 darwin/arm64 (falls back to `re`)

### Option 2: common-expression-language

**Package**: `common-expression-language` on PyPI, imports as `cel`
**Source**: Rust wrapper using PyO3

| Attribute | Value |
|-----------|-------|
| Version | 0.5.3 (Oct 14, 2025) |
| Implementation | Rust via PyO3 |
| Python Support | >=3.11 |
| Dependencies | Rust runtime bindings |
| Spec Compliance | ~80% |
| Maturity | Newer |

**Pros**:
- Microsecond-level performance
- Pre-built wheels for many platforms

**Cons**:
- Requires Python >=3.11 (we support 3.10)
- Only 80% CEL spec compliance
- Newer project, less battle-tested
- Rust dependencies add complexity

## Decision

**Use `cel-python` (celpy)** for the following reasons:

1. **Python Version Compatibility**: We support Python 3.10+, and cel-python supports 3.10 while common-expression-language requires 3.11+.

2. **Full Spec Compliance**: cel-python aims for full CEL specification compliance, while common-expression-language is only 80% compliant.

3. **Production Maturity**: cel-python is used in production by Cloud Custodian, a major cloud security project.

4. **Pure Python**: No native compilation dependencies simplifies installation and cross-platform support.

5. **Performance is Adequate**: For compliance checks, millisecond evaluation time is acceptable. We're not evaluating millions of expressions per second.

6. **Timeout Support**: The multi-step compile/program/evaluate pattern allows us to implement timeouts around evaluation.

## Implementation Notes

### Installation
```toml
[project.dependencies]
cel-python = ">=0.5.0"
```

### Basic Usage Pattern
```python
import celpy

# 1. Create environment with declarations
env = celpy.Environment()

# 2. Compile expression (do once, cache result)
ast = env.compile("output.exit_code == 0 && size(output.stdout) > 0")

# 3. Create program
prog = env.program(ast)

# 4. Evaluate with context (do per-execution)
context = {
    "output": celpy.json_to_cel({
        "exit_code": 0,
        "stdout": "success",
        "stderr": ""
    })
}
result = prog.evaluate(context)
```

### Sandboxing Strategy

CEL is inherently sandboxed (non-Turing complete, no I/O). Additional safety:

1. **Timeout**: Wrap `prog.evaluate()` with Python timeout (1 second limit)
2. **Custom Functions**: Only expose safe functions like `file_exists()` through CEL environment
3. **Memory**: CEL expressions are bounded; combined with timeout provides adequate protection

## References

- [CEL Overview](https://cel.dev/overview/cel-overview)
- [cel-python Documentation](https://cloud-custodian.github.io/cel-python/)
- [cel-python GitHub](https://github.com/cloud-custodian/cel-python)
- [cel-python PyPI](https://pypi.org/project/cel-python/)
- [common-expression-language PyPI](https://pypi.org/project/common-expression-language/)
