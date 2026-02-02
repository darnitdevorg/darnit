"""STRIDE threat analysis engine.

This module implements the STRIDE methodology for threat analysis:
- Spoofing
- Tampering
- Repudiation
- Information Disclosure
- Denial of Service
- Elevation of Privilege
"""

from typing import Any

from darnit.core.logging import get_logger

from .models import (
    AssetInventory,
    CodeLocation,
    RiskLevel,
    RiskScore,
    StrideCategory,
    Threat,
)

logger = get_logger("threat_model.stride")


def calculate_risk_score(
    exposure: str,
    data_sensitivity: str,
    has_auth: bool,
    has_input_validation: bool,
    existing_controls: list[str]
) -> RiskScore:
    """Calculate risk score based on multiple factors.

    Args:
        exposure: Exposure level (public, authenticated, internal, localhost)
        data_sensitivity: Data sensitivity (financial, pii, health, authentication, business, public)
        has_auth: Whether authentication is required
        has_input_validation: Whether input validation is present
        existing_controls: List of existing security controls

    Returns:
        Calculated RiskScore
    """
    # Likelihood factors
    exposure_weights = {
        "public": 1.0,
        "authenticated": 0.7,
        "internal": 0.4,
        "localhost": 0.1
    }

    sensitivity_weights = {
        "financial": 1.0,
        "pii": 0.9,
        "health": 0.95,
        "authentication": 0.85,
        "business": 0.6,
        "public": 0.2
    }

    exposure_score = exposure_weights.get(exposure, 0.7)
    sensitivity_score = sensitivity_weights.get(data_sensitivity, 0.5)

    # Base likelihood
    likelihood = exposure_score * 0.5 + sensitivity_score * 0.5

    # Impact based on data sensitivity
    impact = sensitivity_score

    # Control effectiveness
    control_effectiveness = 0.0
    if has_auth:
        control_effectiveness += 0.3
    if has_input_validation:
        control_effectiveness += 0.3
    for control in existing_controls:
        control_lower = control.lower()
        if "encryption" in control_lower:
            control_effectiveness += 0.2
        if "rate limit" in control_lower:
            control_effectiveness += 0.1
        if "waf" in control_lower:
            control_effectiveness += 0.1
        if "logging" in control_lower:
            control_effectiveness += 0.05

    control_effectiveness = min(control_effectiveness, 0.9)  # Cap at 90%

    # Overall risk
    overall = likelihood * impact * (1 - control_effectiveness)

    # Determine level
    if overall >= 0.8:
        level = RiskLevel.CRITICAL
    elif overall >= 0.6:
        level = RiskLevel.HIGH
    elif overall >= 0.4:
        level = RiskLevel.MEDIUM
    elif overall >= 0.2:
        level = RiskLevel.LOW
    else:
        level = RiskLevel.INFORMATIONAL

    return RiskScore(
        overall=round(overall, 2),
        level=level,
        likelihood=round(likelihood, 2),
        impact=round(impact, 2),
        control_effectiveness=round(control_effectiveness, 2),
        factors={
            "exposure": exposure,
            "data_sensitivity": data_sensitivity,
            "has_auth": has_auth,
            "has_input_validation": has_input_validation
        }
    )


