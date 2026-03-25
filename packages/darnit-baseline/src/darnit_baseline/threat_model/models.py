"""Data structures for threat modeling.

This module contains all the data classes and enums used by the
STRIDE threat analysis engine.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StrideCategory(Enum):
    """STRIDE threat categories."""
    SPOOFING = "spoofing"
    TAMPERING = "tampering"
    REPUDIATION = "repudiation"
    INFORMATION_DISCLOSURE = "information_disclosure"
    DENIAL_OF_SERVICE = "denial_of_service"
    ELEVATION_OF_PRIVILEGE = "elevation_of_privilege"


class RiskLevel(Enum):
    """Risk severity levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


@dataclass
class CodeLocation:
    """Location of code relevant to a threat."""
    file: str
    line_start: int
    line_end: int
    snippet: str = ""
    annotation: str = ""


@dataclass
class EntryPoint:
    """An API entry point discovered in the codebase."""
    id: str
    entry_type: str  # api_route, graphql, websocket, webhook, scheduled, server_action
    path: str
    method: str
    file: str
    line: int
    authentication_required: bool
    framework: str
    parameters: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DataStore:
    """A data storage system detected in the codebase."""
    id: str
    store_type: str  # database, cache, file_system, external_storage
    technology: str
    file: str
    line: int
    contains_pii: bool = False
    contains_financial: bool = False
    encryption_at_rest: bool = False


@dataclass
class SensitiveData:
    """A field or variable that may contain sensitive data."""
    id: str
    data_type: str  # pii, financial, health, authentication, business
    field_name: str
    file: str
    line: int
    context: str = ""


@dataclass
class SecretReference:
    """A potential secret or credential in the codebase."""
    id: str
    secret_type: str  # hardcoded, env_reference
    name: str
    file: str
    line: int
    severity: str = "high"


@dataclass
class AuthMechanism:
    """An authentication mechanism detected in the codebase."""
    id: str
    auth_type: str  # nextauth, clerk, supabase, passport, jwt, custom
    file: str
    line: int
    framework: str
    assets: list[str] = field(default_factory=list)


@dataclass
class RiskScore:
    """Calculated risk score for a threat."""
    overall: float
    level: RiskLevel
    likelihood: float
    impact: float
    control_effectiveness: float
    factors: dict[str, Any] = field(default_factory=dict)


class DetailLevel(Enum):
    """Detail level for threat model output."""
    SUMMARY = "summary"
    DETAILED = "detailed"


@dataclass
class RankedControl:
    """A recommended control ranked by effectiveness."""
    control: str
    effectiveness: str  # "high", "medium", "low"
    rationale: str


@dataclass
class Threat:
    """A security threat identified through STRIDE analysis."""
    id: str
    category: StrideCategory
    title: str
    description: str
    affected_assets: list[str]
    attack_vector: str
    prerequisites: list[str]
    risk: RiskScore
    existing_controls: list[str]
    recommended_controls: list[str]
    code_locations: list[CodeLocation]
    references: list[str] = field(default_factory=list)
    exploitation_scenario: list[str] = field(default_factory=list)
    data_flow_impact: str = ""
    ranked_controls: list["RankedControl"] = field(default_factory=list)
    attack_chain_ids: list[str] = field(default_factory=list)


@dataclass
class AssetInventory:
    """Inventory of security-relevant assets discovered in the codebase."""
    entry_points: list[EntryPoint]
    data_stores: list[DataStore]
    sensitive_data: list[SensitiveData]
    secrets: list[SecretReference]
    authentication: list[AuthMechanism]
    frameworks_detected: list[str]
    external_services: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AttackChain:
    """A compound attack path combining multiple threats."""
    id: str
    name: str
    description: str
    threat_ids: list[str]
    categories: list[StrideCategory]
    shared_assets: list[str]
    composite_risk: RiskScore


@dataclass
class ThreatAnalysis:
    """Complete threat analysis result."""
    methodology: str
    threats: list[Threat]
    control_gaps: list[dict[str, Any]]
    summary: dict[str, Any]
    attack_chains: list[AttackChain] = field(default_factory=list)


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
]
