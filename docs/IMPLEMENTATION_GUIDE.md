# Building a darnit Implementation

This guide walks through building a compliance implementation for the darnit framework.
By the end, you'll have a working plugin that defines controls, runs automated checks
through the sieve pipeline, and provides remediation actions.

We'll build a hypothetical implementation called "darnit-mystandard" that checks projects
against a fictional "My Compliance Standard". Along the way, we'll reference how
`darnit-baseline` (the OpenSSF Baseline implementation) solves the same problems.

## Prerequisites

- Python 3.11+
- Familiarity with Python packaging (pyproject.toml, entry points)
- A local clone of the darnit repository for reference

> **Working example**: The `packages/darnit-example/` package is a complete,
> installable implementation that follows every step in this guide. You can
> study it alongside these instructions — see `packages/darnit-example/README.md`
> for a mapping between guide sections and example files.

## Architecture Overview

darnit uses a plugin architecture that separates the core framework from compliance
implementations:

```
┌─────────────────────────────────────────────────────────┐
│                    darnit (framework)                    │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌────────┐  ┌──────────┐  │
│  │ Discovery │  │  Sieve   │  │ Config │  │  Server  │  │
│  │  System   │  │ Pipeline │  │ Loader │  │  (MCP)   │  │
│  └──────────┘  └──────────┘  └────────┘  └──────────┘  │
│        │              │            │                     │
│        ▼              ▼            ▼                     │
│  ComplianceImplementation Protocol                      │
└────────────────┬────────────────────────────────────────┘
                 │
    ┌────────────┼────────────────┐
    ▼            ▼                ▼
┌─────────┐  ┌──────────┐  ┌──────────┐
│ darnit- │  │ darnit-  │  │  your    │
│baseline │  │testchecks│  │  plugin  │
└─────────┘  └──────────┘  └──────────┘
```

**Key rule**: The framework never imports implementation packages directly. All
communication goes through the `ComplianceImplementation` protocol. Implementations
*may* import from the framework.

### The three layers

darnit operates at three distinct layers. Each layer has built-in primitives and
plugin extensibility:

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

**Layer 1 (Checking)** answers: "Does this control pass?" Using built-in pass types
(file existence, command execution, regex patterns) or custom Python check functions.

**Layer 2 (Remediation)** answers: "How do I fix it?" Using built-in actions
(create file from template, run command, call API, update project config) or custom
Python remediation functions.

**Layer 3 (MCP Tools)** answers: "What can the AI assistant do?" Using built-in
tools (audit all controls, remediate failures, list controls) or custom Python
tool handlers.

For simple frameworks, all three layers can be TOML-only — no Python required.
For complex frameworks, any layer can be extended with Python plugins.

---

## Quick Start: TOML-Only Framework (No Python)

If your controls only need file checks and template-based remediation, you can
create a working MCP server with just a TOML file:

```toml
# my-standard.toml
[metadata]
name = "my-standard"
version = "0.1.0"
schema_version = "0.1.0-alpha"
spec_version = "v1.0"
description = "My compliance standard"

[templates.readme]
content = "# $REPO\nA brief description.\n"

[controls."MS-01"]
name = "HasReadme"
description = "Project must have a README"
tags = { level = 1, domain = "DOC" }

[controls."MS-01".passes]
deterministic = { file_must_exist = ["README.md", "README.rst"] }

[controls."MS-01".passes.manual]
steps = ["Check for README in project root"]

[controls."MS-01".remediation]
safe = true
dry_run_supported = true

[controls."MS-01".remediation.file_create]
path = "README.md"
template = "readme"

[controls."MS-01".remediation.project_update]
set = { "documentation.readme.path" = "README.md" }

[mcp.tools.audit]
builtin = "audit"
description = "Run compliance audit"

[mcp.tools.remediate]
builtin = "remediate"
description = "Auto-fix failing controls"

[mcp.tools.list_controls]
builtin = "list_controls"
description = "List all controls"
```

Serve it directly:

```bash
darnit serve /path/to/my-standard.toml
```

Or configure in Claude Code:

```json
{
  "mcpServers": {
    "my-standard": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/darnit", "darnit", "serve", "/path/to/my-standard.toml"]
    }
  }
}
```

The `builtin = "audit"` tools use the framework's generic implementations that
work with any TOML-defined controls. For custom tools, use a Python plugin
package instead (see sections below).

---

## 1. Package Setup

### Directory structure

```
darnit-mystandard/
├── pyproject.toml
├── mystandard.toml              # Framework configuration
└── src/
    └── darnit_mystandard/
        ├── __init__.py           # register() function
        ├── implementation.py     # ComplianceImplementation class
        ├── controls/
        │   ├── __init__.py
        │   └── level1.py         # Python-defined controls
        └── remediation/
            ├── __init__.py
            └── registry.py       # Remediation action mappings
```

### pyproject.toml

The critical piece is the entry point registration. darnit discovers implementations
through the `darnit.implementations` entry point group:

```toml
[project]
name = "darnit-mystandard"
version = "0.1.0"
description = "My Compliance Standard checks for darnit"
requires-python = ">=3.11"
dependencies = [
    "darnit>=0.1.0",
]

[project.entry-points."darnit.implementations"]
mystandard = "darnit_mystandard:register"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/darnit_mystandard"]
```

The entry point format is `name = "module:function"`. When darnit starts, it calls
`importlib.metadata.entry_points(group="darnit.implementations")`, loads each entry
point, and calls the returned function.

### The register() function

```python
# src/darnit_mystandard/__init__.py

def register():
    """Register the My Standard implementation with darnit.

    Called by darnit's plugin discovery via entry points.
    """
    from .implementation import MyStandardImplementation
    return MyStandardImplementation()
```

The lazy import inside `register()` is intentional — it avoids loading the
implementation class until darnit actually needs it.

> **Reference**: See `packages/darnit-baseline/src/darnit_baseline/__init__.py`
> and `packages/darnit-baseline/pyproject.toml` for the real implementation.

---

## 2. The Implementation Class

Your implementation must satisfy the `ComplianceImplementation` protocol defined in
`packages/darnit/src/darnit/core/plugin.py`. This is a `typing.Protocol` (structural
typing), so you don't need to inherit from it — just implement the required interface.

### Protocol definition

```python
@runtime_checkable
class ComplianceImplementation(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def display_name(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def spec_version(self) -> str: ...

    def get_all_controls(self) -> list[ControlSpec]: ...
    def get_controls_by_level(self, level: int) -> list[ControlSpec]: ...
    def get_rules_catalog(self) -> dict[str, Any]: ...
    def get_remediation_registry(self) -> dict[str, Any]: ...
    def get_framework_config_path(self) -> Path | None: ...
    def register_controls(self) -> None: ...
```

