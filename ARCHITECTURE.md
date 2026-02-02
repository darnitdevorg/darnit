# OpenSSF Baseline MCP Server Architecture

> **For LLMs**: This document provides essential context for understanding and modifying this codebase. Read this first before making changes.

## Overview

This is an MCP (Model Context Protocol) server that audits GitHub repositories against the [OpenSSF Baseline](https://baseline.openssf.org/) security standard (OSPS v2025.10.10). It provides:

- **62 automated security checks** across 3 maturity levels
- **Auto-remediation** capabilities for common issues
- **In-toto attestations** with optional Sigstore signing
- **STRIDE threat modeling** generation
- **Project configuration** management

## Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| MCP Framework | `mcp[cli]` with FastMCP |
| Package Manager | `uv` |
| GitHub Integration | `gh` CLI |
| Signing | Sigstore (sigstore-python) |
| Attestations | in-toto format |

## Package Structure

```
baseline-mcp/
├── main.py                    # MCP tools and entry point
├── pyproject.toml             # Package configuration
├── example.project.toml       # Example project configuration
├── baseline_mcp/              # Modular package
│   ├── __init__.py            # Public API exports
│   ├── server.py              # MCP server instance
│   ├── core/                  # Core abstractions
│   │   ├── __init__.py
│   │   ├── models.py          # CheckStatus, CheckResult, AuditResult
│   │   ├── adapters.py        # CheckAdapter, RemediationAdapter ABCs
│   │   └── utils.py           # gh_api, file_exists, read_file, etc.
│   ├── config/                # Project configuration
│   │   ├── __init__.py
│   │   ├── models.py          # ProjectConfig, ProjectType, constants
│   │   ├── loader.py          # load/save project config
│   │   ├── discovery.py       # Auto-discover files, CI, project name
│   │   └── validation.py      # Validate references (local, URL, repo)
│   ├── checks/                # Legacy checks (being replaced by sieve)
│   │   ├── __init__.py        # Public exports for all checks
│   │   ├── constants.py       # OSI_LICENSES, BINARY_EXTENSIONS, patterns
│   │   ├── helpers.py         # Check-specific utilities
│   │   ├── level1.py          # Level 1 checks (24 controls)
│   │   ├── level2.py          # Level 2 checks (18 controls)
│   │   └── level3.py          # Level 3 checks (20 controls)
│   ├── sieve/                 # Progressive verification system ✅ NEW
│   │   ├── __init__.py        # Public exports
│   │   ├── models.py          # VerificationPhase, PassOutcome, SieveResult
│   │   ├── passes.py          # DeterministicPass, PatternPass, LLMPass, ManualPass
│   │   ├── orchestrator.py    # SieveOrchestrator - runs passes in order
│   │   ├── registry.py        # ControlRegistry, register_control()
│   │   ├── llm_protocol.py    # LLM consultation protocol
│   │   ├── project_context.py # User-confirmed project facts from project.toml
│   │   ├── controls_level1.py # Level 1 sieve control definitions (24)
│   │   ├── controls_level2.py # Level 2 sieve control definitions (18)
│   │   └── controls_level3.py # Level 3 sieve control definitions (20)
│   ├── remediation/           # Auto-fix capabilities
│   │   ├── __init__.py        # Public API
│   │   ├── registry.py        # REMEDIATION_REGISTRY, control mappings
│   │   └── helpers.py         # Common remediation utilities
│   ├── threat_model/          # STRIDE threat modeling
│   │   ├── __init__.py        # Public exports
│   │   ├── models.py          # StrideCategory, RiskLevel, Threat, etc.
│   │   ├── patterns.py        # FRAMEWORK_PATTERNS, INJECTION_PATTERNS, etc.
│   │   ├── discovery.py       # Asset discovery functions
│   │   ├── stride.py          # STRIDE analysis engine
│   │   └── generators.py      # Markdown, SARIF, JSON output
│   ├── attestation/           # In-toto attestations
│   │   ├── __init__.py        # Public exports
│   │   ├── git.py             # Git commit/ref helpers
│   │   ├── predicate.py       # Attestation predicate building
│   │   ├── signing.py         # Sigstore signing (multi-version support)
│   │   └── generator.py       # Attestation generation
│   ├── tools/                 # MCP tool implementations
│   │   ├── __init__.py        # Public exports
│   │   ├── server.py          # MCP server factory
│   │   ├── helpers.py         # Common tool helpers
│   │   └── audit.py           # Audit tool implementations
│   └── formatters/            # Output formatters
│       ├── __init__.py        # Public exports
│       ├── rules_catalog.py   # OSPS rules metadata (62 controls)
│       └── sarif.py           # SARIF 2.1.0 generator
└── docs/                      # Additional documentation
    ├── DECISION_FLOWS.md      # Remediation decision trees
    ├── ATTESTATION_SPEC.md    # Attestation format specification
    └── SARIF_DESIGN.md        # SARIF output design document
```

## Architecture Evolution

The codebase has two check systems:

| System | Status | Location | Description |
|--------|--------|----------|-------------|
| **Legacy checks** | Stable | `baseline_mcp/checks/` | Simple functions returning results |
| **Sieve system** | Active development | `baseline_mcp/sieve/` | 4-phase progressive verification |

The sieve system is the future architecture, providing:
- Multi-phase verification (fast checks first, expensive checks last)
- LLM consultation protocol for ambiguous cases
- Project context awareness (user-confirmed facts)
- CI provider abstraction (not just GitHub Actions)

## Key Data Structures

### CheckResult
```python
@dataclass
class CheckResult:
    control_id: str      # e.g., "OSPS-AC-01.01"
    status: CheckStatus  # PASS, FAIL, WARN, NA, ERROR
    message: str         # Human-readable description
    level: int = 1       # OSPS maturity level (1, 2, or 3)
    details: Optional[Dict[str, Any]] = None
    evidence: Optional[str] = None
    source: str = "builtin"
```

### AuditResult
```python
@dataclass
class AuditResult:
    owner: str
    repo: str
    local_path: str
    level: int                    # Max level checked
    default_branch: str
    all_results: List[Dict]       # All check results
    summary: Dict[str, int]       # {PASS: n, FAIL: n, WARN: n, ...}
    level_compliance: Dict[int, bool]  # {1: True, 2: False, 3: False}
    timestamp: str
    git_commit: Optional[str]
    git_ref: Optional[str]
```

### ProjectConfig
```python
@dataclass
class ProjectConfig:
    project_name: str
    project_type: ProjectType     # LIBRARY, APPLICATION, FRAMEWORK, etc.
    controls: Dict[str, ControlStatus]
    file_locations: Dict[str, str]
    exclusions: List[str]
    custom_checks: Dict[str, Any]
```

## OSPS Control Structure

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

## MCP Tools

### Primary Tool
- `audit_openssf_baseline(owner, repo, local_path)` - Run full compliance audit

### Remediation Tools
- `create_security_policy(owner, repo, local_path)` - Create SECURITY.md
- `create_contributing_guide(owner, repo, local_path)` - Create CONTRIBUTING.md
- `create_codeowners(owner, repo, local_path)` - Create CODEOWNERS
- `create_governance_doc(owner, repo, local_path)` - Create GOVERNANCE.md
- `create_dependabot_config(owner, repo, local_path)` - Create dependabot.yml
- `create_support_doc(owner, repo, local_path)` - Create SUPPORT.md
- `create_bug_report_template(owner, repo, local_path)` - Create bug report template
- `enable_branch_protection(owner, repo, branch)` - Configure branch protection
- `configure_status_checks(owner, repo, branch)` - Configure required status checks
- `configure_dco_enforcement(owner, repo, local_path)` - Configure DCO sign-off
- `remediate_audit_findings(local_path, categories)` - Apply multiple remediations

### Configuration Tools
- `get_project_config(local_path)` - Get current project configuration
- `sync_project_config(local_path, fix)` - Sync/fix configuration

### Analysis Tools
- `generate_threat_model(owner, repo, local_path)` - Generate STRIDE threat model
- `generate_attestation(owner, repo, local_path, sign)` - Generate in-toto attestation

### Combined Workflow
- `audit_and_attest(owner, repo, local_path, sign)` - Audit + attestation in one call

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         MCP Client (Claude)                          │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      audit_openssf_baseline()                        │
│                         (main MCP tool)                              │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
            ┌───────────┐   ┌───────────┐   ┌───────────┐
            │  Level 1  │   │  Level 2  │   │  Level 3  │
            │  Checks   │   │  Checks   │   │  Checks   │
            └───────────┘   └───────────┘   └───────────┘
                    │               │               │
                    ▼               ▼               ▼
            ┌─────────────────────────────────────────────┐
            │              Check Functions                 │
            │  • GitHub API calls (gh_api)                │
            │  • Local file analysis (file_exists, etc)   │
            │  • Pattern matching (regex)                  │
            └─────────────────────────────────────────────┘
                                    │
                                    ▼
            ┌─────────────────────────────────────────────┐
            │              AuditResult                     │
            │  • all_results: List[CheckResult]           │
            │  • summary: {PASS, FAIL, WARN, NA, ERROR}   │
            │  • level_compliance: {1: bool, 2: bool...}  │
            └─────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
            ┌───────────────┐               ┌───────────────┐
            │  Remediation  │               │  Attestation  │
            │  (optional)   │               │  (optional)   │
            └───────────────┘               └───────────────┘
```

## Key Design Decisions

### 1. Hybrid Check Approach
Checks use both GitHub API and local file analysis:
- **GitHub API**: Branch protection, releases, org settings
- **Local files**: Workflow analysis, dependency files, documentation content

### 2. Graceful Degradation
All checks handle failures gracefully:
- API failures → WARN or ERROR status with helpful message
- Missing files → appropriate N/A or FAIL based on requirement
- Permission issues → clear error messages

### 3. Evidence-Based Results
Each check provides:
- Clear status (PASS/FAIL/WARN/NA/ERROR)
- Human-readable message explaining the result
- Optional evidence for verification

### 4. Incremental Migration
The codebase is being migrated from monolithic `main.py` to modular `baseline_mcp/` package:
- Modules can be imported independently
- `main.py` maintains backward compatibility
- Tests can target individual modules

## Sieve System (Progressive Verification)

The sieve system implements a 4-phase progressive verification architecture that runs cheap/fast checks first and only proceeds to expensive checks when needed.

### Verification Phases

```
┌─────────────────────────────────────────────────────────────────┐
│                    OSPS CONTROL CHECK                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Phase 1: DETERMINISTIC                                          │
│  ├─ File existence checks                                        │
│  ├─ GitHub API boolean lookups                                   │
│  └─ Config file parsing                                          │
│                     │                                            │
│            PASS/FAIL? ──────► DONE                               │
│                     │ INCONCLUSIVE                               │
│                     ▼                                            │
│  Phase 2: PATTERN                                                │
│  ├─ Regex content matching                                       │
│  ├─ Heuristic analysis                                           │
│  └─ Multi-file pattern detection                                 │
│                     │                                            │
│            PASS/FAIL? ──────► DONE                               │
│                     │ INCONCLUSIVE                               │
│                     ▼                                            │
│  Phase 3: LLM                                                    │
│  ├─ Consultation request generated                               │
│  ├─ Calling LLM analyzes content                                 │
│  └─ Structured response with confidence                          │
│                     │                                            │
│            PASS/FAIL? ──────► DONE                               │
│                     │ INCONCLUSIVE                               │
│                     ▼                                            │
│  Phase 4: MANUAL                                                 │
│  └─ Returns WARN with verification steps                         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | File | Purpose |
|-----------|------|---------|
| **ControlSpec** | `models.py` | Control definition with pass sequence |
| **PassResult** | `models.py` | Result from a single verification pass |
| **SieveResult** | `models.py` | Final result with full pass history |
| **DeterministicPass** | `passes.py` | File/API checks |
| **PatternPass** | `passes.py` | Regex content matching |
| **LLMPass** | `passes.py` | LLM consultation protocol |
| **ManualPass** | `passes.py` | Human verification steps |
| **SieveOrchestrator** | `orchestrator.py` | Runs passes, stops on conclusion |
| **ControlRegistry** | `registry.py` | Global control registration |

### Control Definition Example

```python
register_control(ControlSpec(
    control_id="OSPS-VM-02.01",
    level=1,
    domain="VM",
    name="SecurityContacts",
    description="Security contacts documented in SECURITY.md",
    passes=[
        # Phase 1: Does SECURITY.md exist?
        DeterministicPass(
            file_must_exist=["SECURITY.md", ".github/SECURITY.md"]
        ),
        # Phase 2: Does it contain contact info?
        PatternPass(
            file_patterns=["SECURITY.md"],
            content_patterns={
                "contact": r"(email|security.*contact|report.*vulnerabilit)",
            },
        ),
        # Phase 3: LLM analysis for ambiguous cases
        LLMPass(
            prompt_template="Analyze if this SECURITY.md provides adequate contact info...",
            files_to_include=["SECURITY.md"],
        ),
        # Phase 4: Manual fallback
        ManualPass(
            verification_steps=[
                "Open SECURITY.md and verify contact method exists",
                "Confirm contact is actively monitored",
            ]
        ),
    ],
))
```

### Project Context System

The project context system allows users to confirm facts about their project that affect how controls are evaluated. This is stored in `project.toml`.

**Configuration (`project.toml`):**
```toml
[project.context]
# Does this project have subprojects?
has_subprojects = false

# What CI/CD system does this project use?
ci_provider = "gitlab"  # github, gitlab, jenkins, circleci, azure, travis, none, other

# Path to CI config (for non-GitHub CI)
ci_config_path = ".gitlab-ci.yml"
```

**Context Keys:**

| Key | Affects Controls | Description |
|-----|-----------------|-------------|
| `has_subprojects` | QA-04.01, QA-04.02 | Whether project has related repos |
| `has_releases` | BR-02.01, BR-04.01, BR-06.01, DO-01.01, DO-03.01 | Whether project makes releases |
| `is_library` | SA-02.01 | Whether project is a library/framework |
| `has_compiled_assets` | QA-02.02 | Whether releases include binaries |
| `ci_provider` | BR-01.*, AC-04.*, QA-06.01, VM-05.*, VM-06.02 | CI/CD system in use |
| `ci_config_path` | Same as ci_provider | Path to CI config file |

**CI Provider Handling:**

When GitHub Actions workflows aren't found, checks now:
1. Look for other CI config files (`.gitlab-ci.yml`, `Jenkinsfile`, etc.)
2. Check `project.toml` for user-confirmed `ci_provider`
3. If `ci_provider = "none"`, mark CI checks as N/A
4. If `ci_provider = "other"`, return INCONCLUSIVE with manual verification steps

```python
# Example from _create_sast_check()
if is_context_confirmed(ctx.local_path, "ci_provider"):
    ci_provider = get_context_value(ctx.local_path, "ci_provider")
    if ci_provider == "none":
        return PassResult(outcome=PassOutcome.INCONCLUSIVE,
            message="No CI/CD configured - SAST check not applicable")
    elif ci_provider != "github":
        return PassResult(outcome=PassOutcome.INCONCLUSIVE,
            message=f"Using {ci_provider} CI - manually verify SAST is configured")
```

### Future: External Data Sources

The architecture is designed to eventually support multiple data sources:

```
┌─────────────────────────────────────────────────────────────────┐
│                      OSPS CONTROL                                │
├─────────────────────────────────────────────────────────────────┤
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│   │  Scorecard  │  │   Built-in  │  │    Trivy    │   ...       │
│   │   Source    │  │   Source    │  │   Source    │             │
│   └──────┬──────┘  └──────┬──────┘  └──────┬──────┘             │
│          │                │                │                     │
│          ▼                ▼                ▼                     │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │              Evidence Aggregator / Resolver              │   │
│   └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

This would allow integrating results from:
- **OpenSSF Scorecard**: Branch-Protection → OSPS-AC-03.01
- **Trivy/Grype**: Vulnerability scanning → OSPS-VM-05.*
- **Semgrep/CodeQL**: SAST results → OSPS-VM-06.02

## Remediation System

The remediation system automatically fixes common compliance gaps based on audit failures.

### Context Sieve (Progressive Detection)

Before applying remediations that require context (like maintainers for CODEOWNERS), the system uses a **Context Sieve** for progressive auto-detection:

```
┌─────────────────────────────────────────────────────────────────┐
│                    CONTEXT SIEVE PIPELINE                        │
├─────────────────────────────────────────────────────────────────┤
│  Phase 1: DETERMINISTIC (conf: 0.9)                              │
│  └─ MAINTAINERS.md, CODEOWNERS, SECURITY.md                      │
│                     │                                            │
│  Phase 2: HEURISTIC (conf: 0.7)                                  │
│  └─ package.json authors, git history, README                    │
│                     │                                            │
│  Phase 3: API (conf: 0.6)                                        │
│  └─ GitHub collaborators with admin/maintain access              │
│                     │                                            │
│  Phase 4: COMBINE                                                │
│  └─ Aggregate signals, calculate agreement, return best value    │
└─────────────────────────────────────────────────────────────────┘
```

| Source | Weight | Example |
|--------|--------|---------|
| `USER_CONFIRMED` | 1.0 | User ran `confirm_project_context()` |
| `EXPLICIT_FILE` | 0.9 | Found in MAINTAINERS.md |
| `PROJECT_MANIFEST` | 0.8 | Found in package.json author |
| `GITHUB_API` | 0.7 | GitHub collaborators API |
| `GIT_HISTORY` | 0.6 | Top git contributors |
| `PATTERN_MATCH` | 0.5 | README author mention |

**Key Components** (in `packages/darnit/src/darnit/context/`):
- `confidence.py` - Signal weighting and confidence calculation
- `sieve.py` - Progressive detection pipeline

See [CONTEXT_SIEVE_DESIGN.md](docs/design/CONTEXT_SIEVE_DESIGN.md) for full design.

### Registry Structure
```python
REMEDIATION_REGISTRY = {
    "branch_protection": {
        "description": "Enable branch protection rules",
        "controls": ["OSPS-AC-03.01", "OSPS-AC-03.02", "OSPS-QA-07.01"],
        "function": "enable_branch_protection",
        "safe": True,           # Safe to auto-apply
        "requires_api": True,   # Needs GitHub API access
    },
    # ... 10 categories total
}
```

### Available Categories
| Category | Controls | Function | API Required |
|----------|----------|----------|--------------|
| `branch_protection` | AC-03.01, AC-03.02, QA-07.01 | `enable_branch_protection` | Yes |
| `status_checks` | QA-03.01 | `configure_status_checks` | Yes |
| `security_policy` | VM-01.01, VM-02.01, VM-03.01 | `create_security_policy` | No |
| `codeowners` | GV-01.01, GV-01.02, GV-04.01 | `create_codeowners` | No |
| `governance` | GV-01.01, GV-01.02 | `create_governance_doc` | No |
| `contributing` | GV-03.01, GV-03.02 | `create_contributing_guide` | No |
| `dco_enforcement` | LE-01.01 | `configure_dco_enforcement` | No |
| `bug_report_template` | DO-02.01 | `create_bug_report_template` | No |
| `dependabot` | VM-05.01, VM-05.02, VM-05.03 | `create_dependabot_config` | No |
| `support_doc` | DO-03.01 | `create_support_doc` | No |

### Usage Pattern
```python
from baseline_mcp.remediation import (
    get_categories_for_failures,
    REMEDIATION_REGISTRY,
)

# After running audit, find applicable fixes
failures = [r for r in results if r["status"] == "FAIL"]
categories = get_categories_for_failures(failures)
# Returns: ["branch_protection", "security_policy", ...]
```

## Threat Model System

The threat model system provides automated security analysis using the STRIDE methodology.

### Key Components

| Component | Purpose |
|-----------|---------|
| `models.py` | Data classes: StrideCategory, RiskLevel, Threat, AssetInventory |
| `patterns.py` | Detection patterns for frameworks, auth, injection, secrets |
| `discovery.py` | Asset discovery: entry points, auth, data stores, secrets |
| `stride.py` | STRIDE analysis engine with risk scoring |
| `generators.py` | Output in Markdown, SARIF, and JSON formats |

### STRIDE Categories

| Category | Description |
|----------|-------------|
| Spoofing | Identity verification threats |
| Tampering | Data integrity threats |
| Repudiation | Audit and accountability threats |
| Information Disclosure | Confidentiality threats |
| Denial of Service | Availability threats |
| Elevation of Privilege | Authorization threats |

### Usage Pattern
```python
from baseline_mcp.threat_model import (
    discover_all_assets,
    discover_injection_sinks,
    analyze_stride_threats,
    identify_control_gaps,
    generate_markdown_threat_model,
)

# Discover assets
assets = discover_all_assets("/path/to/repo")

# Find injection vulnerabilities
injection_sinks = discover_injection_sinks("/path/to/repo")

# Analyze threats
threats = analyze_stride_threats(assets, injection_sinks)
control_gaps = identify_control_gaps(assets, threats)

# Generate report
report = generate_markdown_threat_model(
    "/path/to/repo",
    assets,
    threats,
    control_gaps,
    assets.frameworks_detected
)
```

## Attestation System

The attestation system generates cryptographically signed proofs of compliance using in-toto format and Sigstore keyless signing.

### Key Components

| Component | Purpose |
|-----------|---------|
| `git.py` | Extract git commit SHA and ref (branch/tag) for attestation subjects |
| `predicate.py` | Build OpenSSF Baseline assessment predicate with results summary |
| `signing.py` | Sigstore keyless signing with multi-version API support (1.x, 2.x, 3.x) |
| `generator.py` | Generate complete attestations from audit results |

### Sigstore API Versions

The signing module automatically detects and uses the appropriate Sigstore API:

| Version | API Pattern | Detection |
|---------|-------------|-----------|
| 3.x | `ClientTrustConfig` + `SigningContext.from_trust_config()` | Primary |
| 2.x | `Signer.production()` + `sign_dsse()` | Fallback 1 |
| 1.x | `SigningContext.production()` + `signer.sign()` | Fallback 2 |

### Usage Pattern
```python
from baseline_mcp.attestation import (
    build_assessment_predicate,
    sign_attestation,
    generate_attestation_from_results,
    is_attestation_available,
    BASELINE_PREDICATE_TYPE,
)

# Check if signing is available
if is_attestation_available():
    # Build predicate from audit results
    predicate = build_assessment_predicate(
        owner="owner",
        repo="repo",
        commit="abc123def",
        ref="main",
        level=3,
        results=audit_results,
        project_config=config,
        adapters_used=["builtin"]
    )

    # Sign with Sigstore
    bundle = sign_attestation(
        predicate=predicate,
        predicate_type=BASELINE_PREDICATE_TYPE,
        subject_name="git+https://github.com/owner/repo",
        commit="abc123def"
    )
```

### Signing Behavior

- **CI/CD (GitHub Actions, GitLab CI)**: Uses ambient OIDC credentials automatically
- **Local development**: Opens browser for OIDC authentication (GitHub, Google, Microsoft)
- **Required permission**: `id-token: write` in GitHub Actions

## Tools System

The tools module provides the implementation layer for MCP tools, separating business logic from MCP registration.

### Key Components

| Component | Purpose |
|-----------|---------|
| `server.py` | MCP server factory and registration helpers |
| `helpers.py` | Common utilities for validation, formatting, file operations |
| `audit.py` | Audit implementations: prepare, run checks, format results |

### Server Factory Pattern
```python
from baseline_mcp.tools import create_server, SERVER_NAME

# Create a configured MCP server
mcp = create_server()

# Or with custom name
mcp = create_server("Custom Server Name")
```

### Tool Helper Usage
```python
from baseline_mcp.tools import (
    validate_and_resolve_repo,
    format_error,
    format_success,
    write_file_safely,
)

# Validate inputs
owner, repo, path, error = validate_and_resolve_repo(
    owner=None,  # Auto-detect
    repo=None,   # Auto-detect
    local_path="/path/to/repo"
)
if error:
    return format_error(error)

# Write files safely
success, message = write_file_safely(
    filepath="/path/to/file.md",
    content="# Content",
    overwrite=False
)
```

### Audit Tools Usage
```python
from baseline_mcp.tools import (
    prepare_audit,
    run_checks,
    calculate_compliance,
    summarize_results,
    format_results_markdown,
)

# Prepare audit
owner, repo, path, branch, error = prepare_audit(None, None, "/path/to/repo")
if error:
    return error

# Run checks
results = run_checks(owner, repo, path, branch, level=3)

# Calculate compliance
compliance = calculate_compliance(results, level=3)
summary = summarize_results(results)

# Format output
report = format_results_markdown(owner, repo, results, summary, compliance, level=3)
```

## Common Patterns

### Adding a New Check
```python
# In baseline_mcp/checks/level{N}.py

def check_level{N}_{domain}(owner: str, repo: str, local_path: str) -> List[Dict]:
    """Check Level {N} {Domain} requirements."""
    results = []

    # Use helpers
    content = read_file(local_path, "SOME_FILE.md")
    api_data = gh_api_safe(f"/repos/{owner}/{repo}/...")

    # Create results
    if condition:
        results.append(result("OSPS-XX-YY.ZZ", "PASS", "Description", level=N))
    else:
        results.append(result("OSPS-XX-YY.ZZ", "FAIL", "Description", level=N))

    return results
```

### Adding a New Remediation
```python
# In main.py (will move to baseline_mcp/remediation/)

@mcp.tool()
def remediate_something(owner: str, repo: str, local_path: str) -> str:
    """Remediate something for OSPS compliance."""
    # Validate inputs
    resolved_path, error = _validate_local_path(local_path, owner, repo)
    if error:
        return f"Error: {error}"

    # Perform remediation
    # ...

    return "Success message"
```

## Testing

```bash
# Run syntax check
uv run python -c "import main; print('OK')"

# Test specific module imports
uv run python -c "from baseline_mcp.checks import run_level1_checks; print('OK')"

# Run MCP server
uv run mcp run main.py
```

## Environment Requirements

- Python 3.11+
- `gh` CLI authenticated (`gh auth login`)
- `uv` package manager
- For signing: Sigstore OIDC authentication

## Related Documentation

- [OpenSSF Baseline Specification](https://baseline.openssf.org/)
- [OSPS Controls Reference](https://github.com/ossf/security-baseline)
- [MCP Protocol](https://modelcontextprotocol.io/)
- [In-toto Attestation Format](https://in-toto.io/)
- [Sigstore](https://sigstore.dev/)

---

*Last updated: 2025-12-05 | Sieve system with 62 controls, project context, CI provider abstraction*
