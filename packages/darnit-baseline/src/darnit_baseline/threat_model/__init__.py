"""Threat modeling capabilities using STRIDE methodology.

This module provides automated threat analysis for codebases, including:
- Asset discovery (entry points, auth, data stores, secrets)
- STRIDE-based threat identification
- Risk scoring and prioritization
- Report generation (Markdown, SARIF, JSON)

Usage:
    from darnit_baseline.threat_model import (
        discover_all_assets,
        analyze_stride_threats,
        generate_markdown_threat_model,
    )

    # Discover assets
    assets = discover_all_assets("/path/to/repo")

    # Analyze threats
    injection_sinks = discover_injection_sinks("/path/to/repo")
    threats = analyze_stride_threats(assets, injection_sinks)

    # Generate report
    report = generate_markdown_threat_model(
        "/path/to/repo", assets, threats, [], assets.frameworks_detected
    )

Note:
    MCP tool functions (generate_threat_model, analyze_threats, etc.) are
    still in main.py and will be migrated incrementally.
"""

# Data models
# Discovery functions
# Attack chain detection
from .chains import (
    CHAIN_PATTERNS,
    calculate_composite_risk,
    detect_attack_chains,
)
from .discovery import (
    detect_frameworks,
    discover_all_assets,
    discover_authentication,
    discover_data_stores,
    discover_entry_points,
    discover_injection_sinks,
    discover_secrets,
    discover_sensitive_data,
)

# Output generators
from .generators import (
    generate_json_summary,
    generate_markdown_threat_model,
    generate_mermaid_dfd,
    generate_sarif_threat_model,
)
from .models import (
    AssetInventory,
    AttackChain,
    AuthMechanism,
    CodeLocation,
    DataStore,
    DetailLevel,
    EntryPoint,
    RankedControl,
    RiskLevel,
    RiskScore,
    SecretReference,
    SensitiveData,
    StrideCategory,
    Threat,
    ThreatAnalysis,
)

# Detection patterns
from .patterns import (
    AUTH_PATTERNS,
    DATASTORE_PATTERNS,
    FRAMEWORK_PATTERNS,
    INJECTION_PATTERNS,
    SECRET_PATTERNS,
    SENSITIVE_DATA_PATTERNS,
    SKIP_DIRECTORIES,
    SOURCE_EXTENSIONS,
)

# Remediation handler
from .remediation import generate_threat_model_handler

# Scenario templates
from .scenarios import (
    SCENARIO_TEMPLATES,
    get_scenario,
)

# STRIDE analysis
from .stride import (
    analyze_stride_threats,
    calculate_risk_score,
    identify_control_gaps,
)

__all__ = [
    # Enums
    "StrideCategory",
    "RiskLevel",
    "DetailLevel",
    # Data classes
    "CodeLocation",
    "EntryPoint",
    "DataStore",
    "SensitiveData",
    "SecretReference",
    "AuthMechanism",
    "RiskScore",
    "RankedControl",
    "Threat",
    "AttackChain",
    "AssetInventory",
    "ThreatAnalysis",
    # Patterns
    "FRAMEWORK_PATTERNS",
    "AUTH_PATTERNS",
    "SENSITIVE_DATA_PATTERNS",
    "INJECTION_PATTERNS",
    "SECRET_PATTERNS",
    "DATASTORE_PATTERNS",
    "SKIP_DIRECTORIES",
    "SOURCE_EXTENSIONS",
    # Discovery
    "detect_frameworks",
    "discover_entry_points",
    "discover_authentication",
    "discover_sensitive_data",
    "discover_secrets",
    "discover_data_stores",
    "discover_injection_sinks",
    "discover_all_assets",
    # Analysis
    "calculate_risk_score",
    "analyze_stride_threats",
    "identify_control_gaps",
    # Scenarios
    "SCENARIO_TEMPLATES",
    "get_scenario",
    # Chains
    "CHAIN_PATTERNS",
    "calculate_composite_risk",
    "detect_attack_chains",
    # Remediation
    "generate_threat_model_handler",
    # Generators
    "generate_markdown_threat_model",
    "generate_mermaid_dfd",
    "generate_sarif_threat_model",
    "generate_json_summary",
]
