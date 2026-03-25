"""Exploitation scenario templates for STRIDE threats.

Each threat sub-type has a predefined template with:
- steps: Ordered exploitation steps (>=3)
- data_flow_pattern: Affected data flow description
- control_rankings: Controls ranked by effectiveness with rationale

The get_scenario() function is the extension point for future LLM enrichment.
"""

from __future__ import annotations

from .models import RankedControl

# Keyed by threat sub-type as used in stride.py
SCENARIO_TEMPLATES: dict[str, dict] = {
    "unauthenticated_endpoint": {
        "steps": [
            "Attacker discovers unauthenticated API endpoint through reconnaissance or documentation",
            "Attacker sends crafted requests directly to the endpoint without credentials",
            "Endpoint processes the request and returns data or performs actions without identity verification",
            "Attacker leverages unauthorized access to enumerate resources or exfiltrate data",
        ],
        "data_flow_pattern": "external actor → unauthenticated endpoint → backend service/database",
        "control_rankings": [
            RankedControl(
                control="Implement authentication middleware",
                effectiveness="high",
                rationale="Blocks unauthorized access at the entry point before any processing occurs",
            ),
            RankedControl(
                control="Use session-based or token-based authentication",
                effectiveness="high",
                rationale="Provides verifiable identity for every request",
            ),
            RankedControl(
                control="Apply authentication at the route level",
                effectiveness="medium",
                rationale="Ensures no endpoint is accidentally left unprotected",
            ),
        ],
    },
    "hardcoded_secret": {
        "steps": [
            "Attacker gains access to source code through repository exposure, leaked backup, or insider access",
            "Attacker extracts hardcoded credentials from the source code",
            "Attacker uses the extracted credentials to authenticate to external services or internal systems",
            "Attacker performs lateral movement using the compromised credentials",
        ],
        "data_flow_pattern": "source code repository → attacker extraction → target service authentication",
        "control_rankings": [
            RankedControl(
                control="Move secrets to environment variables",
                effectiveness="high",
                rationale="Separates credentials from source code, preventing exposure through repository access",
            ),
            RankedControl(
                control="Use a secrets management service (Vault, AWS Secrets Manager)",
                effectiveness="high",
                rationale="Centralizes secret rotation and access control with audit logging",
            ),
            RankedControl(
                control="Rotate compromised credentials immediately",
                effectiveness="medium",
                rationale="Limits the window of exposure for already-leaked credentials",
            ),
        ],
    },
    "injection_sql": {
        "steps": [
            "Attacker identifies input fields that interact with database queries",
            "Attacker crafts SQL injection payload to manipulate query logic",
            "Malicious SQL executes against the database, bypassing application controls",
            "Attacker extracts sensitive data, modifies records, or escalates privileges",
        ],
        "data_flow_pattern": "user input → application query builder → database execution → data exfiltration",
        "control_rankings": [
            RankedControl(
                control="Use parameterized queries or prepared statements",
                effectiveness="high",
                rationale="Prevents SQL injection by separating data from query structure",
            ),
            RankedControl(
                control="Use an ORM with built-in query sanitization",
                effectiveness="high",
                rationale="Abstracts database access and prevents direct SQL construction",
            ),
            RankedControl(
                control="Implement input validation and allowlisting",
                effectiveness="medium",
                rationale="Reduces attack surface but does not fully prevent injection",
            ),
        ],
    },
    "injection_xss": {
        "steps": [
            "Attacker identifies input fields that are reflected in HTML output",
            "Attacker injects malicious JavaScript through the vulnerable input",
            "Victim's browser executes the injected script in the context of the application",
            "Attacker steals session tokens, captures keystrokes, or redirects the victim",
        ],
        "data_flow_pattern": "attacker input → server storage/reflection → victim browser → session/data theft",
        "control_rankings": [
            RankedControl(
                control="Use context-aware output encoding",
                effectiveness="high",
                rationale="Prevents script execution by encoding special characters for the output context",
            ),
            RankedControl(
                control="Implement Content Security Policy (CSP) headers",
                effectiveness="high",
                rationale="Browser-level defense that blocks inline script execution",
            ),
            RankedControl(
                control="Sanitize user input on ingestion",
                effectiveness="medium",
                rationale="Reduces attack surface but may miss encoding-specific bypasses",
            ),
        ],
    },
    "injection_command": {
        "steps": [
            "Attacker identifies application functionality that executes system commands",
            "Attacker injects shell metacharacters or command separators into input",
            "Operating system executes the injected commands with application privileges",
            "Attacker gains shell access, reads sensitive files, or installs persistence mechanisms",
        ],
        "data_flow_pattern": "user input → command construction → OS shell execution → system compromise",
        "control_rankings": [
            RankedControl(
                control="Avoid shell command execution; use language-native APIs",
                effectiveness="high",
                rationale="Eliminates the command injection vector entirely",
            ),
            RankedControl(
                control="Use allowlists for permitted command arguments",
                effectiveness="high",
                rationale="Restricts input to known-safe values only",
            ),
            RankedControl(
                control="Run processes with minimal privileges",
                effectiveness="medium",
                rationale="Limits the damage from successful command injection",
            ),
        ],
    },
    "injection_path_traversal": {
        "steps": [
            "Attacker identifies file access operations that use user-controlled paths",
            "Attacker crafts path traversal sequences (../) to escape the intended directory",
            "Application reads or writes files outside the expected directory boundary",
            "Attacker accesses sensitive configuration files, credentials, or system data",
        ],
        "data_flow_pattern": "user input → file path construction → filesystem access → sensitive file exposure",
        "control_rankings": [
            RankedControl(
                control="Validate and canonicalize file paths before access",
                effectiveness="high",
                rationale="Resolves symbolic links and relative paths to prevent directory escape",
            ),
            RankedControl(
                control="Use a chroot or sandboxed filesystem",
                effectiveness="high",
                rationale="Physically restricts file access to a safe directory",
            ),
            RankedControl(
                control="Implement allowlist of permitted file paths",
                effectiveness="medium",
                rationale="Restricts access to known-safe locations only",
            ),
        ],
    },
    "injection_ssrf": {
        "steps": [
            "Attacker identifies application functionality that makes outbound HTTP requests",
            "Attacker provides a malicious URL pointing to internal services or cloud metadata",
            "Application makes a request to the attacker-controlled destination from within the trusted network",
            "Attacker accesses internal services, cloud credentials, or pivots to internal systems",
        ],
        "data_flow_pattern": "user-supplied URL → application HTTP client → internal network/cloud metadata → data exfiltration",
        "control_rankings": [
            RankedControl(
                control="Validate and allowlist permitted destination hosts",
                effectiveness="high",
                rationale="Prevents requests to internal or unauthorized destinations",
            ),
            RankedControl(
                control="Block requests to private IP ranges and cloud metadata endpoints",
                effectiveness="high",
                rationale="Prevents the most common SSRF exploitation targets",
            ),
            RankedControl(
                control="Use a dedicated egress proxy for outbound requests",
                effectiveness="medium",
                rationale="Centralizes network access control for outbound traffic",
            ),
        ],
    },
    "injection_code": {
        "steps": [
            "Attacker identifies application functionality that evaluates dynamic code (eval, exec)",
            "Attacker crafts input that is interpreted as executable code",
            "Application executes the injected code with full application privileges",
            "Attacker achieves remote code execution, data access, or system compromise",
        ],
        "data_flow_pattern": "user input → code evaluation function → runtime execution → full system access",
        "control_rankings": [
            RankedControl(
                control="Remove all dynamic code evaluation (eval, exec)",
                effectiveness="high",
                rationale="Eliminates the code injection vector entirely",
            ),
            RankedControl(
                control="Use sandboxed execution environments",
                effectiveness="high",
                rationale="Contains the impact of code execution to an isolated context",
            ),
            RankedControl(
                control="Implement strict input validation",
                effectiveness="medium",
                rationale="Reduces attack surface but cannot fully prevent code injection",
            ),
        ],
    },
    "missing_rate_limit": {
        "steps": [
            "Attacker identifies publicly accessible endpoints without rate limiting",
            "Attacker sends high-volume automated requests to exhaust server resources",
            "Server resources (CPU, memory, connections) become saturated",
            "Legitimate users experience degraded performance or complete service unavailability",
        ],
        "data_flow_pattern": "attacker → high-volume requests → public endpoints → resource exhaustion",
        "control_rankings": [
            RankedControl(
                control="Implement rate limiting per IP/user",
                effectiveness="high",
                rationale="Directly prevents request flooding from individual sources",
            ),
            RankedControl(
                control="Use CDN/WAF for DDoS protection",
                effectiveness="high",
                rationale="Absorbs volumetric attacks before they reach the application",
            ),
            RankedControl(
                control="Implement request queuing for expensive operations",
                effectiveness="medium",
                rationale="Prevents resource exhaustion from computationally expensive requests",
            ),
            RankedControl(
                control="Add request throttling",
                effectiveness="medium",
                rationale="Slows down abusive clients without blocking legitimate traffic",
            ),
        ],
    },
    "missing_audit_log": {
        "steps": [
            "Attacker performs unauthorized actions through the application",
            "Due to insufficient logging, the actions leave no auditable trace",
            "Security team cannot detect the breach or determine what was accessed",
            "Attacker continues operating undetected, expanding access over time",
        ],
        "data_flow_pattern": "attacker actions → application processing → no audit trail → undetected compromise",
        "control_rankings": [
            RankedControl(
                control="Log authentication events (success/failure)",
                effectiveness="high",
                rationale="Enables detection of brute force attacks and unauthorized access attempts",
            ),
            RankedControl(
                control="Log authorization decisions",
                effectiveness="high",
                rationale="Creates audit trail for privilege escalation and access control bypass",
            ),
            RankedControl(
                control="Log data access and modifications",
                effectiveness="high",
                rationale="Enables forensic analysis of data breaches",
            ),
            RankedControl(
                control="Include user context, timestamp, and action details",
                effectiveness="medium",
                rationale="Provides sufficient context for incident investigation",
            ),
            RankedControl(
                control="Protect logs from tampering",
                effectiveness="medium",
                rationale="Ensures log integrity for legal and compliance purposes",
            ),
        ],
    },
    "server_action_no_auth": {
        "steps": [
            "Attacker discovers server action endpoints through client-side code analysis",
            "Attacker invokes server actions directly, bypassing client-side authorization checks",
            "Server action executes privileged operations without verifying user permissions",
            "Attacker accesses or modifies data beyond their authorized scope",
        ],
        "data_flow_pattern": "attacker → direct server action invocation → privileged operation → unauthorized data access",
        "control_rankings": [
            RankedControl(
                control="Implement explicit authorization checks",
                effectiveness="high",
                rationale="Verifies user permissions before every sensitive operation",
            ),
            RankedControl(
                control="Validate user permissions before sensitive operations",
                effectiveness="high",
                rationale="Prevents privilege escalation through direct action invocation",
            ),
            RankedControl(
                control="Log server action invocations",
                effectiveness="medium",
                rationale="Enables detection and forensic analysis of unauthorized access",
            ),
        ],
    },
    "pii_handling": {
        "steps": [
            "Attacker exploits an application vulnerability to gain database or API access",
            "Attacker queries or exports personally identifiable information (PII) records",
            "PII data is exfiltrated without encryption or access controls in place",
            "Exposed individuals face identity theft, fraud, or privacy violations",
        ],
        "data_flow_pattern": "application vulnerability → database/API access → PII extraction → identity theft risk",
        "control_rankings": [
            RankedControl(
                control="Encrypt PII at rest and in transit",
                effectiveness="high",
                rationale="Renders extracted data unusable without encryption keys",
            ),
            RankedControl(
                control="Implement access logging for PII access",
                effectiveness="high",
                rationale="Enables detection of unauthorized data access",
            ),
            RankedControl(
                control="Define data retention policies",
                effectiveness="medium",
                rationale="Minimizes the amount of PII available for exfiltration",
            ),
            RankedControl(
                control="Ensure GDPR/CCPA compliance",
                effectiveness="medium",
                rationale="Provides legal framework for data protection practices",
            ),
        ],
    },
    "financial_data_handling": {
        "steps": [
            "Attacker exploits an application vulnerability to access financial data stores",
            "Attacker extracts payment card numbers, bank accounts, or financial records",
            "Financial data is used for fraudulent transactions or sold on dark markets",
            "Organization faces PCI-DSS non-compliance penalties and financial liability",
        ],
        "data_flow_pattern": "application vulnerability → financial data store → data extraction → financial fraud",
        "control_rankings": [
            RankedControl(
                control="Use tokenization for payment card data",
                effectiveness="high",
                rationale="Replaces sensitive card data with non-reversible tokens",
            ),
            RankedControl(
                control="Never store CVV/CVC",
                effectiveness="high",
                rationale="Eliminates the most sensitive card verification data from storage",
            ),
            RankedControl(
                control="Implement PCI-DSS controls",
                effectiveness="high",
                rationale="Industry-standard framework for securing financial data",
            ),
            RankedControl(
                control="Use established payment processors (Stripe, etc.)",
                effectiveness="medium",
                rationale="Offloads payment data handling to PCI-compliant providers",
            ),
        ],
    },
}


def get_scenario(threat_sub_type: str) -> dict | None:
    """Get the exploitation scenario template for a threat sub-type.

    This function is the extension point for future LLM enrichment.
    A future implementation could wrap or replace this to provide
    dynamically generated scenarios.

    Args:
        threat_sub_type: The threat sub-type key (e.g., "unauthenticated_endpoint")

    Returns:
        Template dict with steps, data_flow_pattern, and control_rankings,
        or None if no template exists for the sub-type.
    """
    return SCENARIO_TEMPLATES.get(threat_sub_type)


__all__ = [
    "SCENARIO_TEMPLATES",
    "get_scenario",
]