### Required properties (4)

| Property | Type | Purpose |
|----------|------|---------|
| `name` | `str` | Unique identifier (e.g., `"mystandard"`) |
| `display_name` | `str` | Human-readable name (e.g., `"My Compliance Standard"`) |
| `version` | `str` | Implementation version (e.g., `"0.1.0"`) |
| `spec_version` | `str` | Spec version implemented (e.g., `"MySpec v1.0"`) |

### Required methods (6)

| Method | Purpose |
|--------|---------|
| `get_all_controls()` | Return all controls as `ControlSpec` objects |
| `get_controls_by_level(level)` | Filter controls by maturity level |
| `get_rules_catalog()` | Return SARIF rule definitions for output formatting |
| `get_remediation_registry()` | Return mapping of remediation categories to fix functions |
| `get_framework_config_path()` | Return path to the TOML configuration file |
| `register_controls()` | Import Python control modules to trigger registration |

### Optional methods

| Method | Purpose |
|--------|---------|
| `register_handlers()` | Register MCP tool handlers (checked via `hasattr`) |

### Minimal implementation

```python
# src/darnit_mystandard/implementation.py
from pathlib import Path
from typing import Any

from darnit.core.plugin import ControlSpec


class MyStandardImplementation:
    """My Compliance Standard implementation for darnit."""

    @property
    def name(self) -> str:
        return "mystandard"

    @property
    def display_name(self) -> str:
        return "My Compliance Standard"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def spec_version(self) -> str:
        return "MySpec v1.0"

    def get_all_controls(self) -> list[ControlSpec]:
        controls = []
        for level in [1, 2, 3]:
            controls.extend(self.get_controls_by_level(level))
        return controls

    def get_controls_by_level(self, level: int) -> list[ControlSpec]:
        # For now, delegate to the sieve registry
        from darnit.sieve.registry import get_control_registry
        registry = get_control_registry()
        return registry.get_specs_by_level(level)

    def get_rules_catalog(self) -> dict[str, Any]:
        return {}  # Populate as needed for SARIF output

    def get_remediation_registry(self) -> dict[str, Any]:
        from .remediation.registry import REMEDIATION_REGISTRY
        return REMEDIATION_REGISTRY

    def get_framework_config_path(self) -> Path | None:
        # Navigate from implementation.py to the TOML file
        return Path(__file__).parent.parent.parent / "mystandard.toml"

    def register_controls(self) -> None:
        """TOML-first: controls are defined in the TOML config file.

        No Python registration is needed. Override this only if you need
        to register custom sieve handlers (see Section 5).
        """
        pass
```

The `get_framework_config_path()` method deserves attention: it must return the
correct path relative to `implementation.py`. The path traversal depends on your
package structure. For `src/darnit_mystandard/implementation.py` reaching
`mystandard.toml` at the package root:

```
implementation.py  →  parent (darnit_mystandard/)
                   →  parent (src/)
                   →  parent (darnit-mystandard/)
                   →  / mystandard.toml
```

> **Reference**: See `packages/darnit-baseline/src/darnit_baseline/implementation.py`
> for the full OpenSSF Baseline implementation class.

---

## 3. TOML Framework Configuration

The TOML file is the declarative heart of your implementation. It defines metadata,
templates, context collection prompts, and control definitions. The framework loads
this file via `get_framework_config_path()`.

### Metadata section

```toml
[metadata]
name = "mystandard"
display_name = "My Compliance Standard"
version = "0.1.0"
schema_version = "0.1.0-alpha"
spec_version = "MySpec v1.0"
description = "Compliance controls for My Standard"
url = "https://example.com/mystandard"

[defaults]
check_adapter = "builtin"
remediation_adapter = "builtin"
```

### Control definitions

Each control is defined under `[controls."CONTROL-ID"]`. Controls can have
declarative passes that the framework executes without Python code:

```toml
[controls."MS-DOC-01"]
name = "ReadmeExists"
description = "Project must have a README file"
tags = { level = 1, domain = "DOC", documentation = true }
docs_url = "https://example.com/mystandard#MS-DOC-01"
help_md = """Create a README.md file in the repository root.

**Remediation:**
1. Create README.md with project description
2. Include usage instructions
"""

# Deterministic pass: check if file exists
[controls."MS-DOC-01".passes.deterministic]
file_must_exist = [
    "README.md",
    "README.rst",
    "README.txt",
    "README",
]

# Manual pass: fallback verification steps
[controls."MS-DOC-01".passes.manual]
steps = [
    "Check repository root for README file",
    "Verify README contains project description",
]
```

### Handler `when` clauses

Controls can declare preconditions using a `when` clause. If the condition is not
met, the control is **skipped** (not failed) during the audit. This is useful for
controls that only apply to certain platforms, CI providers, or project types:

```toml
# Only check on GitHub-hosted repositories
[controls."MS-AC-01"]
name = "RequireMFA"
description = "Require multi-factor authentication"
when = { platform = "github" }

# Only check if the project uses GitHub Actions
[controls."MS-CI-01"]
name = "SecureWorkflowInputs"
description = "Workflows handle untrusted inputs safely"
when = { ci_provider = "github" }

# Only check if the project makes official releases
[controls."MS-REL-01"]
name = "SignReleases"
description = "Sign releases or provide signed manifest"
when = { has_releases = true }

# Multiple conditions (all must be true)
[controls."MS-REL-02"]
name = "UniqueVersionIdentifiers"
description = "Assign unique version identifiers to each release"
when = { has_releases = true, platform = "github" }
```

The `when` keys are matched against project context values from `.project/project.yaml`.
If a key is missing from the project context, the condition is treated as **not met**
and the control is skipped. This avoids false failures for controls that are
inapplicable to the project.

> **Reference**: See `packages/darnit-baseline/openssf-baseline.toml` for real-world
> `when` clauses used across 30+ controls.

### Built-in pass types

The framework provides these built-in handler names for use in TOML `[[passes]]`
entries, implemented in `packages/darnit/src/darnit/sieve/builtin_handlers.py`:

| Handler Name | Purpose |
|-------------|---------|
| `file_exists` / `file_must_exist` | File existence checks |
| `exec` | Run external commands, evaluate with CEL |
| `regex` / `pattern` | Regex matching in file contents |
| `manual` / `manual_steps` | Human verification steps |

#### file_must_exist

The simplest check — pass if any listed file exists:

