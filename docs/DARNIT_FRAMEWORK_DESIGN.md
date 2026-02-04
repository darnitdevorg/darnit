# Darnit Framework - Design Document

> **Status**: ⚠️ DEPRECATED - See authoritative spec
> **Last Updated**: 2025-12-04
>
> **DEPRECATION NOTICE**: This document has been superseded by the authoritative
> framework specification at `openspec/specs/framework-design/spec.md`.
> Please refer to that document for current framework design decisions.
> Generated documentation is available at `docs/generated/`.
>
> *"Darnit patches holes in your software - like darning a sock, but for code."*

---

## 1. Vision

**Darnit** is a pluggable security and quality assurance framework that:

1. **Unifies multiple standards** (OSPS, SLSA, Scorecard, custom) under one configuration
2. **Supports open and proprietary plugins** - mix OSS community checks with internal compliance
3. **Enables intelligent decision-making** through MCP-to-LLM interaction for ambiguous situations
4. **Provides a canonical project configuration** (`project.toml`) that multiple tools can read/write

### Design Principles

| Principle | Description |
|-----------|-------------|
| **Plugin-First** | Core framework is minimal; all checks come from plugins |
| **Config-Centric** | `project.toml` is the source of truth for project metadata |
| **Progressive Verification** | Sieve model: deterministic → heuristic → manual verification |
| **LLM-Augmented** | MCPs can consult the AI for context-aware decisions |
| **Open Ecosystem** | Clear plugin interface supports OSS and proprietary implementations |
| **Fail to Manual** | When uncertain, always fall back to human verification (WARN) |

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AI Agent / LLM                                  │
│                    (Claude, GPT, or other MCP host)                         │
└─────────────────────────────────────────────────────────────────────────────┘
         │                           ▲
         │ MCP Protocol              │ Consultation Requests
         ▼                           │ (ambiguity, overlap, guidance)
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Darnit MCP Server                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │    Audit     │  │  Remediate   │  │   Attest     │  │   Consult    │    │
│  │    Tools     │  │    Tools     │  │    Tools     │  │    Tools     │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Darnit Core                                       │
│                                                                              │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────────────────┐    │
│  │ Plugin         │  │ Config         │  │ Decision Engine            │    │
│  │ Registry       │  │ Manager        │  │ (LLM Consultation)         │    │
│  └────────────────┘  └────────────────┘  └────────────────────────────┘    │
│                                                                              │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────────────────┐    │
│  │ Standard       │  │ Check          │  │ Result                     │    │
│  │ Registry       │  │ Orchestrator   │  │ Aggregator                 │    │
│  └────────────────┘  └────────────────┘  └────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
            ┌────────────────────────┼────────────────────────┐
            │                        │                        │
            ▼                        ▼                        ▼
┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
│   darnit-osps        │  │   darnit-slsa        │  │   acme-compliance    │
│   (Open Source)      │  │   (Open Source)      │  │   (Proprietary)      │
│                      │  │                      │  │                      │
│  • OSPS checks       │  │  • SLSA verification │  │  • Internal policies │
│  • Remediations      │  │  • Provenance        │  │  • SOC2 mapping      │
│  • Attestations      │  │  • Build analysis    │  │  • Custom checks     │
└──────────────────────┘  └──────────────────────┘  └──────────────────────┘
```

---

## 3. Progressive Verification Model (The "Sieve" Architecture)

### 3.1 Core Philosophy

Darnit uses a **progressive verification model** that processes checks and remediations through increasingly sophisticated "sieves". This ensures:

1. **Efficiency**: Simple, deterministic checks run first without LLM overhead
2. **Accuracy**: Heuristic analysis only when needed, with full context
3. **Transparency**: Clear distinction between automated and human-assisted decisions
4. **Safety**: Always fall back to manual verification when uncertain

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     PROGRESSIVE VERIFICATION PIPELINE                        │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  PASS 1: DETERMINISTIC (Non-Heuristic)                              │    │
│  │  ─────────────────────────────────────────                          │    │
│  │  • File existence checks (SECURITY.md, LICENSE, etc.)               │    │
│  │  • project.toml configuration lookups                               │    │
│  │  • GitHub API calls (branch protection, MFA settings)               │    │
│  │  • Manifest parsing (package.json, pyproject.toml)                  │    │
│  │  • Pattern matching (SPDX identifiers, email formats)               │    │
│  │                                                                      │    │
│  │  Result: PASS | FAIL | → Continue to Pass 2                         │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  PASS 2: HEURISTIC (LLM-Assisted)                                   │    │
│  │  ───────────────────────────────────                                │    │
│  │  • Content analysis (does SECURITY.md have disclosure policy?)      │    │
│  │  • Threat model generation from code analysis                       │    │
│  │  • Architecture documentation assessment                            │    │
│  │  • Contributor vetting policy evaluation                            │    │
│  │  • Evidence interpretation (is this sufficient?)                    │    │
│  │                                                                      │    │
│  │  Result: PASS | FAIL | → Continue to Pass 3                         │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  PASS 3: MANUAL VERIFICATION (Human Required)                       │    │
│  │  ──────────────────────────────────────────                         │    │
│  │  • MFA verification for personal accounts                           │    │
│  │  • Contributor identity verification                                │    │
│  │  • Legal review requirements                                        │    │
│  │  • Ambiguous or context-dependent controls                          │    │
│  │                                                                      │    │
│  │  Result: WARN (Needs Verification) - Always requires human review   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Verification Pass Details

#### Pass 1: Deterministic Checks

These checks have **no ambiguity** and can be fully automated:

| Check Type | Example | Result |
|------------|---------|--------|
| File exists | `SECURITY.md` present | ✅ PASS or ❌ FAIL |
| API query | Branch protection enabled via `gh api` | ✅ PASS or ❌ FAIL |
| Config lookup | `[security] policy = { path = "..." }` in project.toml | ✅ PASS or ❌ FAIL |
| Pattern match | License has SPDX identifier | ✅ PASS or ❌ FAIL |
| Manifest parse | Lockfile exists and is valid | ✅ PASS or ❌ FAIL |

**Key principle**: If the check can be expressed as a simple boolean with no interpretation needed, it belongs in Pass 1.

```python
# Pass 1 Example: Branch protection check
def check_branch_protection(owner: str, repo: str, branch: str) -> CheckResult:
    """Pure API check - no heuristics needed."""
    protection = gh_api(f"/repos/{owner}/{repo}/branches/{branch}/protection")

    if protection is None:
        return CheckResult(status="FAIL", details="Branch protection not enabled")

    if protection.get("required_pull_request_reviews", {}).get("required_approving_review_count", 0) < 1:
        return CheckResult(status="FAIL", details="No review requirements configured")

    return CheckResult(status="PASS", details="Branch protection properly configured")
```

#### Pass 2: Heuristic Checks

These checks require **interpretation** and benefit from LLM analysis:

| Check Type | Example | Why Heuristic |
|------------|---------|---------------|
| Content quality | Does SECURITY.md explain disclosure process? | Requires understanding prose |
| Architecture analysis | Does the architecture doc cover security? | Requires domain knowledge |
| Threat modeling | What are the security risks for this codebase? | Requires code understanding |
| Evidence sufficiency | Is this README sufficient for maintainer docs? | Requires judgment |

**Key principle**: If the check requires understanding context, intent, or quality, it moves to Pass 2.

```python
# Pass 2 Example: Security policy content analysis
def check_security_policy_content(security_md_path: str) -> CheckResult:
    """Heuristic check - requires LLM interpretation."""
    content = read_file(security_md_path)

    # First, try simple pattern matching (Pass 1 style)
    has_email = re.search(r'[\w.-]+@[\w.-]+', content)
    has_disclosure = re.search(r'disclos|report|vulnerabilit', content, re.I)

    if has_email and has_disclosure:
        return CheckResult(status="PASS", details="Security policy has contact and disclosure info")

    # If patterns insufficient, escalate to LLM analysis
    analysis = consult_llm(
        type="evidence_interpretation",
        question="Does this SECURITY.md adequately explain how to report vulnerabilities?",
        context={"content": content}
    )

    if analysis.confidence > 0.8:
        return CheckResult(status=analysis.status, details=analysis.reasoning)

    # Insufficient confidence → escalate to Pass 3
    return CheckResult(
        status="WARN",
        details="Security policy content requires human verification",
        evidence={"content_preview": content[:500]}
    )