def analyze_stride_threats(
    assets: AssetInventory,
    injection_sinks: list[dict[str, Any]]
) -> list[Threat]:
    """Analyze assets using STRIDE methodology.

    Args:
        assets: Discovered asset inventory
        injection_sinks: List of potential injection vulnerabilities

    Returns:
        List of identified threats
    """
    threats = []
    threat_id = 0

    # Analyze each entry point
    for ep in assets.entry_points:
        # Spoofing threats for unauthenticated endpoints
        if not ep.authentication_required:
            threat_id += 1
            risk = calculate_risk_score(
                exposure="public" if ep.entry_type == "api_route" else "authenticated",
                data_sensitivity="business",
                has_auth=False,
                has_input_validation=False,
                existing_controls=[]
            )
            threats.append(Threat(
                id=f"TM-S-{threat_id:03d}",
                category=StrideCategory.SPOOFING,
                title=f"Missing Authentication on {ep.path}",
                description=f"The {ep.entry_type} endpoint {ep.path} does not appear to require authentication, allowing unauthorized access.",
                affected_assets=[ep.id],
                attack_vector="Direct API access without credentials",
                prerequisites=["Network access to the endpoint"],
                risk=risk,
                existing_controls=[],
                recommended_controls=[
                    "Implement authentication middleware",
                    "Use session-based or token-based authentication",
                    "Apply authentication at the route level"
                ],
                code_locations=[CodeLocation(
                    file=ep.file,
                    line_start=ep.line,
                    line_end=ep.line,
                    annotation="Entry point without authentication check"
                )],
                references=["OWASP API Security Top 10 - API2:2023 Broken Authentication"]
            ))

        # Elevation of Privilege for server actions
        if ep.entry_type == "server_action":
            threat_id += 1
            risk = calculate_risk_score(
                exposure="authenticated",
                data_sensitivity="business",
                has_auth=ep.authentication_required,
                has_input_validation=False,
                existing_controls=[]
            )
            threats.append(Threat(
                id=f"TM-E-{threat_id:03d}",
                category=StrideCategory.ELEVATION_OF_PRIVILEGE,
                title=f"Server Action Authorization Check: {ep.path}",
                description=f"Server action '{ep.path}' executes server-side code. Verify authorization is checked for sensitive operations.",
                affected_assets=[ep.id],
                attack_vector="Invoke server action without proper authorization",
                prerequisites=["Valid session (if authenticated)", "Knowledge of server action name"],
                risk=risk,
                existing_controls=["Authentication" if ep.authentication_required else "None"],
                recommended_controls=[
                    "Implement explicit authorization checks",
                    "Validate user permissions before sensitive operations",
                    "Log server action invocations"
                ],
                code_locations=[CodeLocation(
                    file=ep.file,
                    line_start=ep.line,
                    line_end=ep.line,
                    annotation="Server action - verify authorization"
                )],
                references=["OWASP API Security Top 10 - API1:2023 Broken Object Level Authorization"]
            ))

    # Analyze injection sinks
    for sink in injection_sinks:
        threat_id += 1
        category = StrideCategory.TAMPERING
        if sink["type"] == "xss":
            category = StrideCategory.INFORMATION_DISCLOSURE
        elif sink["type"] in ["sql_injection", "command_injection", "code_injection"]:
            category = StrideCategory.ELEVATION_OF_PRIVILEGE

        risk = calculate_risk_score(
            exposure="public",
            data_sensitivity="business",
            has_auth=False,
            has_input_validation=False,
            existing_controls=[]
        )
        # Override for critical injection types
        if sink["severity"] == "critical":
            risk.overall = max(risk.overall, 0.8)
            risk.level = RiskLevel.CRITICAL

        threats.append(Threat(
            id=f"TM-T-{threat_id:03d}",
            category=category,
            title=f"Potential {sink['type'].replace('_', ' ').title()} Vulnerability",
            description=f"Code pattern suggests potential {sink['type'].replace('_', ' ')} vulnerability. {sink['recommendation']}",
            affected_assets=[],
            attack_vector="Inject malicious input through user-controlled data",
            prerequisites=["User input reaches vulnerable sink"],
            risk=risk,
            existing_controls=[],
            recommended_controls=[sink["recommendation"]],
            code_locations=[CodeLocation(
                file=sink["file"],
                line_start=sink["line"],
                line_end=sink["line"],
                snippet=sink["snippet"],
                annotation=f"{sink['cwe']}"
            )],
            references=[f"CWE: {sink['cwe']}", "OWASP Injection Prevention Cheat Sheet"]
        ))

    # Analyze secrets
    for secret in assets.secrets:
        threat_id += 1
        risk = calculate_risk_score(
            exposure="public",
            data_sensitivity="authentication",
            has_auth=False,
            has_input_validation=False,
            existing_controls=[]
        )
        risk.overall = 0.9  # Hardcoded secrets are always critical
        risk.level = RiskLevel.CRITICAL

        threats.append(Threat(
            id=f"TM-I-{threat_id:03d}",
            category=StrideCategory.INFORMATION_DISCLOSURE,
            title=f"Hardcoded Secret: {secret.secret_type}",
            description=f"A {secret.secret_type} appears to be hardcoded in the source code. This could lead to credential exposure.",
            affected_assets=[secret.id],
            attack_vector="Source code access (repository, deployment, logs)",
            prerequisites=["Access to source code or compiled artifacts"],
            risk=risk,
            existing_controls=[],
            recommended_controls=[
                "Move secrets to environment variables",
                "Use a secrets management service (Vault, AWS Secrets Manager)",
                "Rotate compromised credentials immediately"
            ],
            code_locations=[CodeLocation(
                file=secret.file,
                line_start=secret.line,
                line_end=secret.line,
                annotation="Potential hardcoded secret"
            )],
            references=["CWE-798: Use of Hard-coded Credentials", "OWASP Secrets Management Cheat Sheet"]
        ))

    # Analyze sensitive data handling (PII)
    pii_fields = [sd for sd in assets.sensitive_data if sd.data_type == "pii"]
    if pii_fields:
        threat_id += 1
        risk = calculate_risk_score(
            exposure="authenticated",
            data_sensitivity="pii",
            has_auth=True,
            has_input_validation=False,
            existing_controls=[]
        )
        threats.append(Threat(
            id=f"TM-I-{threat_id:03d}",
            category=StrideCategory.INFORMATION_DISCLOSURE,
            title="PII Data Handling Review Required",
            description=f"Found {len(pii_fields)} fields that may contain PII. Review data handling, storage, and transmission practices.",
            affected_assets=[sd.id for sd in pii_fields[:5]],
            attack_vector="Data breach, unauthorized access, logging exposure",
            prerequisites=["Database access or application vulnerability"],
            risk=risk,
            existing_controls=[],
            recommended_controls=[
                "Encrypt PII at rest and in transit",
                "Implement access logging for PII access",
                "Define data retention policies",
                "Ensure GDPR/CCPA compliance"
            ],
            code_locations=[
                CodeLocation(
                    file=sd.file,
                    line_start=sd.line,
                    line_end=sd.line,
                    annotation=f"PII field: {sd.field_name}"
                ) for sd in pii_fields[:3]
            ],
            references=["GDPR Article 32", "OWASP Data Protection Cheat Sheet"]
        ))

    # Analyze financial data
    financial_fields = [sd for sd in assets.sensitive_data if sd.data_type == "financial"]
    if financial_fields:
        threat_id += 1
        risk = calculate_risk_score(
            exposure="authenticated",
            data_sensitivity="financial",
            has_auth=True,
            has_input_validation=False,
            existing_controls=[]
        )
        threats.append(Threat(
            id=f"TM-I-{threat_id:03d}",
            category=StrideCategory.INFORMATION_DISCLOSURE,
            title="Financial Data Handling Review Required",
            description=f"Found {len(financial_fields)} fields that may contain financial data. Ensure PCI-DSS compliance.",
            affected_assets=[sd.id for sd in financial_fields[:5]],
            attack_vector="Data breach, unauthorized access",
            prerequisites=["Database access or application vulnerability"],
            risk=risk,
            existing_controls=[],
            recommended_controls=[
                "Use tokenization for payment card data",
                "Never store CVV/CVC",
                "Implement PCI-DSS controls",
                "Use established payment processors (Stripe, etc.)"
            ],
            code_locations=[
                CodeLocation(
                    file=sd.file,
                    line_start=sd.line,
                    line_end=sd.line,
                    annotation=f"Financial field: {sd.field_name}"
                ) for sd in financial_fields[:3]
            ],
            references=["PCI-DSS Requirements", "OWASP Payment Security Cheat Sheet"]
        ))

    # Denial of Service threats for public endpoints
    public_endpoints = [ep for ep in assets.entry_points if not ep.authentication_required]
    if public_endpoints:
        threat_id += 1
        risk = calculate_risk_score(
            exposure="public",
            data_sensitivity="business",
            has_auth=False,
            has_input_validation=False,
            existing_controls=[]
        )
        threats.append(Threat(
            id=f"TM-D-{threat_id:03d}",
            category=StrideCategory.DENIAL_OF_SERVICE,
            title="Rate Limiting Required for Public Endpoints",
            description=f"Found {len(public_endpoints)} public endpoints that may be vulnerable to abuse without rate limiting.",
            affected_assets=[ep.id for ep in public_endpoints[:5]],
            attack_vector="High-volume requests to exhaust resources",
            prerequisites=["Network access to public endpoints"],
            risk=risk,
            existing_controls=[],
            recommended_controls=[
                "Implement rate limiting per IP/user",
                "Add request throttling",
                "Use CDN/WAF for DDoS protection",
                "Implement request queuing for expensive operations"
            ],
            code_locations=[
                CodeLocation(
                    file=ep.file,
                    line_start=ep.line,
                    line_end=ep.line,
                    annotation=f"Public endpoint: {ep.path}"
                ) for ep in public_endpoints[:3]
            ],
            references=["OWASP API Security Top 10 - API4:2023 Unrestricted Resource Consumption"]
        ))

    # Repudiation - check for logging
    if assets.entry_points:
        threat_id += 1
        risk = calculate_risk_score(
            exposure="authenticated",
            data_sensitivity="business",
            has_auth=True,
            has_input_validation=True,
            existing_controls=[]
        )
        threats.append(Threat(
            id=f"TM-R-{threat_id:03d}",
            category=StrideCategory.REPUDIATION,
            title="Audit Logging Review Required",
            description="Verify that security-relevant actions are logged with sufficient context for audit trails.",
            affected_assets=[ep.id for ep in assets.entry_points[:5]],
            attack_vector="Actions performed without traceability",
            prerequisites=["Lack of audit logging"],
            risk=risk,
            existing_controls=[],
            recommended_controls=[
                "Log authentication events (success/failure)",
                "Log authorization decisions",
                "Log data access and modifications",
                "Include user context, timestamp, and action details",
                "Protect logs from tampering"
            ],
            code_locations=[],
            references=["OWASP Logging Cheat Sheet", "NIST SP 800-92"]
        ))

    return threats


