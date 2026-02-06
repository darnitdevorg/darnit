# Security Assurance Framework - Design Document

> **Status**: ⚠️ DEPRECATED - See authoritative spec
> **Version**: 0.1.0
> **Last Updated**: 2024-12-01
>
> **DEPRECATION NOTICE**: This document has been superseded by the authoritative
> framework specification at `openspec/specs/framework-design/spec.md`.
> Please refer to that document for current framework design decisions.
> Generated documentation is available at `docs/generated/`.

## Executive Summary

This document outlines the design for transforming the OpenSSF Baseline MCP into a **multi-standard security assurance framework**. The framework will support pluggable check providers for OSPS, SLSA, Scorecard, and custom organizational standards, unified through a common configuration model (`project.toml`).

---

## 1. Framework Architecture

### 1.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MCP Clients                                     │
│                    (Claude, VS Code, other MCP hosts)                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Security Assurance MCP Server                         │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  ┌─────────────────┐   │
│  │   Audit     │  │  Remediate   │  │   Attest    │  │  Threat Model   │   │
│  │   Tools     │  │    Tools     │  │   Tools     │  │     Tools       │   │
│  └─────────────┘  └──────────────┘  └─────────────┘  └─────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Framework Core                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │  Plugin Registry │  │  Config Manager  │  │   Result Aggregator      │  │
│  │  & Discovery     │  │  (project.toml)  │  │   (SARIF, MD, JSON)      │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────────────┘  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │  Standard        │  │  Check           │  │   Remediation            │  │
│  │  Registry        │  │  Orchestrator    │  │   Orchestrator           │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    ▼                ▼                ▼
┌──────────────────────┐ ┌──────────────────┐ ┌──────────────────────┐
│   OSPS Plugin        │ │   SLSA Plugin    │ │  Custom Plugin       │
│  ┌────────────────┐  │ │  ┌────────────┐  │ │  ┌────────────────┐  │
│  │ Check Adapters │  │ │  │ Verifiers  │  │ │  │ Org Standards  │  │
│  │ (61 controls)  │  │ │  │ (L1-L4)    │  │ │  │ (N controls)   │  │
│  └────────────────┘  │ │  └────────────┘  │ │  └────────────────┘  │
│  ┌────────────────┐  │ │  ┌────────────┐  │ │  ┌────────────────┐  │
│  │ Remediations   │  │ │  │ Generators │  │ │  │ Remediations   │  │
│  └────────────────┘  │ │  └────────────┘  │ │  └────────────────┘  │
└──────────────────────┘ └──────────────────┘ └──────────────────────┘
```

### 1.2 Package Structure

```
security-assurance-framework/
├── pyproject.toml                    # Framework package config
├── src/
│   └── security_assurance/
│       ├── __init__.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── models.py             # Core data models
│       │   ├── adapters.py           # CheckAdapter, RemediationAdapter ABCs
│       │   ├── registry.py           # Plugin discovery & registration
│       │   ├── orchestrator.py       # Check execution orchestration
│       │   └── exceptions.py         # Framework exceptions
│       ├── config/
│       │   ├── __init__.py
│       │   ├── models.py             # ProjectConfig, Standard definitions
│       │   ├── loader.py             # project.toml parsing
│       │   ├── schema.py             # Config schema validation
│       │   └── discovery.py          # Auto-discovery utilities
│       ├── standards/
│       │   ├── __init__.py
│       │   ├── base.py               # Standard ABC
│       │   ├── registry.py           # Standard registration
│       │   └── control.py            # Control/requirement models
│       ├── formatters/
│       │   ├── __init__.py
│       │   ├── sarif.py              # SARIF 2.1.0 output
│       │   ├── markdown.py           # Markdown reports
│       │   └── json.py               # JSON output
│       ├── attestation/
│       │   ├── __init__.py
│       │   ├── intoto.py             # In-toto statements
│       │   └── signing.py            # Sigstore integration
│       └── server/
│           ├── __init__.py
│           ├── factory.py            # MCP server factory
│           └── tools.py              # Core MCP tools
│
├── plugins/                          # Built-in plugins (can be separate packages)
│   ├── osps/                         # OpenSSF Baseline (current code)
│   ├── slsa/                         # SLSA verification
│   ├── scorecard/                    # OpenSSF Scorecard
│   └── custom/                       # Template for custom plugins
│
└── docs/
    ├── ARCHITECTURE.md
    ├── PLUGIN_DEVELOPMENT.md
    └── CONFIGURATION.md
```

---

## 2. Core Data Models

### 2.1 Standard Definition

```python
# security_assurance/standards/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Set, Optional, Any


class StandardLevel(Enum):
    """Maturity/compliance levels within a standard."""
    LEVEL_1 = 1
    LEVEL_2 = 2
    LEVEL_3 = 3
    LEVEL_4 = 4  # For SLSA


@dataclass
class ControlDefinition:
    """Definition of a single control/requirement within a standard."""
    id: str                              # e.g., "OSPS-AC-01.01", "SLSA-SOURCE-L2"
    standard: str                        # e.g., "osps", "slsa"
    title: str                           # Short title
    description: str                     # Full description
    rationale: Optional[str] = None      # Why this matters
    verification: Optional[str] = None   # How to verify
    remediation_hint: Optional[str] = None

    # Flexible tags dict - can include level, domain, security_severity, and custom tags
    # Example: {"level": 1, "domain": "AC", "security_severity": 8.0, "access-control": True}
    tags: Dict[str, Any] = field(default_factory=dict)

    # Metadata for cross-standard mapping
    related_controls: List[str] = field(default_factory=list)  # Cross-references

    # Convenience properties to extract common tags
    @property
    def level(self) -> int:
        return self.tags.get("level", 1)

    @property
    def domain(self) -> str:
        return self.tags.get("domain", "")

    @property
    def security_severity(self) -> float:
        return self.tags.get("security_severity", 5.0)

    default_sarif_level: str = "warning" # error, warning, note, none