```

#### Pass 3: Manual Verification

These checks **cannot be automated** and must return WARN:

| Check Type | Example | Why Manual |
|------------|---------|------------|
| Identity verification | Is this contributor who they claim to be? | Legal/identity requirements |
| Personal account MFA | Does this personal GitHub account have MFA? | API limitation |
| Policy interpretation | Does our internal policy allow this exception? | Organization-specific |
| Legal review | Is this license acceptable for our use case? | Legal judgment |

**Key principle**: When automation cannot provide confidence, be honest and require human review.

```python
# Pass 3 Example: MFA for personal accounts
def check_mfa_enabled(owner: str) -> CheckResult:
    """Some checks cannot be automated - always require manual verification."""
    user_type = gh_api(f"/users/{owner}")["type"]

    if user_type == "Organization":
        # Organizations expose MFA settings - can check deterministically
        org = gh_api(f"/orgs/{owner}")
        if org.get("two_factor_requirement_enabled"):
            return CheckResult(status="PASS", details="Org MFA requirement enabled")
        return CheckResult(status="FAIL", details="Org MFA requirement not enabled")

    # Personal accounts - cannot verify MFA via API
    # MUST return WARN, never guess or assume
    return CheckResult(
        status="WARN",
        details="MFA status cannot be verified for personal accounts via API. Manual verification required.",
        verification_steps=[
            "Ask the account owner to confirm MFA is enabled",
            "Check organization membership for MFA-required orgs",
            "Review GitHub security audit logs if available"
        ]
    )
```

### 3.3 Remediation Tiers

The same progressive model applies to **remediations**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PROGRESSIVE REMEDIATION PIPELINE                      │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  TIER 1: DETERMINISTIC REMEDIATION (Fully Automated)                │    │
│  │  ─────────────────────────────────────────────────────              │    │
│  │  • Enable branch protection (specific API calls)                    │    │
│  │  • Create SECURITY.md from template                                 │    │
│  │  • Add .gitignore entries                                           │    │
│  │  • Configure Dependabot                                             │    │
│  │  • Enable secret scanning                                           │    │
│  │                                                                      │    │
│  │  Approach: Direct API calls or file writes with known content       │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  TIER 2: HEURISTIC REMEDIATION (LLM-Assisted)                       │    │
│  │  ──────────────────────────────────────────────                     │    │
│  │  • Generate threat model based on code analysis                     │    │
│  │  • Write architecture documentation from codebase                   │    │
│  │  • Create contributor guidelines appropriate to project             │    │
│  │  • Draft security policy tailored to project type                   │    │
│  │                                                                      │    │
│  │  Approach: LLM analyzes project context, generates appropriate      │    │
│  │  content, but flags for human review before committing              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  TIER 3: MANUAL REMEDIATION (Human Required)                        │    │
│  │  ─────────────────────────────────────                              │    │
│  │  • Enable MFA on personal accounts (user must do this)              │    │
│  │  • Verify contributor identities                                    │    │
│  │  • Legal review of licenses                                         │    │
│  │  • Org-specific policy decisions                                    │    │
│  │                                                                      │    │
│  │  Approach: Provide clear instructions, cannot automate              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Tier 1: Deterministic Remediation

Actions that are **fully automated** with predictable outcomes:

```python
# Tier 1 Example: Enable branch protection
def remediate_branch_protection(owner: str, repo: str, branch: str = "main") -> RemediationResult:
    """Deterministic remediation - exact API call, predictable outcome."""
    config = {
        "required_status_checks": None,
        "enforce_admins": True,
        "required_pull_request_reviews": {
            "required_approving_review_count": 1,
            "dismiss_stale_reviews": True
        },
        "restrictions": None
    }

    # Direct API call - no heuristics
    result = gh_api_put(
        f"/repos/{owner}/{repo}/branches/{branch}/protection",
        json=config
    )

    if result.success:
        return RemediationResult(status="APPLIED", details="Branch protection enabled")
    return RemediationResult(status="FAILED", details=result.error)
```

#### Tier 2: Heuristic Remediation

Actions that require **project-specific analysis**:

```python
# Tier 2 Example: Generate threat model
def remediate_threat_model(local_path: str) -> RemediationResult:
    """Heuristic remediation - requires code analysis and LLM generation."""

    # Analyze the codebase
    analysis = analyze_codebase(local_path)

    # Use LLM to generate appropriate threat model
    threat_model = generate_threat_model(
        entry_points=analysis.entry_points,
        data_flows=analysis.data_flows,
        auth_mechanisms=analysis.auth_mechanisms,
        external_dependencies=analysis.dependencies
    )

    # IMPORTANT: Flag for human review before applying
    return RemediationResult(
        status="DRAFT",  # Not APPLIED - needs review
        content=threat_model,
        details="Threat model generated based on code analysis. Please review before committing.",
        requires_review=True,
        review_instructions=[
            "Verify identified threats match your understanding of the system",
            "Add any domain-specific threats not detected automatically",
            "Confirm mitigations are appropriate for your risk tolerance"
        ]
    )
```

#### Tier 3: Manual Remediation

Actions that **cannot be automated**:

```python
# Tier 3 Example: MFA enablement
def remediate_mfa(owner: str) -> RemediationResult:
    """Manual remediation - provide instructions, cannot automate."""
    return RemediationResult(
        status="MANUAL_REQUIRED",
        details="MFA must be enabled manually by the account owner",
        instructions=[
            "1. Go to GitHub Settings → Password and authentication",
            "2. Under 'Two-factor authentication', click 'Enable two-factor authentication'",
            "3. Choose authenticator app (recommended) or SMS",
            "4. Save recovery codes in a secure location",
            "5. Re-run audit to verify"
        ],
        documentation_url="https://docs.github.com/en/authentication/securing-your-account-with-two-factor-authentication"
    )
```

### 3.4 Decision Flow for Checks

```python
def run_check(control: Control, context: CheckContext) -> CheckResult:
    """
    Progressive check execution through the sieve.

    Pass 1 → Pass 2 → Pass 3 (only if needed)
    """

    # PASS 1: Deterministic check
    if control.has_deterministic_check:
        result = control.run_deterministic(context)
        if result.is_conclusive:  # PASS or FAIL with high confidence
            return result

    # PASS 2: Heuristic check (only if Pass 1 inconclusive)
    if control.has_heuristic_check:
        result = control.run_heuristic(context)
        if result.confidence > 0.8:  # High confidence from LLM
            return result

    # PASS 3: Manual verification required
    return CheckResult(
        status="WARN",
        details=f"Control {control.id} requires manual verification",
        verification_guidance=control.manual_verification_steps
    )