```toml
[controls."MS-SEC-01".passes.deterministic]
file_must_exist = [
    "SECURITY.md",
    ".github/SECURITY.md",
    "docs/SECURITY.md",
]
```

#### exec (external command)

Run a CLI tool and evaluate the result with a CEL expression:

```toml
[controls."MS-AC-01".passes.exec]
command = ["gh", "api", "/orgs/$OWNER"]
pass_exit_codes = [0]
fail_exit_codes = [1]
output_format = "json"
expr = 'output.json.two_factor_requirement_enabled == true'
timeout = 30
```

Variable substitution in commands: `$PATH` (local repo path), `$OWNER`,
`$REPO`, `$BRANCH`, `$CONTROL`.

#### Pattern matching

Search file contents with regex:

```toml
[controls."MS-DOC-02".passes.pattern]
file_patterns = ["SECURITY.md", ".github/SECURITY.md"]
content_patterns = { security_contact = '([\w.-]+@[\w.-]+\.\w+|security\s*contact)' }
expr = 'output.any_match'
```

#### Manual verification

Always returns INCONCLUSIVE with human-readable steps:

```toml
[controls."MS-DOC-02".passes.manual]
steps = [
    "Open SECURITY.md",
    "Verify it contains a clear contact method",
    "Confirm the contact method is monitored",
]
```

### Remediation in TOML

Controls can define declarative remediation actions that the framework executes
without Python code. These are the built-in remediation types:

#### file_create

Create a file from a template:

```toml
[controls."MS-SEC-01".remediation]
safe = true
dry_run_supported = true

[controls."MS-SEC-01".remediation.file_create]
path = "SECURITY.md"
template = "security_policy"
overwrite = false
create_dirs = true  # Create parent directories if needed
```

#### exec (run a command)

```toml
[controls."MS-BR-01".remediation.exec]
command = ["git", "tag", "-s", "v1.0.0"]
success_exit_codes = [0]
timeout = 30
```

#### api_call

```toml
[controls."MS-AC-01".remediation.api_call]
method = "PUT"
endpoint = "/repos/$OWNER/$REPO/branches/$BRANCH/protection"
payload_template = "branch_protection_payload"
```

#### project_update

Update `.project/project.yaml` with dotted-path values after a successful
remediation. This keeps the project config in sync with what was created:

```toml
[controls."MS-SEC-01".remediation.project_update]
set = { "security.policy.path" = "SECURITY.md" }
```

The `set` dict maps dotted paths to values. `security.policy.path` becomes:

```yaml
# .project/project.yaml
security:
  policy:
    path: SECURITY.md
```

`project_update` only runs when the primary remediation (file_create, exec, or
api_call) succeeds. In dry-run mode, it shows a preview of what would change.

### on_pass (post-check context updates)