@dataclass
class Standard:
    """A security/compliance standard (e.g., OSPS, SLSA, Scorecard)."""
    id: str                              # e.g., "osps", "slsa", "scorecard"
    name: str                            # e.g., "OpenSSF Baseline"
    version: str                         # e.g., "v2025.10.10"
    url: str                             # Reference URL

    # Control structure
    levels: List[int]                    # Available levels [1, 2, 3] or [1, 2, 3, 4]
    domains: Dict[str, str]              # Domain ID -> Domain name
    controls: Dict[str, ControlDefinition]  # Control ID -> Definition

    # Configuration
    config_section: str                  # Section in project.toml, e.g., "osps", "slsa"
    default_level: int = 1               # Default target level

    def get_controls_for_level(self, level: int) -> List[ControlDefinition]:
        """Get all controls up to and including the specified level."""
        return [c for c in self.controls.values() if c.level <= level]

    def get_domain_controls(self, domain: str) -> List[ControlDefinition]:
        """Get all controls in a specific domain."""
        return [c for c in self.controls.values() if c.domain == domain]
```

### 2.2 Check Results (Enhanced)

```python
# security_assurance/core/models.py

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Any, Optional
from datetime import datetime


class CheckStatus(Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    NA = "na"
    ERROR = "error"
    SKIPPED = "skipped"  # Explicitly skipped by config


@dataclass
class CheckResult:
    """Result of a single control check."""
    control_id: str
    standard: str                        # Which standard this control belongs to
    status: CheckStatus
    message: str
    level: int = 1

    # Evidence and details
    details: Optional[Dict[str, Any]] = None
    evidence: Optional[str] = None
    evidence_location: Optional[str] = None  # File path or URL

    # Metadata
    source: str = "builtin"              # Plugin/adapter that produced this
    timestamp: Optional[datetime] = None
    duration_ms: Optional[int] = None    # Check execution time

    # Remediation hints
    remediation_available: bool = False
    remediation_category: Optional[str] = None


@dataclass
class AuditResult:
    """Combined audit result across all standards."""
    # Repository info
    owner: str
    repo: str
    local_path: str
    commit: Optional[str] = None
    ref: Optional[str] = None

    # Results by standard
    results_by_standard: Dict[str, List[CheckResult]] = field(default_factory=dict)

    # Compliance summary by standard and level
    compliance: Dict[str, Dict[int, bool]] = field(default_factory=dict)

    # Aggregated summary
    summary: Dict[str, int] = field(default_factory=dict)  # Status counts

    # Metadata
    timestamp: str = ""
    standards_checked: List[str] = field(default_factory=list)
    plugins_used: List[str] = field(default_factory=list)

    @property
    def all_results(self) -> List[CheckResult]:
        """Flatten all results across standards."""
        results = []
        for standard_results in self.results_by_standard.values():
            results.extend(standard_results)
        return results
```

### 2.3 Adapter Interfaces (Enhanced)

```python
# security_assurance/core/adapters.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Any, Set, Optional

from .models import CheckResult, CheckStatus


@dataclass
class AdapterCapability:
    """Describes what an adapter can handle."""
    standard: str                        # Which standard (e.g., "osps", "slsa")
    control_ids: Set[str]                # Specific control IDs, or {"*"} for all
    supports_batch: bool = False
    requires_api: bool = False           # Needs GitHub API access
    requires_local: bool = True          # Needs local repo access

    # Optional: declare what config sections this adapter reads
    config_sections: List[str] = field(default_factory=list)


class CheckAdapter(ABC):
    """Base class for check adapters."""

    @abstractmethod
    def name(self) -> str:
        """Unique adapter name."""
        pass

    @abstractmethod
    def standard(self) -> str:
        """Which standard this adapter implements checks for."""
        pass

    @abstractmethod
    def capabilities(self) -> AdapterCapability:
        """Declare what this adapter can check."""
        pass

    @abstractmethod
    def check(
        self,
        control_id: str,
        context: "CheckContext",
    ) -> CheckResult:
        """Run a single check."""
        pass

    def check_batch(
        self,
        control_ids: List[str],
        context: "CheckContext",
    ) -> List[CheckResult]:
        """Run multiple checks. Default: iterate over check()."""
        return [self.check(cid, context) for cid in control_ids]

    def supports_control(self, control_id: str) -> bool:
        """Check if this adapter handles a specific control."""
        caps = self.capabilities()
        return "*" in caps.control_ids or control_id in caps.control_ids


@dataclass
class CheckContext:
    """Context provided to check adapters."""
    # Repository info
    owner: str
    repo: str
    local_path: str
    default_branch: str

    # Project configuration
    config: "ProjectConfig"

    # Standard-specific config section
    standard_config: Dict[str, Any]

    # Caching for expensive operations
    cache: Dict[str, Any] = field(default_factory=dict)

    # Utilities (injected by framework)
    gh_api: Optional[callable] = None
    file_exists: Optional[callable] = None
    read_file: Optional[callable] = None


class RemediationAdapter(ABC):
    """Base class for remediation adapters."""

    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def standard(self) -> str:
        pass

    @abstractmethod
    def capabilities(self) -> AdapterCapability:
        pass

    @abstractmethod
    def remediate(
        self,
        control_id: str,
        context: CheckContext,
        dry_run: bool = True,
    ) -> "RemediationResult":
        pass

    def can_remediate(self, result: CheckResult) -> bool:
        """Check if this adapter can fix a specific failure."""
        return (
            result.standard == self.standard() and
            self.supports_control(result.control_id) and
            result.status in (CheckStatus.FAIL, CheckStatus.WARN)
        )
```

---

## 3. Plugin System

### 3.1 Plugin Interface

```python
# security_assurance/core/plugin.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Type, Optional

from .adapters import CheckAdapter, RemediationAdapter
from ..standards.base import Standard


@dataclass
class PluginMetadata:
    """Plugin identification and requirements."""
    name: str                            # e.g., "osps-baseline"
    version: str                         # e.g., "1.0.0"
    description: str
    author: str

    # Which standard(s) this plugin implements
    standards: List[str]                 # e.g., ["osps"]

    # Dependencies
    requires_framework: str = ">=0.1.0"  # Minimum framework version
    requires_plugins: List[str] = field(default_factory=list)  # Other plugins

    # Configuration
    config_schema: Optional[Dict] = None  # JSON Schema for plugin config


class Plugin(ABC):
    """Base class for security assurance plugins."""

    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata."""
        pass

    @abstractmethod
    def get_standard(self) -> Standard:
        """Return the standard definition this plugin implements."""
        pass

    @abstractmethod
    def get_check_adapters(self) -> List[Type[CheckAdapter]]:
        """Return check adapter classes provided by this plugin."""
        pass

    def get_remediation_adapters(self) -> List[Type[RemediationAdapter]]:
        """Return remediation adapter classes (optional)."""
        return []

    def get_mcp_tools(self) -> List[callable]:
        """Return additional MCP tools to register (optional)."""
        return []

    def on_load(self, registry: "PluginRegistry") -> None:
        """Called when plugin is loaded. Override for initialization."""
        pass

    def on_unload(self) -> None:
        """Called when plugin is unloaded. Override for cleanup."""
        pass
```

### 3.2 Plugin Registry

```python
# security_assurance/core/registry.py

import importlib
import importlib.metadata
from typing import Dict, List, Type, Optional
import logging

from .plugin import Plugin, PluginMetadata
from .adapters import CheckAdapter, RemediationAdapter
from ..standards.base import Standard

logger = logging.getLogger(__name__)


class PluginRegistry:
    """Central registry for plugins, standards, and adapters."""

    # Entry point group for plugin discovery
    ENTRY_POINT_GROUP = "security_assurance.plugins"

    def __init__(self):
        self._plugins: Dict[str, Plugin] = {}
        self._standards: Dict[str, Standard] = {}
        self._check_adapters: Dict[str, List[CheckAdapter]] = {}  # standard -> adapters
        self._remediation_adapters: Dict[str, List[RemediationAdapter]] = {}
        self._mcp_tools: List[callable] = []

    def discover_plugins(self) -> List[str]:
        """Discover installed plugins via entry points."""
        discovered = []

        try:
            eps = importlib.metadata.entry_points(group=self.ENTRY_POINT_GROUP)
            for ep in eps:
                try:
                    plugin_class = ep.load()
                    if issubclass(plugin_class, Plugin):
                        discovered.append(ep.name)
                        logger.info(f"Discovered plugin: {ep.name}")
                except Exception as e:
                    logger.warning(f"Failed to load plugin {ep.name}: {e}")
        except Exception as e:
            logger.warning(f"Plugin discovery failed: {e}")

        return discovered

    def load_plugin(self, name: str) -> bool:
        """Load a plugin by name."""
        try:
            eps = importlib.metadata.entry_points(group=self.ENTRY_POINT_GROUP)
            for ep in eps:
                if ep.name == name:
                    plugin_class = ep.load()
                    plugin = plugin_class()
                    return self.register_plugin(plugin)

            logger.error(f"Plugin not found: {name}")
            return False
        except Exception as e:
            logger.error(f"Failed to load plugin {name}: {e}")
            return False

    def register_plugin(self, plugin: Plugin) -> bool:
        """Register a plugin and its components."""
        meta = plugin.metadata()

        if meta.name in self._plugins:
            logger.warning(f"Plugin {meta.name} already registered")
            return False

        # Register standard
        standard = plugin.get_standard()
        self._standards[standard.id] = standard

        # Register adapters
        for adapter_class in plugin.get_check_adapters():
            adapter = adapter_class()
            std = adapter.standard()
            if std not in self._check_adapters:
                self._check_adapters[std] = []
            self._check_adapters[std].append(adapter)

        for adapter_class in plugin.get_remediation_adapters():
            adapter = adapter_class()
            std = adapter.standard()
            if std not in self._remediation_adapters:
                self._remediation_adapters[std] = []
            self._remediation_adapters[std].append(adapter)

        # Register MCP tools
        self._mcp_tools.extend(plugin.get_mcp_tools())

        # Store plugin
        self._plugins[meta.name] = plugin
        plugin.on_load(self)

        logger.info(f"Registered plugin: {meta.name} v{meta.version}")
        return True

    def get_standard(self, standard_id: str) -> Optional[Standard]:
        """Get a registered standard by ID."""
        return self._standards.get(standard_id)

    def get_standards(self) -> List[Standard]:
        """Get all registered standards."""
        return list(self._standards.values())

    def get_check_adapters(self, standard: str) -> List[CheckAdapter]:
        """Get check adapters for a standard."""
        return self._check_adapters.get(standard, [])

    def get_all_check_adapters(self) -> List[CheckAdapter]:
        """Get all registered check adapters."""
        adapters = []
        for adapter_list in self._check_adapters.values():
            adapters.extend(adapter_list)
        return adapters

    def find_adapter_for_control(self, control_id: str) -> Optional[CheckAdapter]:
        """Find an adapter that can check a specific control."""
        for adapters in self._check_adapters.values():
            for adapter in adapters:
                if adapter.supports_control(control_id):
                    return adapter
        return None
```

### 3.3 Plugin Entry Point Configuration

```toml
# In a plugin's pyproject.toml

[project.entry-points."security_assurance.plugins"]
osps = "osps_plugin:OSPSPlugin"
slsa = "slsa_plugin:SLSAPlugin"
```

---

## 4. Configuration Model

### 4.1 Enhanced project.toml Schema

```toml
# project.toml - Multi-standard security configuration

schema_version = "0.2"

[project]
name = "my-project"
type = "software"  # software | specification | documentation | infrastructure
description = "My awesome project"

# =============================================================================
# STANDARDS CONFIGURATION
# =============================================================================

# Which standards to check (plugins must be installed)
[standards]
enabled = ["osps", "slsa"]  # Standards to audit against
default_levels = { osps = 3, slsa = 2 }  # Target level per standard

# =============================================================================
# OSPS (OpenSSF Baseline) Configuration
# =============================================================================

[osps]
target_level = 3  # Override default

# Control-specific overrides
[osps.controls]
"OSPS-BR-02.01" = { status = "n/a", reason = "Internal tool, no distributable artifacts" }
"OSPS-VM-05.01" = { status = "n/a", reason = "No external dependencies" }

# =============================================================================
# SLSA Configuration
# =============================================================================

[slsa]
target_level = 2  # SLSA Level 2

# Build configuration
[slsa.build]
builder = "github-actions"  # github-actions | tekton | cloudbuild
workflow = ".github/workflows/release.yml"
provenance_generator = "slsa-github-generator"

# Source requirements
[slsa.source]
version_control = "git"
verified_history = true
two_person_review = true

# Artifacts to verify
[[slsa.artifacts]]
name = "my-project"
type = "container"
registry = "ghcr.io/myorg/my-project"

[[slsa.artifacts]]
name = "my-project-cli"
type = "binary"
path = "dist/"

# =============================================================================
# SHARED DOCUMENTATION REFERENCES
# =============================================================================
# These are used by multiple standards

[security]
policy = { path = "SECURITY.md" }
threat_model = { path = "docs/THREAT_MODEL.md" }
advisories = { url = "https://github.com/myorg/myproject/security/advisories" }

[governance]
maintainers = { path = "MAINTAINERS.md" }
contributing = { path = "CONTRIBUTING.md" }
code_of_conduct = { path = "CODE_OF_CONDUCT.md" }
codeowners = { path = ".github/CODEOWNERS" }

[legal]
license = { path = "LICENSE" }
contributor_agreement = { type = "dco" }

[artifacts]
sbom = { path = "sbom.json", format = "cyclonedx" }
signing = { enabled = true, method = "sigstore" }
provenance = { enabled = true, format = "slsa" }

[quality]
changelog = { path = "CHANGELOG.md" }

[ci]
provider = "github"

[ci.github]
workflows = [".github/workflows/ci.yml", ".github/workflows/release.yml"]
security_scanning = [".github/workflows/codeql.yml"]
dependency_management = ".github/dependabot.yml"

# =============================================================================
# CUSTOM STANDARD (Example)
# =============================================================================

[custom.myorg-security]
target_level = 2

[custom.myorg-security.controls]
# Map to internal security requirements
"MYORG-SEC-01" = { enabled = true }
"MYORG-SEC-02" = { enabled = true }
```

### 4.2 Config Models

```python
# security_assurance/config/models.py

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set
from enum import Enum


class ProjectType(Enum):
    SOFTWARE = "software"
    SPECIFICATION = "specification"
    DOCUMENTATION = "documentation"
    INFRASTRUCTURE = "infrastructure"
    DATA = "data"


@dataclass
class StandardConfig:
    """Configuration for a specific standard."""
    standard_id: str
    enabled: bool = True
    target_level: int = 1
    control_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    extra_config: Dict[str, Any] = field(default_factory=dict)

    def is_control_enabled(self, control_id: str) -> tuple[bool, Optional[str]]:
        """Check if a control is enabled, return (enabled, reason_if_disabled)."""
        override = self.control_overrides.get(control_id, {})
        status = override.get("status", "enabled")
        if status == "n/a":
            return False, override.get("reason", "Marked as N/A")
        if status == "disabled":
            return False, override.get("reason", "Disabled")
        return True, None


@dataclass
class ProjectConfig:
    """Complete project configuration from project.toml."""
    # Metadata
    schema_version: str = "0.2"
    config_path: Optional[str] = None

    # Project info
    name: Optional[str] = None
    project_type: str = "software"
    description: Optional[str] = None

    # Standards configuration
    enabled_standards: List[str] = field(default_factory=list)
    standard_configs: Dict[str, StandardConfig] = field(default_factory=dict)

    # Shared resource references
    security: Dict[str, Any] = field(default_factory=dict)
    governance: Dict[str, Any] = field(default_factory=dict)
    legal: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    quality: Dict[str, Any] = field(default_factory=dict)
    documentation: Dict[str, Any] = field(default_factory=dict)
    ci: Dict[str, Any] = field(default_factory=dict)

    # Custom standards
    custom: Dict[str, StandardConfig] = field(default_factory=dict)

    def get_standard_config(self, standard_id: str) -> Optional[StandardConfig]:
        """Get configuration for a specific standard."""
        return self.standard_configs.get(standard_id)

    def get_enabled_standards(self) -> List[str]:
        """Get list of enabled standard IDs."""
        return [
            sid for sid, cfg in self.standard_configs.items()
            if cfg.enabled
        ]
```

---

## 5. Check Orchestration

### 5.1 Orchestrator

```python
# security_assurance/core/orchestrator.py

from dataclasses import dataclass
from typing import Dict, List, Optional, Set
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from .models import CheckResult, CheckStatus, AuditResult
from .adapters import CheckAdapter, CheckContext
from .registry import PluginRegistry
from ..config.schema import ProjectConfig
from ..standards.base import Standard

logger = logging.getLogger(__name__)


@dataclass
class AuditOptions:
    """Options for running an audit."""
    standards: Optional[List[str]] = None  # None = all enabled
    levels: Optional[Dict[str, int]] = None  # Override target levels
    controls: Optional[List[str]] = None  # Specific controls to check
    skip_controls: Optional[Set[str]] = None
    parallel: bool = True
    max_workers: int = 4
    fail_fast: bool = False


class CheckOrchestrator:
    """Orchestrates check execution across multiple standards and plugins."""

    def __init__(self, registry: PluginRegistry):
        self.registry = registry

    def run_audit(
        self,
        context: CheckContext,
        options: AuditOptions = None,
    ) -> AuditResult:
        """Run a complete audit across all configured standards."""
        options = options or AuditOptions()
        config = context.config

        # Determine which standards to check
        standards_to_check = self._resolve_standards(config, options)

        # Initialize result
        result = AuditResult(
            owner=context.owner,
            repo=context.repo,
            local_path=context.local_path,
            commit=context.cache.get("commit"),
            ref=context.cache.get("ref"),
            standards_checked=list(standards_to_check.keys()),
        )

        # Run checks for each standard
        for standard_id, standard in standards_to_check.items():
            std_config = config.get_standard_config(standard_id)
            target_level = options.levels.get(standard_id) if options.levels else None
            target_level = target_level or (std_config.target_level if std_config else standard.default_level)

            # Get controls to check
            controls = self._get_controls_to_check(
                standard, target_level, std_config, options
            )

            # Get adapters for this standard
            adapters = self.registry.get_check_adapters(standard_id)

            # Run checks
            std_results = self._run_standard_checks(
                standard_id, controls, adapters, context, options
            )

            result.results_by_standard[standard_id] = std_results

            # Calculate compliance
            result.compliance[standard_id] = self._calculate_compliance(
                std_results, standard, target_level
            )

        # Calculate summary
        result.summary = self._calculate_summary(result.all_results)
        result.plugins_used = [a.name() for a in self.registry.get_all_check_adapters()]

        return result

    def _resolve_standards(
        self,
        config: ProjectConfig,
        options: AuditOptions,
    ) -> Dict[str, Standard]:
        """Resolve which standards to check."""
        if options.standards:
            standard_ids = options.standards
        else:
            standard_ids = config.get_enabled_standards() or [
                s.id for s in self.registry.get_standards()
            ]

        return {
            sid: self.registry.get_standard(sid)
            for sid in standard_ids
            if self.registry.get_standard(sid)
        }

    def _get_controls_to_check(
        self,
        standard: Standard,
        target_level: int,
        std_config: Optional["StandardConfig"],
        options: AuditOptions,
    ) -> List[str]:
        """Determine which controls to check."""
        # Start with all controls up to target level
        controls = [c.id for c in standard.get_controls_for_level(target_level)]

        # Filter by explicit control list if provided
        if options.controls:
            controls = [c for c in controls if c in options.controls]

        # Remove skipped controls
        if options.skip_controls:
            controls = [c for c in controls if c not in options.skip_controls]

        # Remove controls disabled in config
        if std_config:
            controls = [
                c for c in controls
                if std_config.is_control_enabled(c)[0]
            ]

        return controls

    def _run_standard_checks(
        self,
        standard_id: str,
        controls: List[str],
        adapters: List[CheckAdapter],
        context: CheckContext,
        options: AuditOptions,
    ) -> List[CheckResult]:
        """Run checks for a single standard."""
        results = []

        # Group controls by adapter
        adapter_controls: Dict[CheckAdapter, List[str]] = {}
        unhandled = set(controls)

        for adapter in adapters:
            handled = [c for c in unhandled if adapter.supports_control(c)]
            if handled:
                adapter_controls[adapter] = handled
                unhandled -= set(handled)

        # Warn about unhandled controls
        for control_id in unhandled:
            logger.warning(f"No adapter found for control: {control_id}")
            results.append(CheckResult(
                control_id=control_id,
                standard=standard_id,
                status=CheckStatus.ERROR,
                message="No adapter available for this control",
            ))

        # Execute checks
        if options.parallel and len(adapter_controls) > 1:
            results.extend(self._run_parallel(adapter_controls, context, options))
        else:
            results.extend(self._run_sequential(adapter_controls, context, options))

        return results

    def _run_parallel(
        self,
        adapter_controls: Dict[CheckAdapter, List[str]],
        context: CheckContext,
        options: AuditOptions,
    ) -> List[CheckResult]:
        """Run checks in parallel."""
        results = []

        with ThreadPoolExecutor(max_workers=options.max_workers) as executor:
            futures = {}

            for adapter, controls in adapter_controls.items():
                if adapter.capabilities().supports_batch:
                    future = executor.submit(adapter.check_batch, controls, context)
                    futures[future] = (adapter, controls)
                else:
                    for control in controls:
                        future = executor.submit(adapter.check, control, context)
                        futures[future] = (adapter, [control])

            for future in as_completed(futures):
                adapter, controls = futures[future]
                try:
                    result = future.result()
                    if isinstance(result, list):
                        results.extend(result)
                    else:
                        results.append(result)
                except Exception as e:
                    for control in controls:
                        results.append(CheckResult(
                            control_id=control,
                            standard=adapter.standard(),
                            status=CheckStatus.ERROR,
                            message=f"Check failed: {str(e)}",
                            source=adapter.name(),
                        ))

        return results

    def _run_sequential(
        self,
        adapter_controls: Dict[CheckAdapter, List[str]],
        context: CheckContext,
        options: AuditOptions,
    ) -> List[CheckResult]:
        """Run checks sequentially."""
        results = []

        for adapter, controls in adapter_controls.items():
            try:
                if adapter.capabilities().supports_batch:
                    results.extend(adapter.check_batch(controls, context))
                else:
                    for control in controls:
                        results.append(adapter.check(control, context))
            except Exception as e:
                for control in controls:
                    results.append(CheckResult(
                        control_id=control,
                        standard=adapter.standard(),
                        status=CheckStatus.ERROR,
                        message=f"Check failed: {str(e)}",
                        source=adapter.name(),
                    ))

        return results

    def _calculate_compliance(
        self,
        results: List[CheckResult],
        standard: Standard,
        target_level: int,
    ) -> Dict[int, bool]:
        """Calculate compliance for each level."""
        compliance = {}

        for level in standard.levels:
            if level > target_level:
                break

            level_controls = {c.id for c in standard.get_controls_for_level(level)}
            level_results = [r for r in results if r.control_id in level_controls]

            # Level is compliant if no FAIL status
            compliance[level] = all(
                r.status not in (CheckStatus.FAIL, CheckStatus.ERROR)
                for r in level_results
            )

        return compliance

    def _calculate_summary(self, results: List[CheckResult]) -> Dict[str, int]:
        """Calculate summary counts."""
        summary = {status.value.upper(): 0 for status in CheckStatus}
        summary["TOTAL"] = len(results)

        for result in results:
            summary[result.status.value.upper()] += 1

        return summary
```

---

## 6. SLSA Plugin Example

### 6.1 SLSA Standard Definition

```python
# plugins/slsa/standard.py

from security_assurance.standards.base import Standard, ControlDefinition


SLSA_CONTROLS = {
    # Level 1
    "SLSA-BUILD-L1": ControlDefinition(
        id="SLSA-BUILD-L1",
        standard="slsa",
        title="Build - Level 1",
        description="Build process exists and produces provenance",
        verification="Check for build automation and basic provenance",
        tags={"level": 1, "domain": "BUILD", "security_severity": 7.0, "build": True},
    ),

    # Level 2
    "SLSA-BUILD-L2": ControlDefinition(
        id="SLSA-BUILD-L2",
        standard="slsa",
        title="Build - Level 2",
        description="Build service generates authenticated provenance",
        verification="Verify provenance is signed by build service",
        tags={"level": 2, "domain": "BUILD", "security_severity": 8.0, "build": True, "provenance": True},
    ),
    "SLSA-SOURCE-L2": ControlDefinition(
        id="SLSA-SOURCE-L2",
        standard="slsa",
        title="Source - Level 2",
        description="Version controlled with verified history",
        verification="Check for version control and history retention",
        tags={"level": 2, "domain": "SOURCE", "security_severity": 7.5, "source": True, "version-control": True},
    ),

    # Level 3
    "SLSA-BUILD-L3": ControlDefinition(
        id="SLSA-BUILD-L3",
        standard="slsa",
        title="Build - Level 3",
        description="Build on hardened, isolated build service",
        verification="Verify build service meets isolation requirements",
        tags={"level": 3, "domain": "BUILD", "security_severity": 9.0, "build": True, "hardened": True},
    ),
    "SLSA-SOURCE-L3": ControlDefinition(
        id="SLSA-SOURCE-L3",
        standard="slsa",
        title="Source - Level 3",
        description="Two-person review required for all changes",
        verification="Check for mandatory code review",
        tags={"level": 3, "domain": "SOURCE", "security_severity": 8.5, "source": True, "code-review": True},
    ),

    # Level 4 (future)
    # ...
}


SLSA_STANDARD = Standard(
    id="slsa",
    name="SLSA (Supply-chain Levels for Software Artifacts)",
    version="v1.0",
    url="https://slsa.dev/spec/v1.0/",
    levels=[1, 2, 3, 4],
    domains={
        "BUILD": "Build Process",
        "SOURCE": "Source Code",
        "DEPS": "Dependencies",
        "PROVENANCE": "Provenance",
    },
    controls=SLSA_CONTROLS,
    config_section="slsa",
    default_level=1,
)
```

### 6.2 SLSA Check Adapter

```python
# plugins/slsa/adapters.py

from typing import Dict, List, Set
from security_assurance.core.adapters import CheckAdapter, AdapterCapability, CheckContext
from security_assurance.core.models import CheckResult, CheckStatus


class SLSABuildAdapter(CheckAdapter):
    """Check SLSA build requirements."""

    def name(self) -> str:
        return "slsa-build-checker"

    def standard(self) -> str:
        return "slsa"

    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            standard="slsa",
            control_ids={"SLSA-BUILD-L1", "SLSA-BUILD-L2", "SLSA-BUILD-L3"},
            supports_batch=True,
            requires_local=True,
            config_sections=["slsa.build", "artifacts"],
        )

    def check(self, control_id: str, context: CheckContext) -> CheckResult:
        """Check a single SLSA build control."""
        slsa_config = context.standard_config
        build_config = slsa_config.get("build", {})

        if control_id == "SLSA-BUILD-L1":
            return self._check_build_l1(context, build_config)
        elif control_id == "SLSA-BUILD-L2":
            return self._check_build_l2(context, build_config)
        elif control_id == "SLSA-BUILD-L3":
            return self._check_build_l3(context, build_config)

        return CheckResult(
            control_id=control_id,
            standard="slsa",
            status=CheckStatus.ERROR,
            message=f"Unknown control: {control_id}",
            source=self.name(),
        )

    def _check_build_l1(self, context: CheckContext, config: Dict) -> CheckResult:
        """SLSA Build L1: Build process exists."""
        # Check for CI workflow
        workflow = config.get("workflow")
        if workflow:
            workflow_path = f"{context.local_path}/{workflow}"
            if context.file_exists(workflow_path):
                return CheckResult(
                    control_id="SLSA-BUILD-L1",
                    standard="slsa",
                    status=CheckStatus.PASS,
                    message=f"Build workflow exists: {workflow}",
                    evidence_location=workflow,
                    source=self.name(),
                )

        # Auto-detect common patterns
        common_workflows = [
            ".github/workflows/build.yml",
            ".github/workflows/ci.yml",
            ".github/workflows/release.yml",
        ]
        for wf in common_workflows:
            if context.file_exists(f"{context.local_path}/{wf}"):
                return CheckResult(
                    control_id="SLSA-BUILD-L1",
                    standard="slsa",
                    status=CheckStatus.PASS,
                    message=f"Build workflow detected: {wf}",
                    evidence_location=wf,
                    source=self.name(),
                )

        return CheckResult(
            control_id="SLSA-BUILD-L1",
            standard="slsa",
            status=CheckStatus.FAIL,
            message="No build workflow found",
            source=self.name(),
        )

    def _check_build_l2(self, context: CheckContext, config: Dict) -> CheckResult:
        """SLSA Build L2: Authenticated provenance."""
        # Check for SLSA generator or similar
        provenance_gen = config.get("provenance_generator")

        if provenance_gen == "slsa-github-generator":
            # Look for SLSA generator usage in workflows
            # This would search workflow files for slsa-framework/slsa-github-generator
            pass

        # Check artifacts config
        artifacts_config = context.config.artifacts
        if artifacts_config.get("provenance", {}).get("enabled"):
            return CheckResult(
                control_id="SLSA-BUILD-L2",
                standard="slsa",
                status=CheckStatus.PASS,
                message="Provenance generation is configured",
                source=self.name(),
            )

        return CheckResult(
            control_id="SLSA-BUILD-L2",
            standard="slsa",
            status=CheckStatus.FAIL,
            message="No authenticated provenance generation configured",
            remediation_available=True,
            remediation_category="slsa_provenance",
            source=self.name(),
        )

    def _check_build_l3(self, context: CheckContext, config: Dict) -> CheckResult:
        """SLSA Build L3: Hardened build service."""
        builder = config.get("builder", "").lower()

        # Check for known hardened builders
        hardened_builders = ["github-actions", "google-cloud-build", "tekton"]

        if builder in hardened_builders:
            return CheckResult(
                control_id="SLSA-BUILD-L3",
                standard="slsa",
                status=CheckStatus.PASS,
                message=f"Using hardened builder: {builder}",
                source=self.name(),
            )

        return CheckResult(
            control_id="SLSA-BUILD-L3",
            standard="slsa",
            status=CheckStatus.WARN,
            message="Cannot verify build service hardening. Configure slsa.build.builder",
            source=self.name(),
        )
```

### 6.3 SLSA Plugin Registration

```python
# plugins/slsa/__init__.py

from typing import List, Type
from security_assurance.core.plugin import Plugin, PluginMetadata
from security_assurance.core.adapters import CheckAdapter, RemediationAdapter
from security_assurance.standards.base import Standard

from .standard import SLSA_STANDARD
from .adapters import SLSABuildAdapter, SLSASourceAdapter


class SLSAPlugin(Plugin):
    """SLSA compliance verification plugin."""

    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="slsa",
            version="1.0.0",
            description="SLSA (Supply-chain Levels for Software Artifacts) compliance checks",
            author="OpenSSF",
            standards=["slsa"],
            requires_framework=">=0.1.0",
        )

    def get_standard(self) -> Standard:
        return SLSA_STANDARD

    def get_check_adapters(self) -> List[Type[CheckAdapter]]:
        return [
            SLSABuildAdapter,
            SLSASourceAdapter,
        ]

    def get_remediation_adapters(self) -> List[Type[RemediationAdapter]]:
        return []  # TODO: Add remediation support
```

---

## 7. MCP Server Integration

### 7.1 Unified MCP Tools

```python
# security_assurance/server/tools.py

from typing import Optional, List
import json

from ..core.registry import PluginRegistry
from ..core.orchestrator import CheckOrchestrator, AuditOptions
from ..core.adapters import CheckContext
from ..config.loader import load_project_config
from ..formatters import sarif, markdown


def create_audit_tools(registry: PluginRegistry, mcp):
    """Create and register MCP audit tools."""
    orchestrator = CheckOrchestrator(registry)

    @mcp.tool()
    def audit(
        owner: Optional[str] = None,
        repo: Optional[str] = None,
        local_path: str = ".",
        standards: Optional[List[str]] = None,
        levels: Optional[dict] = None,
        output_format: str = "markdown",
    ) -> str:
        """
        Run security audit against configured standards.

        Args:
            owner: GitHub owner (auto-detected if not provided)
            repo: Repository name (auto-detected if not provided)
            local_path: Path to repository
            standards: Standards to check (default: all enabled in config)
            levels: Override target levels per standard
            output_format: Output format (markdown, json, sarif)

        Returns:
            Formatted audit report
        """
        # Load config
        config = load_project_config(local_path)

        # Build context
        context = CheckContext(
            owner=owner or "unknown",
            repo=repo or "unknown",
            local_path=local_path,
            default_branch="main",
            config=config,
            standard_config={},  # Populated per-standard during audit
        )

        # Build options
        options = AuditOptions(
            standards=standards,
            levels=levels,
        )

        # Run audit
        result = orchestrator.run_audit(context, options)

        # Format output
        if output_format == "sarif":
            return json.dumps(sarif.generate_sarif(result), indent=2)
        elif output_format == "json":
            return json.dumps(result_to_dict(result), indent=2)
        else:
            return markdown.generate_report(result)

    @mcp.tool()
    def list_standards() -> str:
        """List all available security standards."""
        standards = registry.get_standards()

        output = ["# Available Security Standards\n"]
        for std in standards:
            output.append(f"## {std.name} ({std.id})")
            output.append(f"- Version: {std.version}")
            output.append(f"- Levels: {std.levels}")
            output.append(f"- Controls: {len(std.controls)}")
            output.append(f"- URL: {std.url}")
            output.append("")

        return "\n".join(output)

    @mcp.tool()
    def list_controls(
        standard: Optional[str] = None,
        level: Optional[int] = None,
    ) -> str:
        """
        List available controls.

        Args:
            standard: Filter by standard ID
            level: Filter by maturity level
        """
        controls = []

        for std in registry.get_standards():
            if standard and std.id != standard:
                continue

            for control in std.controls.values():
                if level and control.level != level:
                    continue
                controls.append({
                    "id": control.id,
                    "standard": std.id,
                    "level": control.level,
                    "domain": control.domain,
                    "title": control.title,
                })

        return json.dumps(controls, indent=2)

    return [audit, list_standards, list_controls]
```

---

## 8. Implementation Roadmap

### Phase 1: Framework Core (Weeks 1-2)
1. Extract core models and adapters to `security_assurance/core/`
2. Implement `PluginRegistry` with entry-point discovery
3. Implement `CheckOrchestrator` for multi-standard audits
4. Create config schema with multi-standard support
5. Extract SARIF formatter

### Phase 2: OSPS Plugin (Week 3)
1. Refactor current OSPS checks into adapter classes
2. Create `OSPSPlugin` with standard definition
3. Register as entry point plugin
4. Maintain backward compatibility with current API

### Phase 3: SLSA Plugin (Weeks 4-5)
1. Define SLSA standard and controls
2. Implement build verification adapter
3. Implement source verification adapter
4. Add provenance verification
5. Add remediation for SLSA workflow generation

### Phase 4: Integration & Polish (Week 6)
1. Unified MCP tools (`audit`, `list_standards`, etc.)
2. Cross-standard reporting
3. Documentation
4. Plugin development guide

### Phase 5: Additional Plugins (Future)
- OpenSSF Scorecard integration
- Custom organizational standards
- CIS Benchmarks
- SOC2 mapping

---

## 9. Migration Path

### For Existing Users

```python
# Old API (still works)
from baseline_mcp import audit_openssf_baseline
result = audit_openssf_baseline(owner, repo, local_path)

# New API
from security_assurance import audit
result = audit(owner, repo, local_path, standards=["osps"])
```

### Configuration Migration

```toml
# Old: .openssf-baseline.yml (YAML)
# New: project.toml (TOML, superset)

# The framework will read both formats during transition
```

---

## 10. Open Questions

1. **Plugin Distribution**: Separate PyPI packages or monorepo?
2. **Config File Name**: `project.toml` vs `security.toml` vs `.security-assurance.toml`?
3. **Cross-Standard Mapping**: How to handle overlapping controls (OSPS-BR vs SLSA-BUILD)?
4. **Versioning**: How to handle standard version updates (OSPS v2025 vs v2026)?

---

*This document will be updated as the design evolves.*