```

### 3.5 Key Principles

| Principle | Description |
|-----------|-------------|
| **Deterministic First** | Always try the cheapest, fastest, most reliable check first |
| **Escalate Thoughtfully** | Only move to heuristics when deterministic checks are insufficient |
| **Be Honest About Uncertainty** | If confidence is low, say so - don't guess |
| **Never Assume PASS** | When uncertain, default to WARN (needs verification), not PASS |
| **Provide Actionable Guidance** | WARN results must include steps for manual verification |
| **Same Model for Remediation** | Apply the same progressive approach to fixes |
| **Human in the Loop** | Tier 2 remediations should be flagged for review before committing |

---

## 4. LLM Consultation System

### 4.1 The Problem

Security standards overlap. OSPS-BR-03 (build provenance) and SLSA-BUILD-L2 check similar things. When both are enabled:
- Should we run both checks? (comprehensive but redundant)
- Should we deduplicate? (efficient but might miss nuances)
- How do we report overlapping failures?
- What about conflicting remediations?

### 4.2 The Solution: Consultation Protocol

Darnit MCPs can **ask the AI for guidance** on ambiguous situations through a structured consultation protocol.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Consultation Flow                                    │
│                                                                              │
│  1. Plugin detects ambiguity (overlap, conflict, unclear requirement)       │
│  2. Plugin creates ConsultationRequest with context                         │
│  3. Darnit MCP sends request to AI via special tool response                │
│  4. AI analyzes context and provides ConsultationResponse                   │
│  5. Plugin uses response to make decision                                   │
│  6. Decision is cached for similar future situations                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 Consultation Types

```python
# darnit/core/consultation.py

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Any, Optional


class ConsultationType(Enum):
    """Types of consultation requests."""

    # Control overlap - multiple standards check the same thing
    CONTROL_OVERLAP = "control_overlap"

    # Remediation conflict - different fixes for same issue
    REMEDIATION_CONFLICT = "remediation_conflict"

    # Ambiguous requirement - unclear how to interpret a control
    AMBIGUOUS_REQUIREMENT = "ambiguous_requirement"

    # Priority decision - which issues to fix first
    PRIORITY_DECISION = "priority_decision"

    # Custom check guidance - how to evaluate something non-standard
    CUSTOM_CHECK = "custom_check"

    # Evidence interpretation - is this sufficient proof?
    EVIDENCE_INTERPRETATION = "evidence_interpretation"


@dataclass
class ConsultationRequest:
    """Request for AI guidance on an ambiguous situation."""

    # Request identification
    request_id: str
    consultation_type: ConsultationType

    # Context
    context: Dict[str, Any]  # Relevant data for the decision

    # The specific question
    question: str

    # Possible options (if applicable)
    options: List[Dict[str, Any]] = field(default_factory=list)

    # Constraints
    constraints: List[str] = field(default_factory=list)

    # Metadata
    plugin: str  # Which plugin is asking
    standard: Optional[str] = None
    controls: List[str] = field(default_factory=list)

    # Caching
    cache_key: Optional[str] = None  # For caching similar decisions
    cache_ttl: int = 3600  # Seconds to cache decision


@dataclass
class ConsultationResponse:
    """AI response to a consultation request."""

    request_id: str

    # The decision
    decision: str  # Primary recommendation
    reasoning: str  # Explanation of the decision

    # Structured response (type-specific)
    data: Dict[str, Any] = field(default_factory=dict)

    # Confidence and caveats
    confidence: float = 0.8  # 0.0-1.0
    caveats: List[str] = field(default_factory=list)

    # Follow-up actions
    suggested_actions: List[str] = field(default_factory=list)
```

### 4.4 Consultation Examples

#### Example 1: Control Overlap

```python
# OSPS-BR-03.01 (release signing) overlaps with SLSA-BUILD-L2 (authenticated provenance)

request = ConsultationRequest(
    request_id="consult-001",
    consultation_type=ConsultationType.CONTROL_OVERLAP,
    context={
        "controls": [
            {
                "id": "OSPS-BR-03.01",
                "standard": "osps",
                "title": "Release Signing",
                "status": "FAIL",
                "message": "Releases are not signed",
            },
            {
                "id": "SLSA-BUILD-L2",
                "standard": "slsa",
                "title": "Authenticated Provenance",
                "status": "FAIL",
                "message": "No provenance attestation found",
            }
        ],
        "project_type": "software",
        "artifacts": ["container", "binary"],
    },
    question="These controls overlap in their requirements for cryptographic verification of builds. How should I report and remediate this?",
    options=[
        {
            "id": "report_both",
            "description": "Report both failures separately",
            "pros": ["Complete audit trail", "Satisfies both standards"],
            "cons": ["Redundant reporting", "May confuse users"],
        },
        {
            "id": "consolidate",
            "description": "Consolidate into single finding with both control IDs",
            "pros": ["Cleaner output", "Single remediation"],
            "cons": ["May lose standard-specific nuances"],
        },
        {
            "id": "primary_secondary",
            "description": "Report SLSA as primary (more specific), reference OSPS",
            "pros": ["Actionable", "Acknowledges overlap"],
            "cons": ["OSPS-focused users may miss it"],
        },
    ],
    plugin="darnit-core",
    controls=["OSPS-BR-03.01", "SLSA-BUILD-L2"],
    cache_key="overlap:release-signing:provenance",
)

# AI Response
response = ConsultationResponse(
    request_id="consult-001",
    decision="primary_secondary",
    reasoning="""
    SLSA-BUILD-L2 is more specific and actionable - it requires provenance
    attestations in a defined format. OSPS-BR-03.01 is broader (any signing).

    Recommend:
    1. Report SLSA-BUILD-L2 as the primary finding
    2. Add OSPS-BR-03.01 to 'also_addresses' field
    3. Remediation should implement SLSA provenance (satisfies both)
    4. In the report, note: "Implementing SLSA L2 provenance also satisfies OSPS-BR-03.01"
    """,
    data={
        "primary_control": "SLSA-BUILD-L2",
        "secondary_controls": ["OSPS-BR-03.01"],
        "unified_remediation": "slsa_provenance",
        "report_note": "Implementing SLSA L2 provenance also satisfies OSPS-BR-03.01",
    },
    confidence=0.9,
    suggested_actions=[
        "Configure SLSA GitHub generator",
        "Enable Sigstore signing",
    ],
)
```

#### Example 2: Evidence Interpretation

```python
request = ConsultationRequest(
    request_id="consult-002",
    consultation_type=ConsultationType.EVIDENCE_INTERPRETATION,
    context={
        "control": {
            "id": "OSPS-GV-01.01",
            "title": "Project maintainers are documented",
            "requirement": "The project MUST have a documented list of maintainers",
        },
        "evidence_found": {
            "file": "README.md",
            "section": "## Team",
            "content": """
            ## Team

            This project is maintained by the Platform team at Acme Corp.
            For questions, reach out to platform@acme.com.
            """,
        },
    },
    question="Does this README section satisfy the maintainer documentation requirement? It mentions a team but doesn't list individual maintainers.",
    plugin="darnit-osps",
    standard="osps",
    controls=["OSPS-GV-01.01"],
)

response = ConsultationResponse(
    request_id="consult-002",
    decision="partial_pass",
    reasoning="""
    The documentation provides:
    ✓ Clear ownership (Platform team at Acme Corp)
    ✓ Contact method (platform@acme.com)

    Missing:
    ✗ Individual maintainer names
    ✗ Roles/responsibilities

    For an internal corporate project, team-level attribution may be acceptable.
    For an open source project, individual maintainers should be listed.
    """,
    data={
        "status": "WARN",
        "message": "Maintainership documented at team level; consider adding individual maintainers",
        "recommendation": "Add MAINTAINERS.md with individual contributors and their roles",
    },
    confidence=0.75,
    caveats=[
        "Interpretation may vary based on project visibility (internal vs OSS)",
        "Some compliance frameworks require named individuals",
    ],
)
```

### 4.5 Consultation Protocol Implementation

```python
# darnit/core/decision_engine.py

from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass
import hashlib
import json
import logging

