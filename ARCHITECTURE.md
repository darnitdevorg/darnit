# Darnit Architecture

> **For LLMs**: This document provides essential context for understanding and modifying this codebase. Read this first before making changes.

## 1. What is Darnit?

Darnit is a plugin-based compliance auditing framework. It exposes compliance checks as MCP (Model Context Protocol) tools that AI assistants can call. The framework is generic; compliance standards are provided by implementation plugins.

**OpenSSF Baseline** (`darnit-baseline`) is the reference implementation, checking 62 controls from the [OpenSSF Baseline](https://baseline.openssf.org/) security standard (OSPS v2025.10.10).

### Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| MCP Framework | `mcp[cli]` with FastMCP |
| Package Manager | `uv` (monorepo workspace) |
| CLI | `darnit serve` / `darnit audit` |
| GitHub Integration | `gh` CLI |
| Expression Engine | CEL (Common Expression Language) |
| Signing | Sigstore (sigstore-python) |
| Attestations | in-toto format |

### Conservative-by-Default Philosophy

This is a compliance auditing tool. Incorrect results are worse than incomplete results:

- **Never assume compliance.** A control that hasn't been explicitly verified as passing is NOT compliant. WARN means "we don't know" and is treated the same as FAIL for compliance calculations.
- **Never guess user-specific values.** Maintainers, security contacts, governance models require explicit user confirmation. When `auto_detect = false` in TOML, the sieve must not run for that key.
- **Err on the side of caution.** When in doubt, return WARN (needs verification), not PASS.

### How a Typical Session Works

Here's the end-to-end flow that an AI assistant (or human) goes through when auditing a project:

```
 1. LOAD                     2. AUDIT                      3. GATHER CONTEXT
 ───────────────────         ───────────────────────        ───────────────────────
 Load controls from          Run each control through       For controls that WARN:
 framework TOML              the sieve pipeline:
                                                            a) User points to where
 Load existing project         DETERMINISTIC                   things actually live
 context from .project/        │ file exists? API call?        (e.g., "my security
                               ▼                               docs are at
 Merge user overrides          PATTERN                         docs/security.txt,
 from .baseline.toml           │ regex match? heuristics?      not SECURITY.md")
                               ▼
                               LLM                          b) Framework needs user
                               │ ask calling AI to judge       to confirm values it
                               ▼                               can't safely guess
                               MANUAL                          (e.g., "who are the
                               │ human verification steps      maintainers?")

                             Each phase can use built-in
                             handlers OR custom Python
                             plugin handlers

                             Controls get PASS, FAIL,       Context is stored in
                             or WARN (inconclusive)         .project/project.yaml


 4. RE-AUDIT (optional)      5. REMEDIATE                  6. COMMIT
 ───────────────────────     ───────────────────────        ───────────────────────
 Re-run with new context     For controls still failing:    Branch, commit, and PR
 → some WARNs become                                       the changes
 PASS or FAIL now that       Apply TOML-declared fixes
 we know where files are     using gathered context or
 and have confirmed values   sensible defaults as input:

                               • file_create (from template)
                               • exec (run commands)
                               • api_call (GitHub API)
                               • project_update (.project/)
                               • custom plugin handlers
```

**Why context gathering matters**: Many controls can't be fully automated. The sieve might find that *something* exists but not *where*, or it might need human judgment about project-specific facts. For example:

- **Custom checks**: Each sieve phase uses built-in handlers (`file_exists`, `exec`, `pattern`, `manual`) by default, but any phase can be replaced with a custom Python handler registered by a plugin — e.g., running OpenSSF Scorecard, querying a vulnerability database, or checking internal policy systems.
- **Locator misses**: The control checks `SECURITY.md` and `.github/SECURITY.md`, but your project keeps security docs at `docs/security.txt`. The user tells the framework where to look, and that location is stored so future audits find it automatically.
- **Value confirmation**: The framework can auto-detect potential maintainers from git history or GitHub collaborators, but it won't *assume* those are correct — it presents candidates and asks the user to confirm. This is the conservative-by-default philosophy in action.
- **Remediation prerequisites**: Some fixes need context before they can run. Creating a `CODEOWNERS` file requires knowing who the maintainers are. The framework checks for this upfront and prompts for missing values before attempting the fix.
- **Custom remediation**: The built-in remediation types (`file_create`, `exec`, `api_call`) cover common cases, but implementations can register custom Python handlers for anything more complex — e.g., modifying CI configs, updating dependency manifests, or calling third-party libraries.

Context is currently stored in `.project/project.yaml` (a dotfile directory in the repo root). The storage layer is designed to be pluggable in the future — the framework reads/writes context through an abstraction (`context/dot_project.py`, `context/dot_project_mapper.py`) rather than touching YAML directly, so alternative backends (database, API, etc.) could be swapped in.

---

## 2. Package Structure

```
baseline-mcp/
├── packages/
│   ├── darnit/                      # Core framework (MUST NOT import implementations)
│   │   ├── pyproject.toml           # CLI entry point: darnit = "darnit.cli:main"
│   │   └── src/darnit/
│   │       ├── cli.py               # darnit serve | audit | plan | validate | init | list
│   │       ├── core/                # Plugin protocol, discovery, handler registry, logging
│   │       ├── sieve/               # 4-phase verification pipeline
│   │       ├── config/              # TOML loading, merging, schema validation
│   │       ├── context/             # .project/ context: sieve, confidence, dot_project
│   │       ├── remediation/         # RemediationExecutor, helpers, GitHub API
│   │       ├── filtering/           # Tag-based control filtering
│   │       ├── server/              # MCP server factory, tool registration
│   │       │   └── tools/           # Built-in MCP tools (audit, remediate, list, git, context)
│   │       ├── tools/               # Audit orchestration, helpers
│   │       └── formatters/          # Output formatting (markdown, SARIF)
│   │
│   ├── darnit-baseline/             # OpenSSF Baseline implementation
│   │   ├── openssf-baseline.toml    # 62 control definitions (source of truth)
│   │   └── src/darnit_baseline/
│   │       ├── implementation.py    # ComplianceImplementation class
│   │       ├── tools.py             # Custom MCP tool handlers
│   │       ├── controls/            # (mostly empty — controls moved to TOML)
│   │       ├── remediation/         # Remediation orchestrator + legacy helpers
│   │       ├── rules/               # SARIF rule catalog
│   │       ├── attestation/         # In-toto + Sigstore signing
│   │       ├── threat_model/        # STRIDE analysis engine
│   │       └── formatters/          # SARIF output generation
│   │
│   ├── darnit-example/              # Example implementation (docs reference)
│   ├── darnit-plugins/              # Plugin utilities
│   └── darnit-testchecks/           # Test implementation (for testing)
│
├── docs/
│   ├── WORKFLOW.md                  # Mermaid diagrams (audit, remediation, context, startup)
│   ├── IMPLEMENTATION_GUIDE.md      # Plugin authoring guide (the how-to companion to this doc)
│   └── generated/
│       ├── SCHEMA_REFERENCE.md      # TOML schema reference (auto-generated)
│       └── USAGE_GUIDE.md           # Usage guide (auto-generated)
│
├── openspec/specs/
│   └── framework-design/spec.md     # Authoritative framework specification
│
├── tests/
│   ├── darnit/                      # Framework unit tests
│   ├── darnit_baseline/             # Implementation tests
│   └── integration/                 # End-to-end tests
│
├── scripts/
│   ├── validate_sync.py             # Spec-implementation sync checker
│   └── generate_docs.py             # Regenerate docs/generated/
│
├── CLAUDE.md                        # Development guidelines and rules
└── pyproject.toml                   # Workspace root (uv workspace)
```

### Separation Rule

**The framework (`darnit`) MUST NOT import implementation packages.** All communication goes through the `ComplianceImplementation` protocol. Implementations *may* import from the framework.

```python
# WRONG — creates hard dependency
from darnit_baseline.controls import level1

# CORRECT — use plugin discovery
from darnit.core.discovery import get_default_implementation
impl = get_default_implementation()
controls = impl.get_all_controls()
```

---

## 3. Three-Layer Architecture

Darnit operates at three distinct layers. Each has built-in primitives and plugin extensibility:

```
┌─────────────────────────────────────────────────────────┐
│  Layer 3: MCP Tools (what the AI assistant calls)       │
│                                                         │
│  Built-in: audit, remediate, list_controls              │
│  Plugin:   any Python function registered as a handler  │
│                                                         │
│  TOML:  [mcp.tools.audit]                               │
│         builtin = "audit"                               │
├─────────────────────────────────────────────────────────┤
│  Layer 2: Remediation (how to fix a failing control)    │
│                                                         │
│  Built-in: file_create, exec, api_call, project_update  │
│  Plugin:   handler = "my_module:my_func"                │
│                                                         │
│  TOML:  [controls."X".remediation.file_create]          │
│         path = "SECURITY.md"                            │
│         template = "security_policy"                    │
├─────────────────────────────────────────────────────────┤
│  Layer 1: Checking (how to verify a control)            │
│                                                         │
│  Built-in: file_must_exist, exec, pattern, manual       │
│  Plugin:   handler = "my_module:my_func"                │
│                                                         │
│  TOML:  [controls."X".passes.deterministic]             │
│         file_must_exist = ["README.md"]                 │
└─────────────────────────────────────────────────────────┘
```

**Layer 1 (Checking)** answers: "Does this control pass?" Using built-in sieve pass types (file existence, command execution, regex patterns, manual steps) or custom Python handler functions.

**Layer 2 (Remediation)** answers: "How do I fix it?" Using built-in actions (create file from template, run command, call API, update project config) or custom Python functions.

**Layer 3 (MCP Tools)** answers: "What can the AI assistant do?" Using built-in tools (audit all controls, remediate failures, list controls) or custom Python tool handlers.

For simple frameworks, all three layers can be TOML-only — no Python required.

---

## 4. The Sieve Pipeline

The sieve is a 4-phase verification waterfall. Each control defines one or more "passes" that execute in order. The orchestrator stops at the first conclusive result.

**Ordering is controlled by declaration order in TOML.** The `[[controls."X".passes]]` array is a flat ordered list — the orchestrator iterates it top-to-bottom, running each handler in sequence. The framework warns if phases are out of the recommended order (DETERMINISTIC → PATTERN → LLM → MANUAL), but it's advisory; the TOML author has full control over execution order. A control can have multiple passes in the same phase, skip phases entirely, or use only custom plugin handlers.

```
┌─────────────────────────────────────────────────────────┐
│                   CONTROL VERIFICATION                  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Phase 1: DETERMINISTIC                                 │
│  ├─ file_must_exist, exec + CEL, api_check              │
│  └─ High confidence (1.0)                               │
│                     │                                   │
│            PASS/FAIL? ──────► DONE                      │
│                     │ INCONCLUSIVE                      │
│                     ▼                                   │
│  Phase 2: PATTERN                                       │
│  ├─ Regex content matching, heuristic analysis          │
│  └─ Medium confidence (0.7–0.9)                         │
│                     │                                   │
│            PASS/FAIL? ──────► DONE                      │
│                     │ INCONCLUSIVE                      │
│                     ▼                                   │
│  Phase 3: LLM                                           │
│  ├─ Consultation request for calling AI to analyze      │
│  └─ Variable confidence (0.5–0.9)                       │
│                     │                                   │
│            PASS/FAIL? ──────► DONE                      │
│                     │ INCONCLUSIVE                      │
│                     ▼                                   │
│  Phase 4: MANUAL                                        │
│  └─ Returns WARN with human verification steps          │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Key Data Types

All defined in `packages/darnit/src/darnit/sieve/models.py`:

| Type | Purpose |
|------|---------|
| `VerificationPhase` | Enum: `DETERMINISTIC`, `PATTERN`, `LLM`, `MANUAL` |
| `PassOutcome` | Enum: `PASS`, `FAIL`, `INCONCLUSIVE`, `ERROR` |
| `CheckContext` | Runtime context for each pass (owner, repo, local_path, project_context, gathered_evidence) |
| `PassResult` | What every pass returns (phase, outcome, message, evidence, confidence) |
| `PassAttempt` | Record of what a pass attempted, for transparency |
| `SieveResult` | Complete result: status (PASS/FAIL/WARN/NA/ERROR/PENDING_LLM), conclusive_phase, pass_history |
| `ControlSpec` | Control definition: control_id, level, domain, name, description, passes[], tags, metadata |
| `LLMConsultationResponse` | Parsed LLM response with confidence and reasoning |

### Evidence Accumulation

Each pass can return `evidence` (a dict) in its `PassResult`. This evidence is merged into `CheckContext.gathered_evidence` for subsequent passes, enabling multi-pass pipelines where later phases build on earlier discoveries.

### LLM Consultation Protocol

Phase 3 returns a `PENDING_LLM` status with consultation details. The calling AI assistant analyzes the evidence and returns a structured `LLMConsultationResponse`. The sieve never calls an LLM directly — it delegates to whoever invoked the audit.

---

## 5. TOML-First Control Definitions

Controls are defined declaratively in TOML. The framework TOML file (`openssf-baseline.toml` for the Baseline implementation) is the source of truth for control metadata, passes, and remediation.

### Real Example: OSPS-VM-02.01

```toml
[controls."OSPS-VM-02.01"]
name = "HasSecurityPolicy"
description = "Repository has a security policy"
tags = { level = 1, domain = "VM", security_severity = 7.0, security = true }

[controls."OSPS-VM-02.01".locator]
project_path = "security.policy"
discover = ["SECURITY.md", ".github/SECURITY.md", "docs/SECURITY.md"]
kind = "file"

[[controls."OSPS-VM-02.01".passes]]
handler = "file_exists"
use_locator = true

[[controls."OSPS-VM-02.01".passes]]
handler = "manual"
steps = [
    "Look for SECURITY.md in repository root or .github/ directory",
    "Verify it contains vulnerability reporting instructions",
    "Check for security contact or email address",
]

[controls."OSPS-VM-02.01".remediation]
safe = true
dry_run_supported = true

[[controls."OSPS-VM-02.01".remediation.handlers]]
handler = "file_create"
path = "SECURITY.md"
template = "security_policy_standard"
overwrite = false
```

### Built-in Pass Types

| TOML Handler | Phase | Purpose |
|-------------|-------|---------|
| `file_exists` | Deterministic | Check if any listed file exists |
| `exec` | Deterministic | Run external command, evaluate with CEL expression |
| `pattern` / `regex` | Pattern | Regex match in file contents |
| `manual` | Manual | Human verification steps (always INCONCLUSIVE → WARN) |

Custom handlers can be registered by plugins and referenced by short name in TOML.

### CEL Expressions

The `exec` pass type supports CEL (Common Expression Language) for evaluating command output:

```toml
[[controls."OSPS-AC-01.01".passes]]
handler = "exec"
command = ["gh", "api", "/orgs/$OWNER"]
output_format = "json"
expr = 'output.json.two_factor_requirement_enabled == true'
```

Available variables: `output.stdout`, `output.stderr`, `output.exit_code`, `output.json`, plus `project.*` from context.

### Remediation in TOML

Controls can define declarative remediation:

- **`file_create`** — Create a file from a template (`template = "security_policy_standard"`)
- **`exec`** — Run a command
- **`api_call`** — Call the GitHub API via `gh api`
- **`project_update`** — Update `.project/project.yaml` after successful fix

Templates are defined in `[templates.*]` sections and support `$OWNER`, `$REPO`, and `${context.*}` variable substitution.

### OSPS Control Categories

Controls follow the pattern `OSPS-{DOMAIN}-{NUMBER}.{SUBNUMBER}`:

| Domain | Name | Level 1 | Level 2 | Level 3 |
|--------|------|---------|---------|---------|
| AC | Access Control | 4 | 1 | 1 |
| BR | Build & Release | 5 | 4 | 2 |
| DO | Documentation | 2 | 1 | 4 |
| GV | Governance | 2 | 3 | 1 |
| LE | Legal | 4 | 1 | 0 |
| QA | Quality Assurance | 6 | 2 | 5 |
| SA | Security Architecture | 0 | 3 | 1 |
| VM | Vulnerability Management | 1 | 3 | 6 |
| **Total** | | **24** | **18** | **20** |

**Total: 62 controls** (OSPS v2025.10.10)

---

## 6. Plugin Protocol

### ComplianceImplementation

Implementations register via Python entry points and satisfy a structural protocol:

```python
@runtime_checkable
class ComplianceImplementation(Protocol):
    @property
    def name(self) -> str: ...                              # "openssf-baseline"
    @property
    def display_name(self) -> str: ...                      # "OpenSSF Baseline"
    @property
    def version(self) -> str: ...                           # "0.1.0"
    @property
    def spec_version(self) -> str: ...                      # "OSPS v2025.10.10"

    def get_all_controls(self) -> list[ControlSpec]: ...
    def get_controls_by_level(self, level: int) -> list[ControlSpec]: ...
    def get_rules_catalog(self) -> dict[str, Any]: ...
    def get_remediation_registry(self) -> dict[str, Any]: ...
    def get_framework_config_path(self) -> Path | None: ...
    def register_controls(self) -> None: ...
    # Optional: register_handlers() — checked via hasattr()
```

### Entry Point Registration

```toml
# In pyproject.toml of the implementation package:
[project.entry-points."darnit.implementations"]
openssf-baseline = "darnit_baseline:register"
```

The `register()` function returns an instance of the implementation class. The framework discovers implementations via `importlib.metadata.entry_points(group="darnit.implementations")`.

### Handler Registration

Implementations can register custom MCP tool handlers and custom sieve handlers:

| Registry | Layer | Purpose | Access |
|----------|-------|---------|--------|
| `SieveHandlerRegistry` | 1 & 2 | Checking + remediation handlers | `get_sieve_handler_registry()` from `darnit.sieve.handler_registry` |
| `HandlerRegistry` | 3 | MCP tool handlers | `get_handler_registry()` from `darnit.core.handlers` |

Both registries use `set_plugin_context(name)` / `set_plugin_context(None)` to track handler ownership.

---

## 7. Configuration System

Three configuration layers, merged at runtime:

```
┌──────────────────────────────────────────────────────┐
│  Layer 1: Framework TOML (e.g., openssf-baseline.toml)│
│  Defines: controls, passes, templates, context prompts│
│  Owner: implementation author                         │
├──────────────────────────────────────────────────────┤
│  Layer 2: .baseline.toml (user overrides)             │
│  Defines: disabled controls, severity overrides,      │
│           custom tags, plugin trust settings           │
│  Owner: project maintainer                            │
├──────────────────────────────────────────────────────┤
│  Layer 3: .project/project.yaml (project context)     │
│  Defines: maintainers, CI provider, governance model, │
│           security contacts, release info              │
│  Owner: populated by user confirmation + sieve passes │
└──────────────────────────────────────────────────────┘
```

At audit time, the framework merges Layer 1 + Layer 2 into an "effective config", then injects Layer 3 into each `CheckContext.project_context`.

### Context Collection

The framework TOML defines `[context.*]` sections that describe what project-specific information improves audit accuracy. Each context key has a type, prompt, hint, and list of affected controls. The `get_pending_context()` MCP tool returns unanswered prompts; the `confirm_project_context()` tool saves answers to `.project/project.yaml`.

Context values with `auto_detect = true` can be discovered by sieve passes (e.g., detecting CI provider from `.github/workflows/` existence). Values with `auto_detect = false` require explicit user confirmation.

---

## 8. Data Flow

High-level flow for a single audit:

```
AI Assistant
    │
    ▼
audit_openssf_baseline(level=1)
    │
    ├─► Load framework TOML + .baseline.toml → EffectiveConfig
    ├─► Load .project/project.yaml → project_context
    ├─► Convert controls → ControlSpec + Pass objects
    ├─► Filter by level (and optionally by tags)
    │
    ├─► For each control:
    │       Create CheckContext (owner, repo, local_path, project_context)
    │       SieveOrchestrator.verify() → run passes in phase order
    │       Collect SieveResult
    │       If PASS → apply on_pass project_update
    │
    ├─► Calculate summary (PASS/FAIL/WARN counts)
    ├─► Format as markdown report
    │
    ▼
Return to AI
```

For detailed mermaid diagrams of audit internals, remediation flow, context lifecycle, and server startup, see [docs/WORKFLOW.md](docs/WORKFLOW.md).

---

## 9. Key Source Files

### Core Framework (`packages/darnit/src/darnit/`)

| Subsystem | File | Purpose |
|-----------|------|---------|
| **Entry** | `cli.py` | CLI: `darnit serve`, `darnit audit`, `darnit plan`, `darnit validate` |
| **Core** | `core/plugin.py` | `ComplianceImplementation` protocol definition |
| | `core/discovery.py` | Plugin discovery via entry points |
| | `core/handlers.py` | MCP tool handler registry (Layer 3) |
| **Sieve** | `sieve/models.py` | `CheckContext`, `PassResult`, `SieveResult`, `ControlSpec` |
| | `sieve/orchestrator.py` | Runs passes in phase order, stops on conclusion |
| | `sieve/registry.py` | Global `ControlRegistry` for registered controls |
| | `sieve/handler_registry.py` | `SieveHandlerRegistry` (Layer 1 & 2 custom handlers) |
| | `sieve/builtin_handlers.py` | Built-in handlers: `file_exists`, `exec`, `regex`, `manual` |
| | `sieve/cel_evaluator.py` | CEL expression evaluation for exec passes |
| | `sieve/llm_protocol.py` | LLM consultation request/response protocol |
| **Config** | `config/loader.py` | Load and parse TOML framework configs |
| | `config/framework_schema.py` | Schema for framework TOML validation |
| | `config/control_loader.py` | Convert TOML controls → `ControlSpec` objects |
| | `config/merger.py` | Merge framework + user configs → effective config |
| **Context** | `context/dot_project.py` | Load/save `.project/project.yaml` |
| | `context/dot_project_mapper.py` | Map TOML context keys to project YAML paths |
| | `context/sieve.py` | Context sieve (progressive auto-detection) |
| | `context/confidence.py` | Signal weighting and confidence scoring |
| **Remediation** | `remediation/executor.py` | `RemediationExecutor` — runs TOML-declared fixes |
| | `remediation/helpers.py` | Common remediation utilities |
| **Server** | `server/factory.py` | MCP server assembly from TOML + plugins |
| | `server/tools/builtin_audit.py` | Built-in `audit` MCP tool |
| | `server/tools/builtin_list.py` | Built-in `list_controls` MCP tool |
| | `server/tools/project_context.py` | `get_pending_context`, `confirm_project_context` tools |

### OpenSSF Baseline (`packages/darnit-baseline/`)

| File | Purpose |
|------|---------|
| `openssf-baseline.toml` | All 62 control definitions, templates, context prompts |
| `src/darnit_baseline/implementation.py` | `OpenSSFBaselineImplementation` class |
| `src/darnit_baseline/tools.py` | Custom MCP tool handlers (threat model, attestation, etc.) |
| `src/darnit_baseline/remediation/orchestrator.py` | Legacy remediation orchestration |
| `src/darnit_baseline/rules/catalog.py` | SARIF rule metadata (fallback for unmigrated controls) |
| `src/darnit_baseline/attestation/` | In-toto attestation generation + Sigstore signing |
| `src/darnit_baseline/threat_model/` | STRIDE threat analysis engine |

---

## 10. Related Documentation

| Document | What it covers |
|----------|---------------|
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | Mermaid diagrams: audit internals, remediation flow, context lifecycle, server startup |
| [docs/IMPLEMENTATION_GUIDE.md](docs/IMPLEMENTATION_GUIDE.md) | Step-by-step guide to building a darnit plugin (package setup, TOML config, sieve handlers, testing) |
| [docs/generated/SCHEMA_REFERENCE.md](docs/generated/SCHEMA_REFERENCE.md) | Auto-generated TOML schema reference |
| [docs/generated/USAGE_GUIDE.md](docs/generated/USAGE_GUIDE.md) | Auto-generated usage guide |
| [openspec/specs/framework-design/spec.md](openspec/specs/framework-design/spec.md) | Authoritative framework specification |
| [CLAUDE.md](CLAUDE.md) | Development guidelines, separation rules, testing commands |
| [OpenSSF Baseline Specification](https://baseline.openssf.org/) | The compliance standard that `darnit-baseline` implements |
| [MCP Protocol](https://modelcontextprotocol.io/) | Model Context Protocol specification |

---

*Last updated: 2026-02-10 | Darnit framework with TOML-first plugin architecture, 62 OpenSSF Baseline controls*