def identify_control_gaps(
    assets: AssetInventory,
    threats: list[Threat]
) -> list[dict[str, Any]]:
    """Identify missing security controls.

    Args:
        assets: Discovered asset inventory
        threats: List of identified threats

    Returns:
        List of control gaps with recommendations
    """
    gaps = []

    # Check for authentication coverage
    unauthenticated = [ep for ep in assets.entry_points if not ep.authentication_required]
    if unauthenticated and len(unauthenticated) > len(assets.entry_points) * 0.3:
        gaps.append({
            "control": "Authentication",
            "gap": f"{len(unauthenticated)} of {len(assets.entry_points)} endpoints lack authentication",
            "priority": "high",
            "affected": [ep.id for ep in unauthenticated]
        })

    # Check for missing auth mechanisms
    if assets.entry_points and not assets.authentication:
        gaps.append({
            "control": "Authentication Framework",
            "gap": "No authentication framework detected",
            "priority": "critical",
            "recommendation": "Implement authentication using NextAuth, Clerk, or similar"
        })

    # Check for hardcoded secrets
    if assets.secrets:
        gaps.append({
            "control": "Secret Management",
            "gap": f"{len(assets.secrets)} potential hardcoded secrets found",
            "priority": "critical",
            "recommendation": "Use environment variables or secret management service"
        })

    # Check critical threats without controls
    critical_threats = [t for t in threats if t.risk.level in [RiskLevel.CRITICAL, RiskLevel.HIGH]]
    uncontrolled = [t for t in critical_threats if not t.existing_controls]
    if uncontrolled:
        gaps.append({
            "control": "Critical Threat Mitigation",
            "gap": f"{len(uncontrolled)} critical/high threats without existing controls",
            "priority": "critical",
            "affected": [t.id for t in uncontrolled]
        })

    return gaps


__all__ = [
    "calculate_risk_score",
    "analyze_stride_threats",
    "identify_control_gaps",
]