from .consultation import ConsultationRequest, ConsultationResponse, ConsultationType

logger = logging.getLogger(__name__)


@dataclass
class DecisionCache:
    """Cache for consultation decisions."""
    response: ConsultationResponse
    timestamp: float
    ttl: int


class DecisionEngine:
    """
    Manages consultation with the AI for ambiguous decisions.

    The engine can operate in multiple modes:
    - Interactive: Sends requests to AI and waits for response
    - Cached: Uses cached decisions for known patterns
    - Offline: Falls back to deterministic rules when AI unavailable
    """

    def __init__(
        self,
        consultation_callback: Optional[Callable[[ConsultationRequest], ConsultationResponse]] = None,
        enable_cache: bool = True,
        offline_mode: bool = False,
    ):
        self.consultation_callback = consultation_callback
        self.enable_cache = enable_cache
        self.offline_mode = offline_mode
        self._cache: Dict[str, DecisionCache] = {}
        self._offline_rules: Dict[ConsultationType, Callable] = {}

    def consult(self, request: ConsultationRequest) -> ConsultationResponse:
        """
        Request a consultation decision.

        Priority:
        1. Check cache for identical/similar request
        2. If online, consult AI
        3. Fall back to offline rules
        """
        # Check cache
        if self.enable_cache and request.cache_key:
            cached = self._get_cached(request.cache_key)
            if cached:
                logger.debug(f"Using cached decision for {request.cache_key}")
                return cached

        # Consult AI if available
        if not self.offline_mode and self.consultation_callback:
            try:
                response = self.consultation_callback(request)
                if self.enable_cache and request.cache_key:
                    self._cache_response(request.cache_key, response, request.cache_ttl)
                return response
            except Exception as e:
                logger.warning(f"AI consultation failed: {e}, falling back to offline rules")

        # Offline fallback
        return self._apply_offline_rules(request)

    def register_offline_rule(
        self,
        consultation_type: ConsultationType,
        rule: Callable[[ConsultationRequest], ConsultationResponse],
    ):
        """Register a deterministic fallback rule for a consultation type."""
        self._offline_rules[consultation_type] = rule

    def _get_cached(self, cache_key: str) -> Optional[ConsultationResponse]:
        """Get cached decision if still valid."""
        import time

        cached = self._cache.get(cache_key)
        if cached and (time.time() - cached.timestamp) < cached.ttl:
            return cached.response
        return None

    def _cache_response(self, cache_key: str, response: ConsultationResponse, ttl: int):
        """Cache a consultation response."""
        import time

        self._cache[cache_key] = DecisionCache(
            response=response,
            timestamp=time.time(),
            ttl=ttl,
        )

    def _apply_offline_rules(self, request: ConsultationRequest) -> ConsultationResponse:
        """Apply deterministic rules when AI is unavailable."""
        rule = self._offline_rules.get(request.consultation_type)

        if rule:
            return rule(request)

        # Default: conservative approach
        return ConsultationResponse(
            request_id=request.request_id,
            decision="default",
            reasoning="AI consultation unavailable; using conservative default",
            data={"fallback": True},
            confidence=0.5,
            caveats=["This is a fallback decision without AI guidance"],
        )


# Default offline rules
def default_overlap_rule(request: ConsultationRequest) -> ConsultationResponse:
    """Default rule for control overlap: report all."""
    return ConsultationResponse(
        request_id=request.request_id,
        decision="report_both",
        reasoning="Offline mode: reporting all overlapping controls for completeness",
        data={
            "action": "report_all",
            "controls": request.controls,
        },
        confidence=0.6,
    )


def default_evidence_rule(request: ConsultationRequest) -> ConsultationResponse:
    """Default rule for evidence interpretation: be strict."""
    return ConsultationResponse(
        request_id=request.request_id,
        decision="strict",
        reasoning="Offline mode: applying strict interpretation of evidence requirements",
        data={
            "status": "WARN",
            "message": "Evidence found but requires human review",
        },
        confidence=0.5,
        caveats=["Manual review recommended"],
    )
```

### 4.6 MCP Integration for Consultation

```python
# darnit/server/tools.py

from mcp.server.fastmcp import FastMCP
from ..core.decision_engine import DecisionEngine
from ..core.consultation import ConsultationRequest, ConsultationResponse


def create_consultation_tools(mcp: FastMCP, engine: DecisionEngine):
    """Create MCP tools for the consultation protocol."""

    @mcp.tool()
    def darnit_consult(
        consultation_type: str,
        question: str,
        context: dict,
        options: list = None,
    ) -> str:
        """
        Request AI guidance for an ambiguous security decision.

        This tool allows Darnit plugins to consult with you (the AI) when
        they encounter situations that require judgment:

        - Control overlap between standards
        - Ambiguous evidence interpretation
        - Remediation conflicts
        - Priority decisions

        Args:
            consultation_type: Type of consultation (control_overlap, evidence_interpretation, etc.)
            question: The specific question needing guidance
            context: Relevant context for the decision
            options: Possible options to choose from (if applicable)

        Returns:
            Your recommendation with reasoning
        """
        # This tool is special - it's a "reverse tool" that asks the AI
        # The response from this tool should be the AI's guidance

        request = ConsultationRequest(
            request_id=f"consult-{hash(question) % 10000}",
            consultation_type=ConsultationType(consultation_type),
            question=question,
            context=context,
            options=options or [],
            plugin="interactive",
        )

        # Format the request for AI consideration
        prompt = f"""
## Darnit Security Framework - Consultation Request

**Type:** {consultation_type}

**Question:** {question}

**Context:**
```json
{json.dumps(context, indent=2)}
```

**Options:**
{_format_options(options) if options else "No predefined options - open recommendation requested."}

Please provide:
1. Your recommended decision
2. Reasoning for the decision
3. Any caveats or considerations
4. Suggested follow-up actions
"""
        return prompt

    @mcp.tool()
    def darnit_respond_to_consultation(
        request_id: str,
        decision: str,
        reasoning: str,
        data: dict = None,
        confidence: float = 0.8,
        caveats: list = None,
        suggested_actions: list = None,
    ) -> str:
        """
        Provide a response to a Darnit consultation request.

        Use this after reviewing a consultation request to provide your guidance.

        Args:
            request_id: The consultation request ID
            decision: Your recommended decision
            reasoning: Explanation for the decision
            data: Structured response data (optional)
            confidence: Confidence level 0.0-1.0
            caveats: Any caveats or limitations
            suggested_actions: Recommended follow-up actions

        Returns:
            Confirmation that the response was recorded
        """
        response = ConsultationResponse(
            request_id=request_id,
            decision=decision,
            reasoning=reasoning,
            data=data or {},
            confidence=confidence,
            caveats=caveats or [],
            suggested_actions=suggested_actions or [],
        )

        # Store response for the waiting plugin
        engine.record_response(response)

        return f"Consultation response recorded for {request_id}"


def _format_options(options: list) -> str:
    """Format options for display."""
    if not options:
        return ""

    lines = []
    for i, opt in enumerate(options, 1):
        lines.append(f"\n**Option {i}: {opt.get('id', f'option_{i}')}**")
        lines.append(f"- Description: {opt.get('description', 'N/A')}")
        if opt.get('pros'):
            lines.append(f"- Pros: {', '.join(opt['pros'])}")
        if opt.get('cons'):
            lines.append(f"- Cons: {', '.join(opt['cons'])}")

    return "\n".join(lines)
