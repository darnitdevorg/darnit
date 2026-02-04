# Darnit Framework Architecture

> Generated from framework specification
> Spec Version: Unknown

This document describes the architecture of the Darnit framework, including
the sieve orchestrator, plugin system, and TOML configuration schema.

---

## 1. Overview



### 1.1 Purpose

Darnit is a pluggable security and compliance auditing framework that:

1. **Orchestrates verification** through a 4-phase sieve pipeline
2. **Defines controls declaratively** via TOML configuration
3. **Supports multiple compliance frameworks** through a plugin architecture
4. **Generates standardized output** in SARIF, JSON, and Markdown formats

### 1.2 Philosophy

| Principle | Description |
|-----------|-------------|
| **Declarative First** | Most controls SHOULD be expressible in TOML without Python code |
| **Progressive Verification** | Sieve model: deterministic → pattern → LLM → manual |
| **Fail to Manual** | When uncertain, always fall back to human verification (WARN) |
| **Plugin-Optional** | Python plugins are an escape hatch for complex logic, not the default |

### 1.3 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│  DARNIT FRAMEWORK (packages/darnit)                         │
│                                                             │
│  ┌──────────────────┐  ┌─────────────────────────────────┐  │
│  │ Sieve            │  │ TOML Schema                     │  │
│  │ Orchestrator     │  │ - Control structure             │  │
│  │ (4-phase         │  │ - Built-in pass types           │  │
│  │  pipeline)       │  │ - Built-in remediation actions  │  │
│  └──────────────────┘  └─────────────────────────────────┘  │
│                                                             │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ Built-in Capabilities (declarative, no Python)         ││
│  │ - file_must_exist, exec, api_check, pattern, template  ││
│  │ - api_call, file_create (remediation)                  ││
│  └─────────────────────────────────────────────────────────┘│
│                                                             │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ Plugin Protocol (escape hatch for complex logic)       ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                         ▲
                         │ validates/executes
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  TOML CONFIG (user/AI-generated, from any source)           │
│  - Control definitions + SARIF metadata                     │
│  - Pass configs using built-in types                        │
│  - Optional Python plugin references (complex cases)        │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Sieve Orchestrator



### 5.1 Execution Model

The orchestrator runs passes sequentially, stopping at first conclusive result:

```python
for pass in control.passes:
    result = pass.execute(context)

    if result.outcome == PASS:
        return SieveResult(status="PASS", ...)
    elif result.outcome == FAIL:
        return SieveResult(status="FAIL", ...)
    elif result.outcome == ERROR:
        return SieveResult(status="ERROR", ...)
    # INCONCLUSIVE → continue to next pass

### 5.2 Result Statuses

| Status | Description | Conclusive |
|--------|-------------|------------|
| `PASS` | Control verified compliant | Yes |
| `FAIL` | Control verified non-compliant | Yes |
| `ERROR` | Check execution failed | Yes |
| `WARN` | Manual verification required | No |
| `PENDING_LLM` | Awaiting LLM consultation | No |

### 5.3 Evidence Accumulation

Evidence from each pass accumulates and is available to subsequent passes:

```python
context.gathered_evidence["api_check_result"] = {...}
context.gathered_evidence["file_found"] = "/path/to/SECURITY.md"
```

### 5.4 LLM Consultation Protocol

When an LLM pass is reached and `stop_on_llm=True`:

1. Orchestrator returns `PENDING_LLM` with consultation request
2. Calling LLM analyzes and returns `LLMConsultationResponse`
3. Orchestrator continues with `verify_with_llm_response()`

---

## 6. Plugin Protocol



### 6.1 When to Use Plugins

Plugins are appropriate when:
- Logic cannot be expressed with built-in pass types
- External tool integration requires custom parsing
- Framework-specific semantics need encoding

### 6.2 Entry Point Registration

```toml

### 6.3 Implementation Protocol

```python
from darnit.core.plugin import ComplianceImplementation, ControlSpec

class MyImplementation:
    @property
    def name(self) -> str:
        return "my-framework"

    @property
    def display_name(self) -> str:
        return "My Framework"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def spec_version(self) -> str:
        return "MySpec v1.0"

    def get_all_controls(self) -> list[ControlSpec]:
        # Return control definitions
        ...

    def get_framework_config_path(self) -> Path | None:
        # Return path to TOML config
        return Path(__file__).parent / "my-framework.toml"

    def register_controls(self) -> None:
        # Register Python-defined controls with sieve
        ...
```

### 6.4 Function Reference Security

TOML can reference Python functions via `module:function` syntax:

```toml
api_check = "darnit_baseline.checks:check_branch_protection"
```

**Security Rules**:
- Only whitelisted module prefixes are allowed
- Base whitelist: `darnit.`, `darnit_baseline.`, `darnit_plugins.`
- Additional prefixes discovered from registered entry points

---

