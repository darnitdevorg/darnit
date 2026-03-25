"""Attack chain detection for STRIDE threat models.

Identifies compound attack paths from predefined STRIDE category
combination patterns with shared-asset tiebreaker.
"""

from __future__ import annotations

from .models import (
    AssetInventory,
    AttackChain,
    RiskLevel,
    RiskScore,
    StrideCategory,
    Threat,
)

# Predefined STRIDE category combination patterns.
# Each pattern maps a frozenset of two categories to a chain descriptor.
CHAIN_PATTERNS: dict[frozenset[StrideCategory], dict[str, str]] = {
    frozenset({StrideCategory.SPOOFING, StrideCategory.INFORMATION_DISCLOSURE}): {
        "name": "Credential Theft → Data Exfiltration",
        "description": (
            "Spoofed identity combined with information disclosure enables "
            "unauthorized access to sensitive data. An attacker who bypasses "
            "authentication can leverage disclosed information to exfiltrate data."
        ),
    },
    frozenset({StrideCategory.TAMPERING, StrideCategory.ELEVATION_OF_PRIVILEGE}): {
        "name": "Input Manipulation → Privilege Escalation",
        "description": (
            "Tampered input combined with insufficient authorization enables "
            "privilege escalation. An attacker who can manipulate inputs may "
            "bypass authorization checks to access privileged operations."
        ),
    },
    frozenset({StrideCategory.REPUDIATION, StrideCategory.INFORMATION_DISCLOSURE}): {
        "name": "Unlogged Access to Sensitive Data",
        "description": (
            "Insufficient audit logging combined with information disclosure "
            "enables undetected data access. An attacker can access sensitive "
            "data without leaving an auditable trace."
        ),
    },
    frozenset({StrideCategory.DENIAL_OF_SERVICE, StrideCategory.TAMPERING}): {
        "name": "Resource Exhaustion → Data Corruption",
        "description": (
            "Denial of service combined with tampering enables data corruption "
            "during resource exhaustion. While systems are degraded, tampered "
            "inputs may bypass validation checks."
        ),
    },
    frozenset({StrideCategory.SPOOFING, StrideCategory.ELEVATION_OF_PRIVILEGE}): {
        "name": "Unauthenticated Access → Admin Escalation",
        "description": (
            "Missing authentication combined with insufficient authorization "
            "enables full privilege escalation. An unauthenticated attacker "
            "can access endpoints and escalate to administrative privileges."
        ),
    },
}


def calculate_composite_risk(threats: list[Threat]) -> RiskScore:
    """Calculate composite risk for an attack chain.

    Formula: max(individual_scores) + 0.1 * sum(other_scores), capped at 1.0

    Args:
        threats: List of threats in the chain (must have >=2)

    Returns:
        Composite RiskScore
    """
    scores = [t.risk.overall for t in threats]
    max_score = max(scores)
    other_sum = sum(s for s in scores if s != max_score)
    # If all scores are equal, other_sum should include all but one
    if other_sum == 0.0 and len(scores) > 1:
        other_sum = sum(scores[1:])

    overall = min(max_score + 0.1 * other_sum, 1.0)
    overall = round(overall, 2)

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

    # Aggregate factors
    likelihood = round(max(t.risk.likelihood for t in threats), 2)
    impact = round(max(t.risk.impact for t in threats), 2)
    effectiveness = round(min(t.risk.control_effectiveness for t in threats), 2)

    return RiskScore(
        overall=overall,
        level=level,
        likelihood=likelihood,
        impact=impact,
        control_effectiveness=effectiveness,
        factors={"chain_size": len(threats), "formula": "max + 0.1 * sum(others)"},
    )


def _find_shared_assets(
    threats_a: list[Threat],
    threats_b: list[Threat],
    assets: AssetInventory,
) -> list[str]:
    """Find shared assets between two groups of threats.

    Shared assets include: entry points, data stores, or code files
    referenced by threats in both groups.
    """
    def _asset_ids(threat_list: list[Threat]) -> set[str]:
        ids: set[str] = set()
        for t in threat_list:
            ids.update(t.affected_assets)
            for cl in t.code_locations:
                ids.add(cl.file)
        return ids

    ids_a = _asset_ids(threats_a)
    ids_b = _asset_ids(threats_b)
    return sorted(ids_a & ids_b)


def detect_attack_chains(
    threats: list[Threat],
    assets: AssetInventory,
) -> list[AttackChain]:
    """Detect compound attack paths from predefined STRIDE patterns.

    For each CHAIN_PATTERN, checks if both categories have threats AND
    share at least one asset. Builds AttackChain objects and back-references
    chain IDs into participating Threat.attack_chain_ids.

    Args:
        threats: All identified threats
        assets: Discovered asset inventory

    Returns:
        List of detected attack chains
    """
    # Group threats by category
    by_category: dict[StrideCategory, list[Threat]] = {}
    for t in threats:
        by_category.setdefault(t.category, []).append(t)

    chains: list[AttackChain] = []
    chain_counter = 0

    for cat_pair, pattern in CHAIN_PATTERNS.items():
        cats = list(cat_pair)
        if len(cats) != 2:
            continue

        cat_a, cat_b = cats[0], cats[1]
        threats_a = by_category.get(cat_a, [])
        threats_b = by_category.get(cat_b, [])

        if not threats_a or not threats_b:
            continue

        # Check for shared assets (tiebreaker)
        shared = _find_shared_assets(threats_a, threats_b, assets)
        if not shared:
            continue

        chain_counter += 1
        chain_id = f"TC-{chain_counter:03d}"

        # Select representative threats (highest risk from each category)
        rep_a = max(threats_a, key=lambda t: t.risk.overall)
        rep_b = max(threats_b, key=lambda t: t.risk.overall)
        chain_threats = [rep_a, rep_b]

        composite = calculate_composite_risk(chain_threats)

        chain = AttackChain(
            id=chain_id,
            name=pattern["name"],
            description=pattern["description"],
            threat_ids=[rep_a.id, rep_b.id],
            categories=[cat_a, cat_b],
            shared_assets=shared[:5],  # Limit to 5 representative shared assets
            composite_risk=composite,
        )
        chains.append(chain)

        # Back-reference chain ID into participating threats
        for t in chain_threats:
            if chain_id not in t.attack_chain_ids:
                t.attack_chain_ids.append(chain_id)

    return chains


__all__ = [
    "CHAIN_PATTERNS",
    "calculate_composite_risk",
    "detect_attack_chains",
]