```

---

## 5. Plugin System

### 5.1 Plugin Types

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Plugin Ecosystem                                  │
│                                                                              │
│  ┌─────────────────────────┐  ┌─────────────────────────┐                   │
│  │   Open Source Plugins   │  │   Proprietary Plugins   │                   │
│  │                         │  │                         │                   │
│  │  • darnit-osps          │  │  • acme-compliance      │                   │
│  │  • darnit-slsa          │  │  • bigcorp-security     │                   │
│  │  • darnit-scorecard     │  │  • industry-standards   │                   │
│  │  • darnit-cis           │  │  • internal-policies    │                   │
│  │                         │  │                         │                   │
│  │  Distribution:          │  │  Distribution:          │                   │
│  │  • PyPI                 │  │  • Private PyPI         │                   │
│  │  • GitHub               │  │  • Internal registry    │                   │
│  │  • Homebrew             │  │  • License server       │                   │
│  └─────────────────────────┘  └─────────────────────────┘                   │
│                                                                              │
│  ┌─────────────────────────┐  ┌─────────────────────────┐                   │
│  │   Community Plugins     │  │   Enterprise Plugins    │                   │
│  │                         │  │                         │                   │
│  │  • User contributions   │  │  • SOC2 mapping         │                   │
│  │  • Framework adapters   │  │  • PCI-DSS checks       │                   │
│  │  • Tool integrations    │  │  • HIPAA compliance     │                   │
│  │  • Custom standards     │  │  • FedRAMP controls     │                   │
│  └─────────────────────────┘  └─────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Plugin Interface

```python
# darnit/core/plugin.py

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Type, Optional, Any
from enum import Enum


class PluginLicense(Enum):
    """Plugin licensing model."""
    OPEN_SOURCE = "open_source"
    PROPRIETARY = "proprietary"
    FREEMIUM = "freemium"  # Core free, advanced features paid


@dataclass
class PluginMetadata:
    """Plugin identification and requirements."""

    # Identity
    name: str                            # e.g., "darnit-osps"
    version: str                         # Semver, e.g., "1.0.0"
    description: str
    author: str

    # Licensing
    license: PluginLicense = PluginLicense.OPEN_SOURCE
    license_key_required: bool = False

    # Standards implemented
    standards: List[str] = field(default_factory=list)  # e.g., ["osps", "slsa"]

    # Dependencies
    requires_darnit: str = ">=0.1.0"     # Framework version requirement
    requires_plugins: List[str] = field(default_factory=list)
    conflicts_with: List[str] = field(default_factory=list)

    # Capabilities
    provides_checks: bool = True
    provides_remediations: bool = False
    provides_attestations: bool = False
    provides_mcp_tools: bool = False

    # Configuration
    config_schema: Optional[Dict] = None  # JSON Schema for plugin config
    config_section: Optional[str] = None  # Section in project.toml

    # Consultation
    supports_consultation: bool = False   # Can use LLM consultation
    consultation_types: List[str] = field(default_factory=list)


