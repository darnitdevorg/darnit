# Design: Interactive Context Collection System

> **⚠️ Note: Spec Under Development**
>
> The CNCF `.project/` specification and extension mechanism ([PR #131](https://github.com/cncf/automation/pull/131)) are still under active development and have not been finalized. The design in this document aligns with the current draft but **may change significantly** as the upstream spec evolves. Implementation should be prepared for breaking changes.

## Overview

This document describes enhancements to the darnit context system that enable:
1. **Declarative context prompts** defined in TOML framework files
2. **Structured context storage** in `.project/` directory following CNCF conventions
3. **Interactive prompt flow** where MCP tools can request user input
4. **Progressive auto-detection** via the Context Sieve (see [CONTEXT_SIEVE_DESIGN.md](./CONTEXT_SIEVE_DESIGN.md))

## Context Sieve Integration (Implemented)

The Context Sieve provides automatic detection of context before prompting users:

```text
┌─────────────────────────────────────────────────────────────────┐
│                         DETECTION FLOW                           │
├─────────────────────────────────────────────────────────────────┤
│  1. Check .project.yaml for USER_CONFIRMED context               │
│                     │                                            │
│            found? ──┼──► Use stored value                        │
│                     │ NO                                         │
│                     ▼                                            │
│  2. Run Context Sieve (progressive auto-detection)               │
│     ├─ Deterministic: MAINTAINERS.md, CODEOWNERS                 │
│     ├─ Heuristic: package.json, git history                      │
│     └─ API: GitHub collaborators                                 │
│                     │                                            │
│            usable? ─┼──► Show auto-detected with confidence      │
│                     │ NO                                         │
│                     ▼                                            │
│  3. Prompt user for confirmation/input                           │
└─────────────────────────────────────────────────────────────────┘
```

**Key files:**
- `packages/darnit/src/darnit/context/sieve.py` - Progressive detection
- `packages/darnit/src/darnit/context/confidence.py` - Confidence scoring
- `packages/darnit/src/darnit/remediation/context_validator.py` - Integration

## CNCF .project Specification Alignment

The `.project/` directory follows the [CNCF .project specification](https://github.com/cncf/automation/tree/main/utilities/dot-project).
Extensions use the mechanism defined in [PR #131](https://github.com/cncf/automation/pull/131).

### Extension Format (schema_version 1.1.0+)
```yaml
schema_version: "1.1.0"
extensions:
  openssf-baseline:
    metadata:
      author: "OpenSSF"
      homepage: "https://baseline.openssf.org"
      version: "0.1.0"
    config:
      # Tool-specific configuration
      context:
        has_releases: true
        ci_provider: github
```

## Current State

### Context Keys (Hardcoded in Python)
```python
# packages/darnit/src/darnit/sieve/project_context.py
CONTEXT_KEYS = {
    "has_subprojects": {"affects": [...], "prompt": "..."},
    "has_releases": {"affects": [...], "prompt": "..."},
    # ...
}
```

### Context Storage (Legacy - in .project.yaml)
```yaml
# DEPRECATED: x- prefix pattern
x-openssf-baseline:
  context:
    has_releases: true
    ci_provider: github
```

### Problems
1. Context keys are hardcoded - can't add new ones without Python code changes
2. No structured prompts with hints, examples, or validation
3. No way to define context requirements per-control in TOML
4. Context stored in monolithic `.project.yaml` rather than modular `.project/`
5. Uses deprecated `x-` prefix instead of CNCF `extensions:` pattern

---

## Proposed Design

### 1. TOML Schema: Context Definitions

Add a `[context]` section to the framework TOML:

```toml
# openssf-baseline.toml

[context]
# Global context definitions reusable across controls

[context.has_releases]
type = "boolean"
prompt = "Does this project make official releases?"
hint = "Official releases include versioned tags, published packages, or downloadable binaries"
affects = ["OSPS-BR-02.01", "OSPS-BR-04.01", "OSPS-BR-06.01"]

[context.maintainers]
type = "list_or_path"  # Can be ["user1", "user2"] or "MAINTAINERS.md"
prompt = "Who are the project maintainers?"
hint = "Provide GitHub usernames, email addresses, or path to MAINTAINERS.md"
examples = ["@user1, @user2", "MAINTAINERS.md", "See CODEOWNERS"]
affects = ["OSPS-GV-01.01", "OSPS-GV-01.02", "OSPS-GV-04.01"]
store_as = "governance.maintainers"  # Where to store in .project/

[context.security_contact]
type = "string"
prompt = "What is the security contact for vulnerability reports?"
hint = "Email address, URL, or reference to SECURITY.md section"
examples = ["security@example.com", "https://hackerone.com/example"]
affects = ["OSPS-VM-01.01", "OSPS-VM-03.01"]
store_as = "security.contact"

[context.ci_provider]
type = "enum"
prompt = "What CI/CD system does this project use?"
values = ["github", "gitlab", "jenkins", "circleci", "azure", "travis", "none", "other"]
affects = ["OSPS-BR-01.01", "OSPS-AC-04.01", "OSPS-QA-06.01"]
auto_detect = true  # Can be auto-detected from repo structure

[context.governance_model]
type = "enum"
prompt = "What governance model does this project use?"
values = ["bdfl", "meritocracy", "democracy", "corporate", "foundation", "other"]
hint = "BDFL = single maintainer, meritocracy = earned commit access, etc."
affects = ["OSPS-GV-01.01"]
store_as = "governance.model"
```

### 2. Per-Control Context Requirements

Controls can reference context they need:

```toml
[controls."OSPS-GV-01.01"]
name = "DocumentedRoles"
description = "Project roles and responsibilities are documented"

# Context this control needs
requires_context = ["maintainers", "governance_model"]

# What happens if context is missing
on_missing_context = "warn"  # warn | fail | skip | prompt

# Custom prompt for this specific control
[controls."OSPS-GV-01.01".context_prompt]
message = "To verify governance documentation, we need to know:"
fields = ["maintainers", "governance_model"]
```

### 3. Context Types

| Type | Description | Validation | Storage |
|------|-------------|------------|---------|
| `boolean` | Yes/No question | `true`/`false` | Direct value |
| `string` | Free text | Non-empty | Direct value |
| `enum` | One of predefined values | Must match `values` | Direct value |
| `list` | Multiple values | Array of strings | Array |
| `path` | File path | Must exist (optional) | Path reference |
| `list_or_path` | Either list or path | Either valid | Smart storage |
| `email` | Email address | RFC 5322 | String |
| `url` | URL | Valid URL | String |

### 4. .project/ Directory Structure (CNCF Compliant)

Move from monolithic `.project.yaml` to modular `.project/` following CNCF conventions:

```
.project/
├── project.yaml              # Core CNCF metadata (schema_version 1.1.0+)
├── extensions/               # Extension-specific directories
│   └── openssf-baseline/     # OpenSSF Baseline extension
│       ├── config.yaml       # Extension configuration
│       ├── context/          # User-confirmed context
│       │   ├── governance.yaml
│       │   ├── security.yaml
│       │   ├── build.yaml
│       │   └── releases.yaml
│       └── evidence/         # Cached evidence (gitignored)
│           ├── branch-protection.json
│           └── ci-workflows.json
└── .gitignore                # Ignore evidence/ directories
```

**Alternative: Single-file extension** (for simpler projects):
```
.project/
├── project.yaml              # Core CNCF metadata with extensions: section
└── .gitignore
```

The `extensions:` block in `project.yaml` can contain all config inline:
```yaml
schema_version: "1.1.0"
name: "my-project"
extensions:
  openssf-baseline:
    metadata:
      author: "OpenSSF"
      homepage: "https://baseline.openssf.org"
    config:
      context:
        has_releases: true
        ci_provider: github
      controls:
        OSPS-BR-02.01:
          status: not_applicable
          reason: "No releases yet"
```

### 5. Context Storage Schema (CNCF Extension Format)

**Option A: Inline in `.project/project.yaml`** (recommended for most projects):
```yaml
schema_version: "1.1.0"
name: "my-project"
extensions:
  openssf-baseline:
    metadata:
      author: "OpenSSF"
      homepage: "https://baseline.openssf.org"
      version: "0.1.0"
    config:
      # User-confirmed context with provenance
      context:
        governance:
          maintainers:
            source: "user_confirmed"
            value: ["@mlieberman85", "@contributor2"]
            confirmed_at: "2025-01-26T10:30:00Z"
          governance_model:
            source: "user_confirmed"
            value: "bdfl"
            confirmed_at: "2025-01-26T10:30:00Z"
          codeowners_path:
            source: "auto_detected"
            value: ".github/CODEOWNERS"
            detected_at: "2025-01-26T10:00:00Z"
        security:
          security_contact:
            source: "user_confirmed"
            value: "security@example.com"
            confirmed_at: "2025-01-26T10:30:00Z"
          private_vuln_reporting:
            source: "auto_detected"
            value: true
            detected_at: "2025-01-26T10:00:00Z"
            detection_method: "github_api"
        build:
          ci_provider:
            source: "auto_detected"
            value: "github"
            detected_at: "2025-01-26T10:00:00Z"
          has_releases:
            source: "user_confirmed"
            value: true
            confirmed_at: "2025-01-26T10:30:00Z"
      # Control overrides
      controls:
        OSPS-BR-02.01:
          status: "not_applicable"
          reason: "Project does not make releases"
```

**Option B: Separate files** (for large projects or complex context):

**`.project/extensions/openssf-baseline/context/governance.yaml`**:
```yaml
# User-confirmed governance context
# Updated by: confirm_project_context MCP tool
maintainers:
  source: "user_confirmed"
  value: ["@mlieberman85", "@contributor2"]
  confirmed_at: "2025-01-26T10:30:00Z"

governance_model:
  source: "user_confirmed"
  value: "bdfl"
  confirmed_at: "2025-01-26T10:30:00Z"

codeowners_path:
  source: "auto_detected"
  value: ".github/CODEOWNERS"
  detected_at: "2025-01-26T10:00:00Z"
```

**`.project/extensions/openssf-baseline/context/security.yaml`**:
```yaml
security_contact:
  source: "user_confirmed"
  value: "security@example.com"
  confirmed_at: "2025-01-26T10:30:00Z"

private_vuln_reporting:
  source: "auto_detected"
  value: true
  detected_at: "2025-01-26T10:00:00Z"
  detection_method: "github_api"
```

**Context Value Sources**:
| Source | Description | Confidence |
|--------|-------------|------------|
| `user_confirmed` | Explicitly confirmed by user via MCP tool | 1.0 |
| `auto_detected` | Automatically detected from repo structure | 0.7-0.9 |
| `file_reference` | Points to a file containing the information | 0.9 |
| `default` | Default value when no other source available | 0.5 |

### 6. Pydantic Models (CNCF Extension Compatible)

```python
# packages/darnit/src/darnit/config/context_schema.py

from enum import Enum
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ContextSource(str, Enum):
    """Source/provenance of a context value."""
    USER_CONFIRMED = "user_confirmed"
    AUTO_DETECTED = "auto_detected"
    FILE_REFERENCE = "file_reference"
    DEFAULT = "default"


class ContextValue(BaseModel):
    """A single context value with provenance tracking."""
    source: ContextSource
    value: Any
    confirmed_at: Optional[datetime] = None
    detected_at: Optional[datetime] = None
    detection_method: Optional[str] = None
    confidence: float = 1.0  # 0.0-1.0, lower for auto-detected


class ContextType(str, Enum):
    """Supported context value types."""
    BOOLEAN = "boolean"
    STRING = "string"
    ENUM = "enum"
    LIST = "list"
    PATH = "path"
    LIST_OR_PATH = "list_or_path"
    EMAIL = "email"
    URL = "url"


class ContextDefinition(BaseModel):
    """Definition of a context key from TOML framework file."""
    type: ContextType
    prompt: str
    hint: Optional[str] = None
    examples: List[str] = Field(default_factory=list)
    values: Optional[List[str]] = None  # For enum type
    affects: List[str] = Field(default_factory=list)
    store_as: Optional[str] = None  # e.g., "governance.maintainers"
    auto_detect: bool = False
    required: bool = False


class ContextPromptRequest(BaseModel):
    """Request for user input on a context value."""
    key: str
    definition: ContextDefinition
    control_ids: List[str]  # Controls that need this
    current_value: Optional[ContextValue] = None  # If auto-detected
    priority: int = 0  # Higher = more important


# CNCF Extension Models

class ExtensionMetadata(BaseModel):
    """Metadata for a CNCF .project extension."""
    author: str
    homepage: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None


class ContextCategory(BaseModel):
    """A category of context values (governance, security, build, etc.)."""
    # Dynamic dict of context key -> ContextValue
    # Validated at runtime based on ContextDefinitions
    pass


class BaselineExtensionConfig(BaseModel):
    """Configuration for the openssf-baseline extension."""
    context: Optional[Dict[str, Dict[str, ContextValue]]] = None  # category -> key -> value
    controls: Optional[Dict[str, Any]] = None  # control_id -> override


class BaselineExtension(BaseModel):
    """CNCF-compliant openssf-baseline extension."""
    metadata: ExtensionMetadata
    config: BaselineExtensionConfig


class ProjectExtensions(BaseModel):
    """All extensions in a .project file."""
    openssf_baseline: Optional[BaselineExtension] = Field(
        default=None, alias="openssf-baseline"
    )
    # Other extensions can be added here


class CNCFProjectConfig(BaseModel):
    """CNCF .project/project.yaml schema (v1.1.0+)."""
    schema_version: str = "1.1.0"
    name: Optional[str] = None
    description: Optional[str] = None
    extensions: Optional[ProjectExtensions] = None
```

### 7. Framework Schema Extensions

```python
# packages/darnit/src/darnit/config/framework_schema.py

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ContextConfig(BaseModel):
    """Context definitions from framework TOML."""
    definitions: Dict[str, ContextDefinition] = Field(default_factory=dict)


class ControlContextConfig(BaseModel):
    """Context requirements for a control."""
    requires_context: List[str] = Field(default_factory=list)
    on_missing_context: str = "warn"  # warn | fail | skip | prompt
    custom_prompt: Optional[str] = None


class FrameworkConfig(BaseModel):
    """Extended framework config with context support."""
    metadata: MetadataConfig
    defaults: DefaultsConfig
    templates: Dict[str, str]
    context: ContextConfig = Field(default_factory=ContextConfig)  # NEW
    controls: Dict[str, ControlConfig]


# packages/darnit/src/darnit/config/project_loader.py

def load_project_config(local_path: str) -> Optional[CNCFProjectConfig]:
    """Load project configuration from .project/ directory.

    Supports both legacy (.project.yaml with x- prefix) and
    CNCF-compliant (.project/project.yaml with extensions:) formats.

    Priority:
    1. .project/project.yaml (CNCF format)
    2. .project.yaml (legacy format, auto-migrated)
    """
    project_dir = Path(local_path) / ".project"
    project_yaml = project_dir / "project.yaml"
    legacy_yaml = Path(local_path) / ".project.yaml"

    if project_yaml.exists():
        return _load_cncf_config(project_yaml)
    elif legacy_yaml.exists():
        return _migrate_legacy_config(legacy_yaml)
    return None
```

### 8. MCP Tool: confirm_project_context (Enhanced)

```python
def confirm_project_context(
    local_path: str = ".",
    # Existing params
    has_subprojects: Optional[bool] = None,
    has_releases: Optional[bool] = None,
    is_library: Optional[bool] = None,
    has_compiled_assets: Optional[bool] = None,
    ci_provider: Optional[str] = None,
    # NEW params
    maintainers: Optional[Union[List[str], str]] = None,
    security_contact: Optional[str] = None,
    governance_model: Optional[str] = None,
    # Generic context setting
    context_key: Optional[str] = None,
    context_value: Optional[Any] = None,
) -> str:
    """
    Record user-confirmed project context in .project/context/.

    Args:
        local_path: Path to repository
        maintainers: List of maintainers or path to MAINTAINERS.md
        security_contact: Security contact email or URL
        governance_model: One of: bdfl, meritocracy, democracy, corporate, other
        context_key: Generic context key to set
        context_value: Value for generic context key

    Returns:
        Confirmation message with what was updated
    """
```

### 9. MCP Tool: get_pending_context

```python
def get_pending_context(
    local_path: str = ".",
    control_ids: Optional[List[str]] = None,
) -> str:
    """
    Get list of context that would improve audit accuracy.

    Returns structured list of prompts for missing/uncertain context.

    Example output:
    ```
    ## Context Needed for Better Audit Results

    ### High Priority (affects 5+ controls)

    **maintainers** - Who are the project maintainers?
    - Hint: Provide GitHub usernames, email addresses, or path to MAINTAINERS.md
    - Examples: "@user1, @user2" or "MAINTAINERS.md"
    - Affects: OSPS-GV-01.01, OSPS-GV-01.02, OSPS-GV-04.01
    - Use: `confirm_project_context(maintainers=["@user1", "@user2"])`

    ### Medium Priority (affects 2-4 controls)

    **governance_model** - What governance model does this project use?
    ...
    ```
    """
```

### 10. Audit Output Integration

When audit runs, include context prompts in output:

```python
def format_audit_markdown(results, pending_context):
    output = format_results(results)

    if pending_context:
        output += "\n\n---\n\n"
        output += "## 🤔 Help Improve This Audit\n\n"
        output += "The following information would help verify additional controls:\n\n"

        for ctx in sorted(pending_context, key=lambda x: -len(x['affects'])):
            output += f"### {ctx['key']}\n"
            output += f"**Question:** {ctx['prompt']}\n"
            if ctx.get('hint'):
                output += f"- *Hint:* {ctx['hint']}\n"
            if ctx.get('examples'):
                output += f"- *Examples:* {', '.join(ctx['examples'])}\n"
            output += f"- *Affects:* {', '.join(ctx['affects'])}\n"
            output += f"- *Set with:* `confirm_project_context({ctx['key']}=...)`\n\n"

    return output
```

---

## Implementation Plan

> **⚠️ Implementation Note**: Since the CNCF `.project/` spec is still evolving, consider:
> - Abstracting the storage layer so format changes are isolated
> - Keeping the legacy `x-openssf-baseline` format as a stable fallback
> - Monitoring [cncf/automation](https://github.com/cncf/automation) for spec updates

### Phase 1: CNCF Extension Models ✅ COMPLETE
1. ✅ Add CNCF-compliant Pydantic models to `config/schema.py`
2. ✅ Add `ContextDefinition`, `ContextValue`, `ContextSource` models
3. ✅ Create `CNCFProjectConfig` model with `extensions:` support
4. ✅ Maintain backward compatibility with `x-openssf-baseline` format

### Phase 2: TOML Context Definitions ✅ COMPLETE
1. ✅ Add `ContextConfig` to `framework_schema.py`
2. ✅ Add `[context]` section support to TOML loader
3. ✅ Update `openssf-baseline.toml` with context definitions

### Phase 3: .project/ Storage (CNCF Compliant) ✅ COMPLETE
1. ✅ Create context storage module (`context_storage.py`)
2. ✅ Support both inline (project.yaml) and separate file storage
3. ✅ Add migration path from `.project.yaml` to `.project/project.yaml`
4. ✅ Update `get_project_context()` to read from new location

### Phase 4: Context Sieve (Progressive Detection) ✅ COMPLETE (NEW)
1. ✅ Create `packages/darnit/src/darnit/context/` module
2. ✅ Implement `ContextSieve` with 4-phase progressive detection
3. ✅ Implement confidence scoring with source weights
4. ✅ Integrate sieve into `context_validator.py`
5. ✅ Update orchestrator to pass owner/repo for API detection
6. ✅ Remove duplicated detection logic from remediation actions

**Key files created:**
- `packages/darnit/src/darnit/context/sieve.py`
- `packages/darnit/src/darnit/context/confidence.py`
- `packages/darnit/src/darnit/context/__init__.py`

### Phase 5: Enhanced MCP Tools ✅ COMPLETE
1. ✅ Extend `confirm_project_context` with new params
2. ✅ Add `get_pending_context` tool
3. ✅ Update audit output to include context prompts

### Phase 6: Per-Control Context ✅ COMPLETE
1. ✅ Add `requires_context` to `ControlConfig`
2. ✅ Update sieve orchestrator to check context requirements
3. ✅ Implement `on_missing_context` behavior

---

## Files to Modify

| File | Changes |
|------|---------|
| `packages/darnit/src/darnit/config/schema.py` | Add CNCF extension models, ContextValue, ContextSource |
| `packages/darnit/src/darnit/config/framework_schema.py` | Add ContextDefinition, ContextConfig |
| `packages/darnit/src/darnit/config/context_storage.py` | NEW: Read/write .project/ with CNCF format |
| `packages/darnit/src/darnit/sieve/project_context.py` | Update to use new storage, add migration |
| `packages/darnit-baseline/openssf-baseline.toml` | Add [context] section |
| `packages/darnit-baseline/src/darnit_baseline/tools.py` | Extend confirm_project_context |
| `packages/darnit/src/darnit/tools/audit.py` | Add context prompts to output |

## Migration Strategy

### Automatic Migration
When loading config, detect format and migrate automatically:

```python
def load_project_config(local_path: str) -> CNCFProjectConfig:
    """Load with automatic format detection and migration."""

    # Priority 1: New CNCF format
    cncf_path = Path(local_path) / ".project" / "project.yaml"
    if cncf_path.exists():
        return _load_cncf_format(cncf_path)

    # Priority 2: Legacy format (migrate on read)
    legacy_path = Path(local_path) / ".project.yaml"
    if legacy_path.exists():
        config = _load_legacy_format(legacy_path)
        # Log migration suggestion
        logger.info(
            "Using legacy .project.yaml format. "
            "Consider migrating to .project/project.yaml"
        )
        return _convert_to_cncf_format(config)

    return None
```

### Migration Command
Add MCP tool to migrate existing projects:

```python
def migrate_project_config(
    local_path: str = ".",
    backup: bool = True,
    dry_run: bool = True,
) -> str:
    """Migrate .project.yaml to CNCF .project/project.yaml format.

    Args:
        local_path: Path to repository
        backup: Create backup of original file
        dry_run: Show what would change without making changes

    Returns:
        Migration summary
    """
```

---

## Example Usage Flow

1. **User runs audit:**
   ```
   audit_openssf_baseline(local_path=".")
   ```

2. **Audit output includes:**
   ```
   ## Audit Results
   ✅ PASS (45) | ❌ FAIL (3) | ⚠️ WARN (5)

   ## 🤔 Help Improve This Audit

   ### maintainers
   **Question:** Who are the project maintainers?
   - *Hint:* Provide GitHub usernames or path to MAINTAINERS.md
   - *Affects:* OSPS-GV-01.01, OSPS-GV-01.02, OSPS-GV-04.01
   - *Set with:* `confirm_project_context(maintainers=["@user1"])`
   ```

3. **Claude asks user:**
   > I couldn't automatically determine who the maintainers are. Could you tell me who maintains this project, or point me to a file that lists them?

4. **User responds:**
   > The maintainers are me (@mlieberman85) and @other-maintainer

5. **Claude calls:**
   ```
   confirm_project_context(maintainers=["@mlieberman85", "@other-maintainer"])
   ```

6. **Context saved to `.project/project.yaml`** (CNCF format):
   ```yaml
   schema_version: "1.1.0"
   name: "my-project"
   extensions:
     openssf-baseline:
       metadata:
         author: "OpenSSF"
         homepage: "https://baseline.openssf.org"
         version: "0.1.0"
       config:
         context:
           governance:
             maintainers:
               source: "user_confirmed"
               value: ["@mlieberman85", "@other-maintainer"]
               confirmed_at: "2025-01-26T10:30:00Z"
   ```

7. **Re-run audit → OSPS-GV-01.01 now has context to evaluate**

---

## Backward Compatibility

### Legacy Format Support
The system will continue to support the legacy `.project.yaml` with `x-openssf-baseline:` prefix:

```yaml
# Legacy format (still supported, but deprecated)
x-openssf-baseline:
  context:
    has_releases: true
    ci_provider: github
  controls:
    OSPS-BR-02.01:
      status: not_applicable
      reason: "No releases yet"
```

### Migration Path
1. **Automatic read migration**: Legacy files are read and converted to CNCF format in memory
2. **Optional write migration**: `migrate_project_config()` tool to convert on disk
3. **Deprecation warnings**: Log warnings when legacy format is detected
4. **No forced migration**: Legacy format will continue to work indefinitely