When a control **passes**, the sieve may discover useful evidence (e.g., "SECURITY.md
exists at this path"). The `on_pass` section feeds that evidence back into
`.project/project.yaml` so subsequent checks can use it:

```toml
[controls."MS-SEC-01".on_pass]
project_update = { "security.policy.path" = "SECURITY.md" }
```

Values can reference evidence gathered during the check using `$EVIDENCE.<key>`:

```toml
[controls."MS-SEC-01".on_pass]
project_update = { "security.policy.path" = "$EVIDENCE.file" }
```

This creates a lifecycle:
- Control passes → `on_pass` records what was found
- Control fails → remediation fixes it → `project_update` records what was created
- Next audit run → project config has the context for downstream controls

### Templates

Templates are string content blocks used by remediation actions:

```toml
[templates.security_policy]
description = "Standard SECURITY.md template"
content = """# Security Policy

## Reporting a Vulnerability

Report vulnerabilities by emailing security@$OWNER.example.com.
We will respond within 48 hours.
"""
```

Templates support `$OWNER` and `$REPO` variable substitution.

### Context definitions

Context prompts collect project-specific information to improve audit accuracy:

```toml
[context.ci_provider]
type = "enum"
prompt = "What CI/CD system does this project use?"
hint = "Select your primary CI/CD provider"
values = ["github", "gitlab", "jenkins", "none", "other"]
affects = ["MS-CI-01", "MS-CI-02"]
store_as = "ci.provider"
auto_detect = true
required = false
presentation_hint = "[github/gitlab/jenkins/circleci/azure/travis/none/other]"
```

Context values are stored in `.project/project.yaml` and injected into checks
via `CheckContext.project_context`.

#### `presentation_hint` and `allowed_values`

Context definitions support two additional fields for controlling how the LLM
presents questions to users:

- **`presentation_hint`** — A short string shown alongside the prompt to indicate
  the expected format (e.g., `"[y/N]"` for booleans, `"[github/gitlab/other]"` for enums).
  If not set, the framework auto-generates a hint from `allowed_values` or `values`.

- **`allowed_values`** — An explicit list of display values, distinct from `values`
  (which is used for validation). Useful when the display options differ from the
  validation set.

```toml
[context.governance_model]
type = "enum"
prompt = "What governance model does this project use?"
store_as = "governance.model"
auto_detect = false
presentation_hint = "[bdfl/meritocracy/democracy/corporate/foundation/committee/other]"

[context.has_releases]
type = "boolean"
prompt = "Does this project make official releases?"
store_as = "releases.enabled"
auto_detect = true
presentation_hint = "[y/N]"
```

> **Reference**: See `packages/darnit-baseline/openssf-baseline.toml` for a full
> TOML configuration with 62 controls, templates, and context definitions.

---

## 4. The Sieve Pipeline

The sieve is a 4-phase verification pipeline. Each control defines one or more
"passes" that execute in order. The orchestrator stops at the first conclusive result.

```
DETERMINISTIC  →  PATTERN  →  LLM  →  MANUAL
     ↓               ↓          ↓        ↓
  Exact checks    Heuristics   AI     Human
  (high conf)     (med conf)   eval   review
```

### Phase execution rules

1. **DETERMINISTIC**: File existence, API calls, config lookups. Returns PASS, FAIL,
   or INCONCLUSIVE.
2. **PATTERN**: Regex matching, content analysis. Only runs if DETERMINISTIC was
   INCONCLUSIVE.
3. **LLM**: Asks the calling LLM to analyze evidence. Only runs if earlier phases
   were INCONCLUSIVE.
4. **MANUAL**: Always returns INCONCLUSIVE (rendered as WARN) with verification steps.
   This is the fallback when no automated check can determine the result.

### Key data types

All defined in `packages/darnit/src/darnit/sieve/models.py`:

```python
class VerificationPhase(Enum):
    DETERMINISTIC = "deterministic"
    PATTERN = "pattern"
    LLM = "llm"
    MANUAL = "manual"

class PassOutcome(Enum):
    PASS = "pass"           # Control satisfied
    FAIL = "fail"           # Control NOT satisfied
    INCONCLUSIVE = "inconclusive"  # Cannot determine, try next pass
    ERROR = "error"         # Pass failed to execute
```

**PassResult** is what every pass returns:

```python
@dataclass
class PassResult:
    phase: VerificationPhase
    outcome: PassOutcome
    message: str
    evidence: dict[str, Any] | None = None
    confidence: float | None = None  # 0.0-1.0, primarily for LLM pass
    details: dict[str, Any] | None = None
```

**CheckContext** is what every pass receives:

```python
@dataclass
class CheckContext:
    owner: str                  # GitHub org/user
    repo: str                   # Repository name
    local_path: str             # Path to cloned repo
    default_branch: str         # e.g., "main"
    control_id: str             # e.g., "MS-DOC-01"
    control_metadata: dict      # From TOML definition
    gathered_evidence: dict     # Accumulated from previous passes
    project_context: dict       # From .project/project.yaml
```

### ControlSpec (sieve version)

Controls registered with the sieve use the sieve-specific `ControlSpec` from
`darnit.sieve.models`, not the one from `darnit.core.plugin`:

```python
from darnit.sieve.models import ControlSpec

ControlSpec(
    control_id="MS-DOC-01",
    level=1,
    domain="DOC",
    name="ReadmeExists",
    description="Project must have a README file",
    passes=[
        DeterministicPass(file_must_exist=["README.md", "README.rst"]),
        ManualPass(verification_steps=["Check for README"]),
    ],
)
```

The sieve `ControlSpec` includes a `passes` field (list of pass objects) and validates
that passes are in the correct phase order (DETERMINISTIC → PATTERN → LLM → MANUAL).

> **Reference**: See `packages/darnit/src/darnit/sieve/models.py` for all data types
> and `openspec/specs/framework-design/spec.md` for the authoritative specification.

---

## 5. Custom Sieve Handlers

When the built-in pass types (`file_exists`, `exec`, `regex`, `manual`) aren't enough,
you can write **custom sieve handlers** — Python functions that plug into the
confidence gradient pipeline for checking or remediation.

> **Authoritative API**: See
> `packages/darnit/src/darnit/sieve/handler_registry.py` for the full registry,
> context, and result types.

> **Two registries — don't confuse them!**
>
> | Registry | Layer | Purpose | Access |
> |----------|-------|---------|--------|
> | `SieveHandlerRegistry` | 1 & 2 | Checking + remediation handlers in the sieve pipeline | `get_sieve_handler_registry()` from `darnit.sieve.handler_registry` |
> | `HandlerRegistry` | 3 | MCP tool handlers exposed to the LLM | `get_handler_registry()` from `darnit.core.handlers` |
>
> This section covers `SieveHandlerRegistry` (Layer 1 & 2). For MCP tool handlers,
> see Section 8.

### Handler function signature

Every sieve handler is a plain function with this signature:

```python
from typing import Any
from darnit.sieve.handler_registry import HandlerContext, HandlerResult, HandlerResultStatus

def my_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Check something and return a result."""
    # Your logic here
    return HandlerResult(
        status=HandlerResultStatus.PASS,
        message="Check passed",
        confidence=1.0,
        evidence={"key": "value"},
    )
```

- **`config`** — a dict containing all pass-through fields from the TOML `[[passes]]`
  entry. The framework strips `handler`, `shared`, and `phase` before calling your
  function; everything else arrives as-is.
- **`context`** — an immutable dataclass provided by the framework with everything
  your handler needs to do its work.

### HandlerContext fields

| Field | Type | Description |
|-------|------|-------------|
| `local_path` | `str` | Absolute path to the repository being audited. Always populated. |
| `owner` | `str` | Repository owner (GitHub org or user). Empty string if unknown. |
| `repo` | `str` | Repository name. Empty string if unknown. |
| `default_branch` | `str` | Default branch name (e.g., `"main"`). Defaults to `"main"`. |
| `control_id` | `str` | ID of the control being verified (e.g., `"OSPS-AC-01.01"`). Empty for context gathering. |
| `project_context` | `dict[str, Any]` | Flattened values from `.project/project.yaml` and `.project/darnit.yaml`. |
| `gathered_evidence` | `dict[str, Any]` | Evidence accumulated from earlier handlers in this control's pipeline. See [Evidence propagation](#evidence-propagation). |
| `shared_cache` | `dict[str, HandlerResult]` | Cache of shared handler results, keyed by the shared handler name. Shared handlers run once and cache their result for all controls that reference them. |
| `dependency_results` | `dict[str, Any]` | Results from dependency controls (keyed by control ID), available when control dependencies are declared in TOML. |

### HandlerResult construction

Return a `HandlerResult` with the appropriate status:

| Status | Meaning | When to use | Confidence |
|--------|---------|-------------|------------|
| `PASS` | Control satisfied | Your handler positively verified compliance | `1.0` for deterministic, `0.0–1.0` for heuristic |
| `FAIL` | Control NOT satisfied | Your handler positively verified non-compliance | `1.0` for deterministic, `0.0–1.0` for heuristic |
| `INCONCLUSIVE` | Cannot determine | Your handler can't tell — let the next handler in the pipeline try | `None` |
| `ERROR` | Handler malfunction | Your handler itself broke (not the control) — e.g., command not found, file unreadable | `None` |

```python
# PASS example — deterministic check found what it needed
HandlerResult(
    status=HandlerResultStatus.PASS,
    message="License header found in 42/42 source files",
    confidence=1.0,
    evidence={"files_checked": 42, "files_passing": 42},
)

# FAIL example — deterministic check found a violation
HandlerResult(
    status=HandlerResultStatus.FAIL,
    message="License header missing in 3 source files",
    confidence=1.0,
    evidence={"files_checked": 42, "files_failing": 3, "failing_files": ["a.py", "b.py", "c.py"]},
)

# INCONCLUSIVE — can't determine, let the next handler try
HandlerResult(
    status=HandlerResultStatus.INCONCLUSIVE,
    message="No source files found to check",
    evidence={"files_checked": 0},
)

# ERROR — the handler itself failed
HandlerResult(
    status=HandlerResultStatus.ERROR,
    message="Failed to read source directory: Permission denied",
    evidence={"error": "PermissionError: /src/"},
)
```

The `evidence` dict is free-form — put whatever is useful for debugging and for
downstream handlers. The `details` dict is for metadata that doesn't belong in evidence
(e.g., `consultation_request` for LLM handlers).

### Registering a handler

Register your handler with the `SieveHandlerRegistry` using a short name and phase
affinity:

```python
from darnit.sieve.handler_registry import get_sieve_handler_registry

registry = get_sieve_handler_registry()
registry.register(
    "license_header",              # Short name used in TOML
    phase="deterministic",         # Phase affinity (deterministic, pattern, llm, manual)
    handler_fn=license_header_handler,
    description="Check source files for license headers",
)
```

**Phase affinity** is advisory — the framework logs a warning if a handler is used in
a different phase than its registered affinity, but still executes it. Choose the
phase that best matches your handler's confidence level:

| Phase | Confidence | Typical handlers |
|-------|-----------|-----------------|
| `deterministic` | High (1.0) | File checks, API calls, config lookups |
| `pattern` | Medium (0.7–0.9) | Regex matching, heuristic analysis |
| `llm` | Variable (0.5–0.9) | AI-assisted evaluation |
| `manual` | N/A | Human verification steps |

### Registering from a plugin

When registering handlers from within an implementation, set plugin context so the
framework knows which plugin owns each handler:

```python
from darnit.sieve.handler_registry import get_sieve_handler_registry

def register_sieve_handlers(self):
    registry = get_sieve_handler_registry()
    registry.set_plugin_context(self.name)

    registry.register("license_header", "deterministic", license_header_handler,
                       description="Check source files for license headers")
    registry.register("scorecard", "deterministic", scorecard_handler,
                       description="Run OpenSSF Scorecard checks")

    registry.set_plugin_context(None)  # Always clear when done
```

Plugin handlers **override** core built-in handlers of the same name. If you register
a handler named `"exec"`, your handler replaces the built-in `exec` handler for the
duration of the audit. The framework logs a debug message about the override.

### Wiring into TOML

Reference your registered handler from a control's `[[passes]]` block. All fields
besides `handler`, `shared`, and `phase` are passed through to your handler's `config`
dict:

```toml
[controls."MS-LIC-01"]
name = "LicenseHeaders"
description = "Source files must contain license headers"
tags = { level = 1, domain = "LE" }

[[controls."MS-LIC-01".passes]]
phase = "deterministic"
handler = "license_header"           # Matches the registered name
file_extensions = [".py", ".js"]     # → config["file_extensions"]
header_pattern = "Copyright.*2024"   # → config["header_pattern"]
min_files = 1                        # → config["min_files"]

[[controls."MS-LIC-01".passes]]
phase = "manual"
handler = "manual"
steps = ["Review source files for license headers"]
```

### Evidence propagation

When a handler returns `evidence` in its `HandlerResult`, those key-value pairs are
merged into `HandlerContext.gathered_evidence` for subsequent handlers in the same
control's pipeline. This enables multi-pass pipelines:

```toml
# Pass 1: Find the file
[[controls."MS-SEC-01".passes]]
phase = "deterministic"
handler = "file_exists"
files = ["SECURITY.md", ".github/SECURITY.md"]

# Pass 2: Check the file's content (uses evidence from pass 1)
[[controls."MS-SEC-01".passes]]
phase = "pattern"
handler = "security_content_checker"
file = "$FOUND_FILE"                 # Reads from gathered_evidence["found_file"]
required_sections = ["Reporting", "Contact"]
```

In pass 2, the handler can access the found file path via:

```python
def security_content_checker(config, context):
    file_path = config.get("file", "")
    if file_path == "$FOUND_FILE":
        file_path = context.gathered_evidence.get("found_file", "")
    # ... check the file content
```

### Remediation handlers

Remediation handlers use the same signature and result type as checking handlers, with
two key differences:

1. **All handlers execute**: In a remediation phase, every handler runs even if a
   prior handler succeeded. (Checking stops on first conclusive result.)
2. **PASS means "remediation succeeded"**: Return PASS when your handler successfully
   applied the fix, FAIL if the fix could not be applied.

```python
def create_license_file(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Create a LICENSE file from a template."""
    path = os.path.join(context.local_path, config.get("path", "LICENSE"))

    if config.get("dry_run"):
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"Would create {config.get('path', 'LICENSE')}",
            evidence={"path": config.get("path", "LICENSE"), "action": "dry_run"},
        )

    content = config.get("content", "MIT License\n")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)

    return HandlerResult(
        status=HandlerResultStatus.PASS,
        message=f"Created {config.get('path', 'LICENSE')}",
        confidence=1.0,
        evidence={"path": config.get("path", "LICENSE"), "action": "created"},
    )
```

**Dry-run convention**: Check `config.get("dry_run")` and return a descriptive PASS
without performing the action. The framework passes `dry_run=True` when the user
requests a preview.

**project_update integration**: When a control's TOML defines `on_pass.project_update`,
the framework automatically updates `.project/project.yaml` after the control passes
during audit. For remediation, define `[controls."X".remediation.project_update]` to
update the config after a successful fix. See Section 3 for TOML syntax.

### Complete example: license_header handler

Here's a complete custom handler from Python function to TOML usage:

**1. The handler function** (`src/darnit_mystandard/handlers/license_check.py`):

```python
"""Custom sieve handler: check source files for license headers."""

import os
import re
from typing import Any

from darnit.sieve.handler_registry import (
    HandlerContext,
    HandlerResult,
    HandlerResultStatus,
)


def license_header_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Check that source files contain a license header.

    Config fields:
        file_extensions: list[str] - Extensions to check (e.g., [".py", ".js"])
        header_pattern: str - Regex pattern for the license header
        min_files: int - Minimum files that must have headers (default: 1)
    """
    extensions = config.get("file_extensions", [".py"])
    pattern = config.get("header_pattern", r"Copyright")
    min_files = config.get("min_files", 1)

    source_files = []
    for root, _dirs, files in os.walk(context.local_path):
        # Skip hidden directories and common non-source dirs
        if any(part.startswith(".") for part in root.split(os.sep)):
            continue
        for f in files:
            if any(f.endswith(ext) for ext in extensions):
                source_files.append(os.path.join(root, f))

    if not source_files:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message=f"No source files found with extensions {extensions}",
            evidence={"extensions": extensions, "files_found": 0},
        )

    passing = []
    failing = []
    for filepath in source_files:
        try:
            with open(filepath, encoding="utf-8", errors="ignore") as fh:
                # Only check first 20 lines for license header
                head = "".join(fh.readline() for _ in range(20))
            if re.search(pattern, head):
                passing.append(filepath)
            else:
                failing.append(filepath)
        except OSError:
            failing.append(filepath)

    evidence = {
        "files_checked": len(source_files),
        "files_passing": len(passing),
        "files_failing": len(failing),
        "failing_files": [os.path.relpath(f, context.local_path) for f in failing[:10]],
    }

    if len(passing) >= min_files and not failing:
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"License header found in {len(passing)}/{len(source_files)} files",
            confidence=1.0,
            evidence=evidence,
        )
    elif failing:
        return HandlerResult(
            status=HandlerResultStatus.FAIL,
            message=f"License header missing in {len(failing)}/{len(source_files)} files",
            confidence=1.0,
            evidence=evidence,
        )
    else:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message=f"Only {len(passing)} files have headers (need {min_files})",
            evidence=evidence,
        )
```

**2. Registration** (in your implementation's initialization):

```python
from darnit.sieve.handler_registry import get_sieve_handler_registry
from .handlers.license_check import license_header_handler

registry = get_sieve_handler_registry()
registry.set_plugin_context("mystandard")
registry.register("license_header", "deterministic", license_header_handler,
                   description="Check source files for license headers")
registry.set_plugin_context(None)
```

**3. TOML wiring** (in `mystandard.toml`):

```toml
[controls."MS-LE-01"]
name = "LicenseHeaders"
description = "All source files must contain a license header"
tags = { level = 2, domain = "LE" }

[[controls."MS-LE-01".passes]]
phase = "deterministic"
handler = "license_header"
file_extensions = [".py", ".js", ".ts"]
header_pattern = 'Copyright\s+\d{4}'
min_files = 1

[[controls."MS-LE-01".passes]]
phase = "manual"
handler = "manual"
steps = ["Review source files for license headers", "Verify header matches project license"]
```

**4. Expected audit output**:

Pass case:
```
MS-LE-01  PASS  License header found in 15/15 files  (deterministic, confidence=1.0)
```

Fail case:
```
MS-LE-01  FAIL  License header missing in 3/15 files  (deterministic, confidence=1.0)
```

> **Reference**: See `packages/darnit/src/darnit/sieve/builtin_handlers.py` for the
> framework's built-in handler implementations (`file_exists`, `exec`, `regex`, etc.).

---

## 6. Custom Sieve Handlers

When the built-in TOML handler types (`file_exists`, `exec`, `regex`, `manual`)
aren't expressive enough — for example, when you need custom API calls, complex
multi-step logic, or content analysis — write a custom sieve handler in Python
and reference it from TOML.

### Writing a custom handler

A sieve handler is a function with signature
`(config: dict, context: HandlerContext) -> HandlerResult`:

```python
# src/darnit_mystandard/handlers.py
from darnit.sieve.handler_registry import (
    HandlerContext,
    HandlerResult,
    HandlerResultStatus,
)


def api_check_handler(config: dict, context: HandlerContext) -> HandlerResult:
    """Check repository visibility via GitHub API."""
    import json
    import subprocess

    result = subprocess.run(
        ["gh", "api", f"/repos/{context.owner}/{context.repo}"],
        capture_output=True, text=True, timeout=30,
    )

    if result.returncode != 0:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message="Could not reach API",
        )

    data = json.loads(result.stdout)
    if data.get("private") is False:
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message="Repository is public",
            confidence=1.0,
            evidence={"private": False},
        )
    return HandlerResult(
        status=HandlerResultStatus.FAIL,
        message="Repository is private",
        evidence={"private": True},
    )
```

### Registering the handler

Register handlers in your implementation's `register_sieve_handlers()` method:

```python
def register_sieve_handlers(self) -> None:
    from darnit.sieve.handler_registry import get_sieve_handler_registry
    from . import handlers

    registry = get_sieve_handler_registry()
    registry.set_plugin_context(self.name)
    registry.register("api_check", "deterministic", handlers.api_check_handler,
                       "Check repository via API")
    registry.set_plugin_context(None)
```

### Referencing from TOML

Once registered, reference the handler by short name in your framework TOML:

```toml
[[controls."MS-AC-01".passes]]
handler = "api_check"

[[controls."MS-AC-01".passes]]
handler = "manual"
steps = [
    "Check repository visibility in Settings",
    "Verify repository is not private",
]
```

> **Reference**: See `packages/darnit-example/src/darnit_example/handlers.py` for
> real custom handler examples (readme analysis, CI config detection).

---

## 7. Remediation

Remediation maps audit failures to automated fix actions. The registry tells the
framework which function to call when a control fails.

### Registry structure

```python
# src/darnit_mystandard/remediation/registry.py
from typing import Any

REMEDIATION_REGISTRY: dict[str, dict[str, Any]] = {
    "security_policy": {
        "description": "Create SECURITY.md with vulnerability reporting info",
        "controls": ["MS-SEC-01", "MS-SEC-02"],
        "function": "create_security_policy",
        "safe": True,           # Safe to auto-apply without confirmation
        "requires_api": False,  # Doesn't need GitHub API access
    },
    "branch_protection": {
        "description": "Enable branch protection rules",
        "controls": ["MS-AC-02", "MS-AC-03"],
        "function": "enable_branch_protection",
        "safe": True,
        "requires_api": True,
    },
}
```

### Registry fields

| Field | Type | Purpose |
|-------|------|---------|
| `description` | `str` | Human-readable description of the fix |
| `controls` | `list[str]` | Control IDs this remediation addresses |
| `function` | `str` | Name of the function to call |
| `safe` | `bool` | Whether auto-application is safe |
| `requires_api` | `bool` | Whether the fix needs API access |
| `requires_context` | `list[dict]` | Context values needed before applying |

### Context requirements

Some remediations need user-confirmed context before they can run:

```python
"codeowners": {
    "description": "Create CODEOWNERS file",
    "controls": ["MS-GV-01"],
    "function": "create_codeowners",
    "safe": True,
    "requires_api": False,
    "requires_context": [{
        "key": "maintainers",
        "required": True,
        "confidence_threshold": 0.9,
        "prompt_if_auto_detected": True,
        "warning": "Please confirm who should be code owners.",
    }],
},
```

### Remediation action functions

The actual remediation functions are defined separately and invoked by name from the
registry. They typically create or modify files in the repository:

```python
# src/darnit_mystandard/remediation/actions.py

def create_security_policy(owner: str, repo: str, local_path: str, **kwargs) -> dict:
    """Create a SECURITY.md file.

    Returns:
        dict with keys: success (bool), message (str), files_created (list)
    """
    import os

    security_path = os.path.join(local_path, "SECURITY.md")
    if os.path.exists(security_path):
        return {
            "success": True,
            "message": "SECURITY.md already exists",
            "files_created": [],
        }

    content = f"# Security Policy\n\nReport vulnerabilities to security@{owner}.example.com\n"
    with open(security_path, "w") as f:
        f.write(content)

    return {
        "success": True,
        "message": "Created SECURITY.md",
        "files_created": ["SECURITY.md"],
    }
```

> **Reference**: See `packages/darnit-baseline/src/darnit_baseline/remediation/registry.py`
> for the full OpenSSF Baseline remediation registry with 11 categories.

---

## 8. MCP Tools

MCP tools are functions exposed to AI assistants (Claude, etc.) via the Model Context
Protocol. There are two ways to provide them: built-in tools (TOML-only) and custom
handler tools (requires Python).

### Built-in MCP tools

The framework provides generic built-in tools that work with any TOML-defined
framework. Reference them with `builtin = "..."` instead of `handler = "..."`:

```toml
[mcp.tools.audit]
builtin = "audit"
description = "Run compliance audit"

[mcp.tools.remediate]
builtin = "remediate"
description = "Auto-fix failing controls"

[mcp.tools.list_controls]
builtin = "list_controls"
description = "List all controls by level"
```

Available built-in tools:

| Name | What it does |
|------|-------------|
| `audit` | Load controls from this framework's TOML, run sieve on each, return formatted report |
| `remediate` | Run audit, then apply declarative remediations (file_create, exec, api_call) for failures |
| `list_controls` | Return JSON list of all controls grouped by level |

Built-in tools automatically receive the framework name from the `[metadata]` section,
so they know which TOML to load. They support `local_path`, `level`, and `dry_run`
parameters.

Use built-in tools when your framework only needs standard audit/remediate behavior.
Use custom handler tools (below) when you need additional parameters, custom output
formats, or specialized logic.

### Custom handler tools

If your implementation provides custom MCP tools, register them through the handler
system.

### The register_handlers() method

This is an **optional** method on your implementation class. The framework checks
for it with `hasattr()` before calling:

```python
# In implementation.py

def register_handlers(self) -> None:
    """Register MCP tool handlers."""
    from darnit.core.handlers import get_handler_registry
    from . import tools

    registry = get_handler_registry()
    registry.set_plugin_context(self.name)

    # Register each handler by short name
    registry.register_handler("audit_mystandard", tools.audit_mystandard)
    registry.register_handler("list_checks", tools.list_checks)

    # Clear plugin context when done
    registry.set_plugin_context(None)
```

### How it works

1. `set_plugin_context(self.name)` — tells the registry which plugin is registering
   handlers (for audit trails)
2. `register_handler("name", func)` — registers the function under a short name
3. `set_plugin_context(None)` — clears the context

Handlers can then be referenced in TOML by short name:

```toml
[mcp.tools.audit_mystandard]
handler = "audit_mystandard"
```

Or by full module path:

```toml
[mcp.tools.audit_mystandard]
handler = "darnit_mystandard.tools:audit_mystandard"
```

### Module allowlist security

When handlers are referenced by `module:function` path in TOML, the registry only
allows imports from approved module prefixes. The default allowlist in
`packages/darnit/src/darnit/core/handlers.py`:

```python
ALLOWED_MODULE_PREFIXES = (
    "darnit.",
    "darnit_baseline.",
    "darnit_testchecks.",
)
```

If your implementation uses `module:function` references, you'll need to add your
module prefix to this allowlist. Using short names (via `register_handler()`) avoids
this restriction entirely.

> **Reference**: See `packages/darnit-baseline/src/darnit_baseline/implementation.py:92`
> for the OpenSSF Baseline's `register_handlers()` method and
> `packages/darnit/src/darnit/core/handlers.py` for the full handler registry.

---

## 9. Testing

### Protocol compliance tests

Verify your implementation satisfies the `ComplianceImplementation` protocol:

```python
# tests/test_mystandard/test_implementation.py
from darnit.core.plugin import ComplianceImplementation
from darnit_mystandard.implementation import MyStandardImplementation


def test_implements_protocol():
    impl = MyStandardImplementation()
    assert isinstance(impl, ComplianceImplementation)


def test_properties():
    impl = MyStandardImplementation()
    assert impl.name == "mystandard"
    assert impl.display_name == "My Compliance Standard"
    assert impl.version == "0.1.0"
    assert impl.spec_version == "MySpec v1.0"


def test_get_framework_config_path():
    impl = MyStandardImplementation()
    path = impl.get_framework_config_path()
    assert path is not None
    assert path.name == "mystandard.toml"
    # Verify the file actually exists at this path
    assert path.exists(), f"TOML not found at {path}"
```

### Control unit tests

Test individual controls by mocking external dependencies:

```python
# tests/test_mystandard/test_controls.py
from darnit.sieve.models import CheckContext, PassOutcome


def _make_context(tmp_path, **kwargs):
    """Create a CheckContext for testing."""
    return CheckContext(
        owner="test-owner",
        repo="test-repo",
        local_path=str(tmp_path),
        default_branch="main",
        control_id="MS-DOC-01",
        **kwargs,
    )


def test_readme_exists_pass(tmp_path):
    """README check passes when README.md exists."""
    (tmp_path / "README.md").write_text("# My Project")

    from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus
    from darnit_mystandard.handlers import readme_check_handler

    ctx = HandlerContext(local_path=str(tmp_path))
    result = readme_check_handler({}, ctx)

    assert result.status == HandlerResultStatus.PASS


def test_readme_exists_fail(tmp_path):
    """README check fails when no README exists."""
    from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus
    from darnit_mystandard.handlers import readme_check_handler

    ctx = HandlerContext(local_path=str(tmp_path))
    result = readme_check_handler({}, ctx)

    assert result.status == HandlerResultStatus.FAIL
```

### Testing API-based handlers

Mock the subprocess calls to avoid hitting real APIs:

```python
from unittest.mock import patch
import json


def test_api_check_pass(tmp_path):
    """API handler passes when API returns expected data."""
    mock_response = json.dumps({"private": False})

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = mock_response

        from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus
        from darnit_mystandard.handlers import api_check_handler

        ctx = HandlerContext(local_path=str(tmp_path))
        result = api_check_handler({}, ctx)

        assert result.status == HandlerResultStatus.PASS
```

### Integration tests

Test the full audit pipeline end-to-end:

```python
def test_full_audit(tmp_path):
    """Run a complete audit against a test repository."""
    # Set up minimal repo structure
    (tmp_path / "README.md").write_text("# Test")
    (tmp_path / "LICENSE").write_text("MIT License")
    (tmp_path / "SECURITY.md").write_text("Report to security@test.com")

    from darnit_mystandard.implementation import MyStandardImplementation
    impl = MyStandardImplementation()

    # Register controls
    impl.register_controls()

    # Get controls and verify they loaded
    controls = impl.get_all_controls()
    assert len(controls) > 0
```

### Test organization

```
tests/
├── test_mystandard/
│   ├── __init__.py
│   ├── test_implementation.py   # Protocol compliance
│   ├── test_controls.py         # Individual control logic
│   ├── test_remediation.py      # Remediation actions
│   └── conftest.py              # Shared fixtures
└── integration/
    └── test_full_audit.py       # End-to-end (may need network)
```

> **Reference**: See `tests/darnit_baseline/` for the OpenSSF Baseline test suite.

---

## 10. Common Pitfalls

### Handler function signature

**Problem**: Writing a handler that doesn't match the expected signature
`(config: dict, context: HandlerContext) -> HandlerResult`.

```python
# WRONG: Missing config parameter
def my_handler(context):
    ...

# WRONG: Returning a plain dict instead of HandlerResult
def my_handler(config, context):
    return {"status": "pass"}

# CORRECT: Full signature with HandlerResult return type
def my_handler(config: dict, context: HandlerContext) -> HandlerResult:
    return HandlerResult(
        status=HandlerResultStatus.PASS,
        message="Check passed",
        confidence=1.0,
    )
```

### Module allowlist for dynamic loading

If you reference handlers by `module:function` path in TOML, the handler registry
enforces a module allowlist. Your module must start with an approved prefix
(`darnit.`, `darnit_baseline.`, `darnit_testchecks.`). For new implementations,
either:

1. Use short names via `register_handler()` (recommended), or
2. Add your module prefix to `HandlerRegistry.ALLOWED_MODULE_PREFIXES`

### TOML path resolution

`get_framework_config_path()` returns a path relative to `implementation.py`.
Count the `parent` traversals carefully:

```python
# From: src/darnit_mystandard/implementation.py
# To:   mystandard.toml (at package root)
Path(__file__).parent  # → src/darnit_mystandard/
             .parent   # → src/
             .parent   # → darnit-mystandard/
             / "mystandard.toml"
```

If this path is wrong, the framework silently falls back to an empty config.
Add an assertion in your tests to catch this early.

### Entry point naming conventions

The entry point name in `pyproject.toml` becomes the key used to look up your
implementation:

```toml
[project.entry-points."darnit.implementations"]
mystandard = "darnit_mystandard:register"
#  ↑ This name must match impl.name
```

If the entry point name doesn't match `impl.name`, discovery will still work but
the implementation will be stored under `impl.name`, not the entry point name.
Keep them consistent.

### Control registration is global

`register_control()` writes to a global registry. If multiple implementations
register a control with the same ID, only the first one wins (duplicates are
skipped). If you need to override, use the `overwrite=True` parameter:

```python
from darnit.sieve.registry import get_control_registry
registry = get_control_registry()
registry.register(my_spec, overwrite=True)
```

### Pass ordering validation

The sieve `ControlSpec` validates that passes are in phase order
(DETERMINISTIC → PATTERN → LLM → MANUAL). If passes are out of order,
a warning is emitted. While not an error, out-of-order passes may produce
unexpected results since the orchestrator assumes the order.

---

## 11. Quick Reference

### ComplianceImplementation protocol

```
Properties:  name, display_name, version, spec_version
Methods:     get_all_controls(), get_controls_by_level(level),
             get_rules_catalog(), get_remediation_registry(),
             get_framework_config_path(), register_controls()
Optional:    register_handlers()
```

### Handler type cheat sheet

| Need | TOML Handler | Notes |
|------|-------------|-------|
| File exists? | `handler = "file_exists"` + `files = [...]` | Also accepts `file_must_exist` alias |
| CLI/API check? | `handler = "exec"` + `command = [...]` + `expr = "..."` | CEL expression on output |
| Regex in file? | `handler = "pattern"` + `file_patterns = [...]` | Also accepts `regex` alias |
| AI analysis? | `handler = "llm_eval"` + `confidence_threshold = 0.8` | Requires LLM consultation |
| Human steps? | `handler = "manual"` + `steps = [...]` | Also accepts `manual_steps` alias |
| Custom logic? | `handler = "my_handler"` | Register via `SieveHandlerRegistry` (Section 6) |

### Key imports

```python
# Sieve handler authoring (Section 5-6)
from darnit.sieve.handler_registry import (
    HandlerContext, HandlerResult, HandlerResultStatus,
    get_sieve_handler_registry,
)

# Models
from darnit.sieve.models import (
    CheckContext, ControlSpec, PassOutcome, PassResult, VerificationPhase,
)

# Control registration
from darnit.sieve.registry import register_control

# Protocol (for isinstance checks)
from darnit.core.plugin import ComplianceImplementation, ControlSpec as PluginControlSpec

# MCP tool handler registration (Section 8)
from darnit.core.handlers import get_handler_registry
```

### Key file paths

| What | Path |
|------|------|
| Protocol definition | `packages/darnit/src/darnit/core/plugin.py` |
| Plugin discovery | `packages/darnit/src/darnit/core/discovery.py` |
| Sieve models | `packages/darnit/src/darnit/sieve/models.py` |
| Control registry | `packages/darnit/src/darnit/sieve/registry.py` |
| Sieve handler registry | `packages/darnit/src/darnit/sieve/handler_registry.py` |
| Built-in sieve handlers | `packages/darnit/src/darnit/sieve/builtin_handlers.py` |
| MCP tool handler registry | `packages/darnit/src/darnit/core/handlers.py` |
| Reference implementation | `packages/darnit-baseline/src/darnit_baseline/implementation.py` |
| Reference TOML | `packages/darnit-baseline/openssf-baseline.toml` |
| Reference remediation | `packages/darnit-baseline/src/darnit_baseline/remediation/registry.py` |
| Example implementation | `packages/darnit-example/src/darnit_example/implementation.py` |
| Example TOML config | `packages/darnit-example/example-hygiene.toml` |
| Example custom handlers | `packages/darnit-example/src/darnit_example/handlers.py` |
| Example tests | `tests/darnit_example/` |
| Framework spec | `openspec/specs/framework-design/spec.md` |