class Plugin(ABC):
    """Base class for Darnit plugins."""

    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata."""
        pass

    @abstractmethod
    def get_standards(self) -> List["Standard"]:
        """Return standard definitions this plugin implements."""
        pass

    @abstractmethod
    def get_check_adapters(self) -> List[Type["CheckAdapter"]]:
        """Return check adapter classes."""
        pass

    def get_remediation_adapters(self) -> List[Type["RemediationAdapter"]]:
        """Return remediation adapter classes (optional)."""
        return []

    def get_mcp_tools(self) -> List[callable]:
        """Return additional MCP tools to register (optional)."""
        return []

    def validate_license(self, license_key: Optional[str] = None) -> bool:
        """Validate plugin license (override for proprietary plugins)."""
        return True

    def on_load(self, context: "PluginContext") -> None:
        """Called when plugin is loaded."""
        pass

    def on_unload(self) -> None:
        """Called when plugin is unloaded."""
        pass


@dataclass
class PluginContext:
    """Context provided to plugins during lifecycle."""
    registry: "PluginRegistry"
    decision_engine: "DecisionEngine"
    config: "DarnitConfig"
    logger: Any
```

### 5.3 Plugin Discovery and Registration

```python
# darnit/core/registry.py

import importlib.metadata
from typing import Dict, List, Optional, Set
import logging

from .plugin import Plugin, PluginMetadata, PluginLicense
from .adapters import CheckAdapter, RemediationAdapter
from ..standards.base import Standard

logger = logging.getLogger(__name__)


class PluginRegistry:
    """
    Central registry for Darnit plugins.

    Supports multiple discovery mechanisms:
    1. Entry points (installed packages)
    2. Direct registration (programmatic)
    3. Plugin directories (file-based)
    """

    # Entry point groups
    ENTRY_POINT_GROUP = "darnit.plugins"
    PROPRIETARY_ENTRY_POINT_GROUP = "darnit.plugins.proprietary"

    def __init__(self, license_validator: Optional[callable] = None):
        self._plugins: Dict[str, Plugin] = {}
        self._standards: Dict[str, Standard] = {}
        self._check_adapters: Dict[str, List[CheckAdapter]] = {}
        self._remediation_adapters: Dict[str, List[RemediationAdapter]] = {}
        self._mcp_tools: List[callable] = []
        self._license_validator = license_validator
        self._loaded_order: List[str] = []

    def discover_plugins(self) -> Dict[str, PluginMetadata]:
        """
        Discover all available plugins.

        Returns dict of plugin_name -> metadata (not loaded yet)
        """
        discovered = {}

        # Check both entry point groups
        for group in [self.ENTRY_POINT_GROUP, self.PROPRIETARY_ENTRY_POINT_GROUP]:
            try:
                eps = importlib.metadata.entry_points(group=group)
                for ep in eps:
                    try:
                        plugin_class = ep.load()
                        plugin = plugin_class()
                        meta = plugin.metadata()
                        discovered[ep.name] = meta
                        logger.debug(f"Discovered plugin: {ep.name} ({meta.license.value})")
                    except Exception as e:
                        logger.warning(f"Failed to load plugin {ep.name}: {e}")
            except Exception as e:
                logger.debug(f"No plugins in group {group}: {e}")

        return discovered

    def load_plugin(
        self,
        name: str,
        license_key: Optional[str] = None,
    ) -> bool:
        """
        Load a plugin by name.

        Args:
            name: Plugin name (entry point name)
            license_key: License key for proprietary plugins

        Returns:
            True if loaded successfully
        """
        if name in self._plugins:
            logger.info(f"Plugin {name} already loaded")
            return True

        # Find and load plugin class
        plugin = self._find_plugin(name)
        if not plugin:
            logger.error(f"Plugin not found: {name}")
            return False

        meta = plugin.metadata()

        # Validate license for proprietary plugins
        if meta.license_key_required:
            if not plugin.validate_license(license_key):
                logger.error(f"License validation failed for {name}")
                return False
            if self._license_validator and not self._license_validator(name, license_key):
                logger.error(f"External license validation failed for {name}")
                return False

        # Check dependencies
        for dep in meta.requires_plugins:
            if dep not in self._plugins:
                logger.info(f"Loading dependency {dep} for {name}")
                if not self.load_plugin(dep):
                    logger.error(f"Failed to load dependency {dep} for {name}")
                    return False

        # Check conflicts
        for conflict in meta.conflicts_with:
            if conflict in self._plugins:
                logger.error(f"Plugin {name} conflicts with loaded plugin {conflict}")
                return False

        # Register plugin
        return self._register_plugin(plugin)

    def load_all_discovered(
        self,
        license_keys: Optional[Dict[str, str]] = None,
        skip_proprietary: bool = False,
    ) -> List[str]:
        """
        Load all discovered plugins.

        Args:
            license_keys: Dict of plugin_name -> license_key
            skip_proprietary: Skip plugins requiring license keys

        Returns:
            List of successfully loaded plugin names
        """
        license_keys = license_keys or {}
        loaded = []

        discovered = self.discover_plugins()

        # Sort by dependencies
        sorted_plugins = self._sort_by_dependencies(discovered)

        for name, meta in sorted_plugins:
            if skip_proprietary and meta.license_key_required:
                logger.info(f"Skipping proprietary plugin: {name}")
                continue

            key = license_keys.get(name)
            if self.load_plugin(name, key):
                loaded.append(name)

        return loaded

    def _find_plugin(self, name: str) -> Optional[Plugin]:
        """Find a plugin by name."""
        for group in [self.ENTRY_POINT_GROUP, self.PROPRIETARY_ENTRY_POINT_GROUP]:
            try:
                eps = importlib.metadata.entry_points(group=group)
                for ep in eps:
                    if ep.name == name:
                        plugin_class = ep.load()
                        return plugin_class()
            except Exception:
                continue
        return None

    def _register_plugin(self, plugin: Plugin) -> bool:
        """Register a plugin and its components."""
        meta = plugin.metadata()

        try:
            # Register standards
            for standard in plugin.get_standards():
                if standard.id in self._standards:
                    logger.warning(f"Standard {standard.id} already registered, skipping")
                else:
                    self._standards[standard.id] = standard

            # Register check adapters
            for adapter_class in plugin.get_check_adapters():
                adapter = adapter_class()
                std = adapter.standard()
                if std not in self._check_adapters:
                    self._check_adapters[std] = []
                self._check_adapters[std].append(adapter)

            # Register remediation adapters
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
            self._loaded_order.append(meta.name)

            # Notify plugin
            plugin.on_load(PluginContext(
                registry=self,
                decision_engine=None,  # Set later
                config=None,  # Set later
                logger=logger,
            ))

            logger.info(f"Loaded plugin: {meta.name} v{meta.version}")
            return True

        except Exception as e:
            logger.error(f"Failed to register plugin {meta.name}: {e}")
            return False

    def _sort_by_dependencies(
        self,
        plugins: Dict[str, PluginMetadata],
    ) -> List[tuple]:
        """Topological sort of plugins by dependencies."""
        # Simple implementation - could be more sophisticated
        result = []
        remaining = dict(plugins)

        while remaining:
            # Find plugins with no unmet dependencies
            ready = []
            for name, meta in remaining.items():
                deps_met = all(
                    dep in [p[0] for p in result] or dep not in remaining
                    for dep in meta.requires_plugins
                )
                if deps_met:
                    ready.append(name)

            if not ready:
                # Circular dependency or missing dependency
                logger.warning(f"Could not resolve dependencies for: {list(remaining.keys())}")
                ready = list(remaining.keys())[:1]

            for name in ready:
                result.append((name, remaining.pop(name)))

        return result

    # Query methods
    def get_standard(self, standard_id: str) -> Optional[Standard]:
        return self._standards.get(standard_id)

    def get_standards(self) -> List[Standard]:
        return list(self._standards.values())

    def get_check_adapters(self, standard: str) -> List[CheckAdapter]:
        return self._check_adapters.get(standard, [])

    def get_all_check_adapters(self) -> List[CheckAdapter]:
        return [a for adapters in self._check_adapters.values() for a in adapters]

    def get_plugins(self) -> Dict[str, Plugin]:
        return dict(self._plugins)

    def get_mcp_tools(self) -> List[callable]:
        return list(self._mcp_tools)
```

---

## 6. The project.toml Specification

> **CRITICAL**: This section defines the canonical specification for `project.toml`. All tools, MCPs, and LLMs that interact with this file MUST adhere to this specification.

### 6.1 Purpose and Scope

`project.toml` is a **configuration file**, not a results file. It defines:

| Belongs in project.toml | Does NOT Belong in project.toml |
|-------------------------|----------------------------------|
| Project identity (name, type) | Audit results (pass/fail counts) |
| File locations (where is SECURITY.md?) | Check outcomes (which controls passed) |
| User decisions (control overrides) | Timestamps of audits |
| Target compliance levels | Remediation suggestions |
| CI/CD configuration | Evidence collected during audits |
| Standard-specific settings | Compliance status (true/false) |

### 6.2 The Golden Rule

```
project.toml changes when the USER changes something about their project.
project.toml does NOT change when an audit runs.
```

**Correct behavior:**
- User adds `SECURITY.md` → User (or tool helping user) updates `[security] policy = { path = "SECURITY.md" }`
- User decides a control doesn't apply → User adds `[osps.controls] "OSPS-BR-02.01" = { status = "n/a", reason = "..." }`

**Incorrect behavior:**
- Audit runs → Tool writes `[osps.audit] passed = 10, failed = 19` ❌
- Audit runs → Tool writes `[osps.level1] passed = ["OSPS-AC-02.01", ...]` ❌
- Audit runs → Tool writes `[osps.compliance] level_1 = false` ❌

### 6.3 Where Audit Results Belong

Audit results are **ephemeral** and belong in separate output:

```
project-root/
├── project.toml              # Configuration (user-managed, stable)
│
├── .darnit/                  # Darnit working directory
│   ├── cache/                # Cached data for performance
│   │   └── last-audit.json   # Most recent audit for quick lookup
│   │
│   ├── reports/              # Historical audit reports
│   │   ├── audit-2025-12-01T10-30-00.json
│   │   ├── audit-2025-12-01T10-30-00.sarif
│   │   └── audit-2025-12-01T10-30-00.md
│   │
│   └── attestations/         # Signed compliance proofs
│       └── baseline-2025-12-01.intoto.jsonl
│
└── (or output to stdout/return value for MCP tools)
```

### 6.4 LLM/AI Guidelines

**When an AI agent uses Darnit tools, it MUST:**

1. **Never write audit results to project.toml**
   - Results go to `.darnit/reports/`, stdout, or are returned from MCP tools
   - The AI should present results to the user, not persist them to config

2. **Only modify project.toml for configuration changes**
   - Adding file location references (user added a SECURITY.md)
   - Adding control overrides (user says a control doesn't apply)
   - Changing target levels (user wants to aim for Level 2)

3. **Ask before modifying project.toml**
   - "I found SECURITY.md at `./SECURITY.md`. Should I add this to your project.toml?"
   - "This control doesn't apply to specification projects. Should I mark it as N/A?"

4. **Understand the file is user-owned**
   - Users may hand-edit project.toml
   - Users may have comments explaining their decisions
   - Tools should preserve formatting and comments when possible

### 6.5 Example: Correct vs Incorrect

**INCORRECT project.toml (mixing config and results):**
```toml
[project]
name = "my-project"

[osps]
target_level = 1

# ❌ WRONG - These are audit results, not configuration
[osps.compliance]
level_1 = false
level_2 = false

[osps.audit]
total_checks = 62
passed = 10
failed = 19

[osps.level1]
passed = ["OSPS-AC-02.01", "OSPS-BR-03.01"]
failed = ["OSPS-AC-03.02", "OSPS-VM-02.01"]
```

**CORRECT project.toml (configuration only):**
```toml
[project]
name = "my-project"
type = "software"

# Documentation locations (evidence references)
[security]
policy = { path = "SECURITY.md" }

[governance]
contributing = { path = "CONTRIBUTING.md" }

[legal]
license = { path = "LICENSE" }

# Standard configuration
[osps]
target_level = 2

# User-specified overrides only
[osps.controls]
"OSPS-BR-02.01" = { status = "n/a", reason = "No distributable releases" }
```

**CORRECT audit output (separate file or MCP response):**
```json
{
  "audit_id": "audit-2025-12-01T10-30-00",
  "repository": "myorg/my-project",
  "timestamp": "2025-12-01T10:30:00Z",
  "standards": {
    "osps": {
      "target_level": 2,
      "compliance": { "level_1": true, "level_2": false },
      "results": [
        { "id": "OSPS-AC-02.01", "status": "PASS", "message": "..." },
        { "id": "OSPS-VM-02.01", "status": "FAIL", "message": "..." }
      ]
    }
  }
}
```

### 6.6 Schema Versioning

The `schema_version` field allows for future evolution:

```toml
schema_version = "1.0"  # Current version
```

Tools MUST check this version and handle unknown versions gracefully.

---

## 7. Configuration Model

### 7.1 project.toml Schema

```toml
# project.toml - Darnit Security Configuration
#
# IMPORTANT: This file contains CONFIGURATION only.
# Audit results belong in .darnit/reports/ or tool output.
#
# This file is the canonical source of truth for:
# - Project metadata
# - Security documentation locations
# - Compliance standard configuration
# - CI/CD integration settings
#
# Future: This may move to .project/ directory with multiple files

schema_version = "1.0"

# =============================================================================
# PROJECT METADATA
# =============================================================================

[project]
name = "my-awesome-project"
type = "software"  # software | specification | documentation | infrastructure | data
description = "An awesome project that does awesome things"
repository = "https://github.com/myorg/my-awesome-project"

# =============================================================================
# DARNIT CONFIGURATION
# =============================================================================

[darnit]
# Which standards/plugins to enable
enabled = ["osps", "slsa"]

# Plugin-specific license keys (for proprietary plugins)
[darnit.licenses]
# acme-compliance = "LICENSE-KEY-HERE"

# Global settings
[darnit.settings]
fail_on_warn = false          # Treat warnings as failures
parallel_checks = true        # Run checks in parallel
max_workers = 4               # Parallel worker count
cache_decisions = true        # Cache LLM consultation decisions
consultation_mode = "auto"    # auto | always | never | offline

# =============================================================================
# STANDARD-SPECIFIC CONFIGURATION
# =============================================================================

# --- OpenSSF Baseline (OSPS) ---
[osps]
target_level = 3

[osps.controls]
# Override specific controls
"OSPS-BR-02.01" = { status = "n/a", reason = "Internal tool with no distributable artifacts" }
"OSPS-VM-05.01" = { status = "n/a", reason = "No external dependencies" }

# --- SLSA ---
[slsa]
target_level = 2

[slsa.build]
builder = "github-actions"
workflow = ".github/workflows/release.yml"
provenance_generator = "slsa-github-generator"

[slsa.source]
version_control = "git"
verified_history = true
two_person_review = true

[[slsa.artifacts]]
name = "my-project"
type = "container"
registry = "ghcr.io/myorg/my-project"

[[slsa.artifacts]]
name = "my-project-cli"
type = "binary"
path = "dist/"

# --- Custom/Proprietary Standards ---
[custom.acme-security]
enabled = true
target_level = 2
config_url = "https://internal.acme.com/security-policy.json"

# =============================================================================
# SHARED DOCUMENTATION REFERENCES
# =============================================================================
# These sections are read by multiple standards

[security]
policy = { path = "SECURITY.md" }
threat_model = { path = "docs/THREAT_MODEL.md" }
advisories = { url = "https://github.com/myorg/my-project/security/advisories" }

# Section references - point to headings within other files
vex_policy = { section = "security.policy#vulnerability-exceptions" }
sca_policy = { section = "security.policy#dependency-vulnerabilities" }
sast_policy = { section = "security.policy#static-analysis" }

[governance]
maintainers = { path = "MAINTAINERS.md" }
contributing = { path = "CONTRIBUTING.md" }
code_of_conduct = { path = "CODE_OF_CONDUCT.md" }
codeowners = { path = ".github/CODEOWNERS" }
governance_doc = { path = "GOVERNANCE.md" }

[legal]
license = { path = "LICENSE" }
contributor_agreement = { type = "dco" }  # dco | cla | none

[artifacts]
sbom = { path = "sbom.json", format = "cyclonedx" }
signing = { enabled = true, method = "sigstore" }
provenance = { enabled = true, format = "slsa" }

[quality]
changelog = { path = "CHANGELOG.md" }

[documentation]
readme = { path = "README.md" }
support = { path = "SUPPORT.md" }
architecture = { path = "docs/ARCHITECTURE.md" }

[dependencies]
lockfile = { path = "uv.lock" }
manifest = { path = "pyproject.toml" }

# =============================================================================
# CI/CD CONFIGURATION
# =============================================================================

[ci]
provider = "github"

[ci.github]
workflows = [".github/workflows/ci.yml", ".github/workflows/release.yml"]
security_scanning = [".github/workflows/codeql.yml"]
dependency_management = ".github/dependabot.yml"

[ci.github.branch_protection]
branch = "main"
required_approvals = 1
required_checks = ["test", "lint"]
enforce_admins = true
```

### 7.2 Future: .project Directory

```
.project/
├── config.toml          # Core project config (what's in project.toml today)
├── security.toml        # Security-specific configuration
├── compliance/
│   ├── osps.toml        # OSPS-specific overrides and evidence
│   ├── slsa.toml        # SLSA configuration
│   └── custom.toml      # Custom standard definitions
├── evidence/
│   ├── attestations/    # Generated attestations
│   └── reports/         # Audit reports
└── cache/
    └── decisions.json   # Cached LLM consultation decisions
```

---

## 8. Package Structure

```
darnit/
├── pyproject.toml
├── README.md
├── LICENSE
│
├── src/
│   └── darnit/
│       ├── __init__.py              # Public API exports
│       ├── __main__.py              # CLI entry point
│       │
│       ├── core/
│       │   ├── __init__.py
│       │   ├── models.py            # CheckResult, AuditResult, etc.
│       │   ├── adapters.py          # CheckAdapter, RemediationAdapter ABCs
│       │   ├── plugin.py            # Plugin, PluginMetadata
│       │   ├── registry.py          # PluginRegistry
│       │   ├── orchestrator.py      # CheckOrchestrator
│       │   ├── consultation.py      # Consultation protocol
│       │   ├── decision_engine.py   # LLM consultation engine
│       │   └── exceptions.py        # DarnitError, etc.
│       │
│       ├── config/
│       │   ├── __init__.py
│       │   ├── models.py            # ProjectConfig, StandardConfig
│       │   ├── loader.py            # TOML parsing
│       │   ├── schema.py            # Validation
│       │   └── discovery.py         # Auto-discovery utilities
│       │
│       ├── standards/
│       │   ├── __init__.py
│       │   ├── base.py              # Standard, ControlDefinition
│       │   └── registry.py          # Standard registration
│       │
│       ├── formatters/
│       │   ├── __init__.py
│       │   ├── sarif.py             # SARIF 2.1.0 output
│       │   ├── markdown.py          # Markdown reports
│       │   └── json.py              # JSON output
│       │
│       ├── attestation/
│       │   ├── __init__.py
│       │   ├── intoto.py            # In-toto statements
│       │   └── signing.py           # Sigstore integration
│       │
│       └── server/
│           ├── __init__.py
│           ├── factory.py           # MCP server factory
│           └── tools.py             # Core MCP tools
│
├── plugins/                         # Built-in plugins (or separate packages)
│   ├── darnit-osps/
│   │   ├── pyproject.toml
│   │   └── src/darnit_osps/
│   │       ├── __init__.py
│   │       ├── plugin.py            # OSPSPlugin class
│   │       ├── standard.py          # OSPS standard definition
│   │       ├── adapters/
│   │       │   ├── access_control.py
│   │       │   ├── build_release.py
│   │       │   └── ...
│   │       └── remediations/
│   │           └── ...
│   │
│   └── darnit-slsa/
│       ├── pyproject.toml
│       └── src/darnit_slsa/
│           ├── __init__.py
│           ├── plugin.py
│           ├── standard.py
│           └── adapters/
│
├── tests/
│   ├── core/
│   ├── config/
│   ├── plugins/
│   └── integration/
│
└── docs/
    ├── getting-started.md
    ├── configuration.md
    ├── plugin-development.md
    └── api/
```

---

## 9. MCP Tools

### 9.1 Core Tools

```python
# darnit/server/tools.py

"""
Darnit MCP Tools
================

Core tools provided by the Darnit framework.
Plugins can register additional tools.
"""


@mcp.tool()
def darnit_audit(
    local_path: str = ".",
    standards: list[str] | None = None,
    levels: dict | None = None,
    output_format: str = "markdown",
    include_passing: bool = False,
) -> str:
    """
    Run security audit against configured standards.

    Checks the project against enabled security standards (OSPS, SLSA, etc.)
    and returns a comprehensive report.

    Args:
        local_path: Path to repository (default: current directory)
        standards: Standards to check (default: all enabled in project.toml)
        levels: Override target levels, e.g., {"osps": 2, "slsa": 1}
        output_format: Output format (markdown, json, sarif)
        include_passing: Include passing checks in output

    Returns:
        Formatted audit report
    """


@mcp.tool()
def darnit_list_standards() -> str:
    """
    List all available security standards.

    Shows installed plugins and their supported standards,
    including version and control counts.
    """


@mcp.tool()
def darnit_list_controls(
    standard: str | None = None,
    level: int | None = None,
    domain: str | None = None,
) -> str:
    """
    List available controls/requirements.

    Args:
        standard: Filter by standard ID (e.g., "osps", "slsa")
        level: Filter by maturity level (1-4)
        domain: Filter by domain (e.g., "AC", "BUILD")
    """


@mcp.tool()
def darnit_check(
    control_id: str,
    local_path: str = ".",
) -> str:
    """
    Run a single control check.

    Useful for testing or debugging specific controls.

    Args:
        control_id: Control ID to check (e.g., "OSPS-AC-01.01", "SLSA-BUILD-L2")
        local_path: Path to repository
    """


@mcp.tool()
def darnit_remediate(
    control_id: str | None = None,
    category: str | None = None,
    local_path: str = ".",
    dry_run: bool = True,
) -> str:
    """
    Apply remediation for failed controls.

    Args:
        control_id: Specific control to remediate
        category: Remediation category (e.g., "security_policy", "branch_protection")
        local_path: Path to repository
        dry_run: Preview changes without applying (default: True)
    """


@mcp.tool()
def darnit_init(
    local_path: str = ".",
    standards: list[str] | None = None,
    interactive: bool = True,
) -> str:
    """
    Initialize Darnit configuration for a project.

    Creates project.toml with discovered settings and
    optionally guides through configuration.

    Args:
        local_path: Path to repository
        standards: Standards to enable (default: auto-detect)
        interactive: Enable interactive configuration
    """


@mcp.tool()
def darnit_attest(
    local_path: str = ".",
    standards: list[str] | None = None,
    sign: bool = True,
    output_path: str | None = None,
) -> str:
    """
    Generate compliance attestation.

    Creates an in-toto attestation documenting the project's
    compliance status, optionally signed with Sigstore.

    Args:
        local_path: Path to repository
        standards: Standards to include in attestation
        sign: Sign with Sigstore (default: True)
        output_path: Where to save attestation
    """


@mcp.tool()
def darnit_consult(
    consultation_type: str,
    question: str,
    context: dict,
    options: list | None = None,
) -> str:
    """
    Request AI guidance for an ambiguous security decision.

    This tool allows Darnit to consult with you when it encounters
    situations requiring judgment (overlapping controls, ambiguous
    evidence, priority decisions, etc.)

    Args:
        consultation_type: Type of consultation
        question: The specific question
        context: Relevant context
        options: Possible options to choose from
    """


@mcp.tool()
def darnit_plugins() -> str:
    """
    List installed and available Darnit plugins.

    Shows loaded plugins, their status, and standards they provide.
    """
```

---

## 10. Implementation Roadmap

### Phase 1: Core Framework (2-3 weeks)

**Goal**: Extract reusable framework from current baseline-mcp

| Task | Description | Status |
|------|-------------|--------|
| Core models | CheckResult, AuditResult, etc. | Exists (migrate) |
| Adapter ABCs | CheckAdapter, RemediationAdapter | Exists (migrate) |
| Plugin interface | Plugin, PluginMetadata | New |
| Plugin registry | Discovery, loading, validation | New |
| Config loader | project.toml parsing | Exists (enhance) |
| Check orchestrator | Multi-standard execution | New |

### Phase 2: OSPS Plugin (1 week)

**Goal**: Refactor current OSPS checks into plugin format

| Task | Description | Status |
|------|-------------|--------|
| OSPS standard definition | Control definitions | New |
| Check adapters | Migrate check functions | Exists (refactor) |
| Remediation adapters | Migrate remediation | Exists (refactor) |
| Plugin registration | Entry point setup | New |

### Phase 3: Consultation System (1-2 weeks)

**Goal**: Implement LLM consultation protocol

| Task | Description | Status |
|------|-------------|--------|
| Consultation models | Request/Response types | New |
| Decision engine | Caching, offline fallback | New |
| MCP tools | darnit_consult | New |
| Offline rules | Default decision rules | New |

### Phase 4: SLSA Plugin (2 weeks)

**Goal**: First new standard implementation

| Task | Description | Status |
|------|-------------|--------|
| SLSA standard definition | L1-L4 controls | New |
| Build verification | Provenance checking | New |
| Source verification | History, review checks | New |
| Integration tests | End-to-end testing | New |

### Phase 5: Integration & Polish (1 week)

**Goal**: Unified experience

| Task | Description | Status |
|------|-------------|--------|
| Unified MCP tools | darnit_audit, etc. | New |
| Cross-standard reporting | Aggregated SARIF | New |
| Documentation | User and plugin dev docs | New |
| CLI | Command-line interface | New |

### Phase 6: Ecosystem (Ongoing)

| Task | Description |
|------|-------------|
| Scorecard plugin | OpenSSF Scorecard integration |
| CIS plugin | CIS Benchmarks |
| Custom plugin template | Starter for proprietary plugins |
| VS Code extension | IDE integration |

---

## 11. Open Questions

### Resolved

| Question | Decision |
|----------|----------|
| Framework name | **Darnit** |
| Config file | **project.toml** (future: .project/) |
| Plugin distribution | Mixed - OSS on PyPI, proprietary private |
| Cross-standard overlap | LLM consultation for intelligent handling |

### Open

| Question | Options | Considerations |
|----------|---------|----------------|
| CLI interface | Click vs Typer vs argparse | Typer for modern UX |
| Async support | Full async vs sync-first | Start sync, add async later |
| Plugin sandboxing | Trust all vs sandbox proprietary | Security vs complexity |
| Consultation caching | Local vs shared cache | Privacy considerations |
| Standard version handling | Multiple versions vs latest | Migration complexity |

---

## 12. Appendix: Consultation Type Reference

| Type | When Used | Example |
|------|-----------|---------|
| `control_overlap` | Multiple standards check same thing | OSPS-BR-03 vs SLSA-BUILD-L2 |
| `remediation_conflict` | Different fixes for same issue | Add file vs configure API |
| `ambiguous_requirement` | Unclear control interpretation | "Documented maintainers" - team vs individual? |
| `priority_decision` | Which issues to address first | Security vs quality fixes |
| `custom_check` | Non-standard verification needed | Internal policy compliance |
| `evidence_interpretation` | Uncertain if evidence is sufficient | Partial documentation |

---

*Last updated: 2025-12-04*
