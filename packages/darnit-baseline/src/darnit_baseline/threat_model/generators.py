"""Output generators for threat models.

This module provides functions to generate threat model reports
in various formats including Markdown, SARIF, and JSON.
"""

from datetime import datetime
from typing import Any

from .models import (
    AssetInventory,
    AttackChain,
    RiskLevel,
    StrideCategory,
    Threat,
)

# Human-readable category names and descriptions for empty-category explanations
_CATEGORY_DESCRIPTIONS: dict[StrideCategory, dict[str, str]] = {
    StrideCategory.SPOOFING: {
        "name": "Spoofing",
        "checked": "Checked for unauthenticated endpoints and missing identity verification.",
    },
    StrideCategory.TAMPERING: {
        "name": "Tampering",
        "checked": "Checked for injection vulnerabilities (SQL, command, XSS, path traversal, SSRF, code injection).",
    },
    StrideCategory.REPUDIATION: {
        "name": "Repudiation",
        "checked": "Checked for insufficient audit logging on security-relevant actions.",
    },
    StrideCategory.INFORMATION_DISCLOSURE: {
        "name": "Information Disclosure",
        "checked": "Checked for hardcoded secrets, PII handling, financial data exposure, and XSS.",
    },
    StrideCategory.DENIAL_OF_SERVICE: {
        "name": "Denial Of Service",
        "checked": "Checked for public endpoints without rate limiting.",
    },
    StrideCategory.ELEVATION_OF_PRIVILEGE: {
        "name": "Elevation Of Privilege",
        "checked": "Checked for server actions without authorization and injection-based privilege escalation.",
    },
}

_RISK_ICONS: dict[RiskLevel, str] = {
    RiskLevel.CRITICAL: "🔴",
    RiskLevel.HIGH: "🟠",
    RiskLevel.MEDIUM: "🟡",
    RiskLevel.LOW: "🟢",
    RiskLevel.INFORMATIONAL: "ℹ️",
}


def generate_mermaid_dfd(
    assets: AssetInventory,
    threats: list[Threat],
) -> str:
    """Generate a Mermaid data-flow diagram from asset inventory.

    Args:
        assets: Discovered asset inventory
        threats: List of identified threats (used for >50 node simplification)

    Returns:
        Mermaid flowchart LR string, or empty string if no assets
    """
    if not assets.entry_points and not assets.data_stores:
        return ""

    # Determine if simplification is needed
    total_nodes = (
        len(assets.entry_points)
        + len(assets.data_stores)
        + len(assets.authentication)
        + 1  # external actor
    )
    simplify = total_nodes > 50

    if simplify:
        # Only show entry points connected to CRITICAL/HIGH threats
        high_risk_asset_ids: set[str] = set()
        for t in threats:
            if t.risk.level in (RiskLevel.CRITICAL, RiskLevel.HIGH):
                high_risk_asset_ids.update(t.affected_assets)
        entry_points = [ep for ep in assets.entry_points if ep.id in high_risk_asset_ids]
        data_stores = assets.data_stores[:5]  # Limit data stores
    else:
        entry_points = assets.entry_points
        data_stores = assets.data_stores

    lines = ["```mermaid", "flowchart LR"]

    # External actor
    lines.append('    User(["External Actor"])')

    # Split entry points by auth requirement for trust boundaries
    authed = [ep for ep in entry_points if ep.authentication_required]
    unauthed = [ep for ep in entry_points if not ep.authentication_required]

    if unauthed:
        lines.append("    subgraph Public Zone")
        for ep in unauthed[:20]:
            safe_id = ep.id.replace("-", "_")
            lines.append(f"        {safe_id}[{ep.method} {ep.path}]")
        lines.append("    end")

    if authed:
        lines.append("    subgraph Authenticated Zone")
        for ep in authed[:20]:
            safe_id = ep.id.replace("-", "_")
            lines.append(f"        {safe_id}[{ep.method} {ep.path}]")
        if assets.authentication:
            for auth in assets.authentication[:3]:
                safe_id = auth.id.replace("-", "_")
                lines.append(f"        {safe_id}{{{{{auth.auth_type}}}}}")
        lines.append("    end")

    if data_stores:
        lines.append("    subgraph Data Layer")
        for ds in data_stores[:10]:
            safe_id = ds.id.replace("-", "_")
            lines.append(f"        {safe_id}[({ds.technology})]")
        lines.append("    end")

    # Edges: User -> entry points
    for ep in entry_points[:20]:
        safe_id = ep.id.replace("-", "_")
        lines.append(f"    User --> {safe_id}")

    # Edges: entry points -> data stores (simplified)
    if data_stores:
        ds_id = data_stores[0].id.replace("-", "_")
        for ep in entry_points[:20]:
            safe_id = ep.id.replace("-", "_")
            lines.append(f"    {safe_id} --> {ds_id}")

    lines.append("```")

    if simplify:
        lines.append("")
        lines.append("> **Note:** Diagram simplified to show only high-risk paths. See Asset Inventory table for full details.")

    return "\n".join(lines)


def _render_threat_detailed(threat: Threat) -> list[str]:
    """Render a single threat in detailed mode."""
    md: list[str] = []
    risk_icon = _RISK_ICONS.get(threat.risk.level, "⚪")

    md.append(f"#### {risk_icon} {threat.id}: {threat.title}")
    md.append("")
    md.append(f"**Risk Score:** {threat.risk.overall:.2f} ({threat.risk.level.value.upper()})")
    md.append("")
    md.append(f"**Description:** {threat.description}")
    md.append("")
    md.append(f"**Attack Vector:** {threat.attack_vector}")
    md.append("")

    # Exploitation scenario (new)
    if threat.exploitation_scenario:
        md.append("**Exploitation Scenario:**")
        md.append("")
        for i, step in enumerate(threat.exploitation_scenario, 1):
            md.append(f"{i}. {step}")
        md.append("")

    # Data flow impact (new)
    if threat.data_flow_impact:
        md.append(f"**Data Flow Impact:** {threat.data_flow_impact}")
        md.append("")

    if threat.code_locations:
        md.append("**Code Locations:**")
        for cl in threat.code_locations[:3]:
            md.append(f"- `{cl.file}:{cl.line_start}` - {cl.annotation}")
        md.append("")

    # Ranked controls (new, preferred over recommended_controls)
    if threat.ranked_controls:
        md.append("**Recommended Controls:**")
        md.append("")
        md.append("| Control | Effectiveness | Rationale |")
        md.append("|---------|--------------|-----------|")
        for rc in threat.ranked_controls:
            md.append(f"| {rc.control} | {rc.effectiveness} | {rc.rationale} |")
        md.append("")
    elif threat.recommended_controls:
        md.append("**Recommended Controls:**")
        for control in threat.recommended_controls:
            md.append(f"- {control}")
        md.append("")

    if threat.references:
        md.append("**References:**")
        for ref in threat.references:
            md.append(f"- {ref}")
        md.append("")

    return md


def _render_threat_summary(threat: Threat) -> str:
    """Render a single threat in summary mode (single line)."""
    risk_icon = _RISK_ICONS.get(threat.risk.level, "⚪")
    top_control = ""
    if threat.ranked_controls:
        top_control = threat.ranked_controls[0].control
    elif threat.recommended_controls:
        top_control = threat.recommended_controls[0]
    else:
        top_control = "Review required"
    return f"- {risk_icon} **{threat.id}: {threat.title}** — Risk: {threat.risk.overall:.2f} ({threat.risk.level.value.upper()}) — {top_control}"


def generate_markdown_threat_model(
    repo_path: str,
    assets: AssetInventory,
    threats: list[Threat],
    control_gaps: list[dict],
    frameworks: list[str],
    detail_level: str = "detailed",
    attack_chains: list[AttackChain] | None = None,
) -> str:
    """Generate a markdown-formatted threat model document.

    Args:
        repo_path: Path to the repository
        assets: Discovered asset inventory
        threats: List of identified threats
        control_gaps: List of control gaps
        frameworks: List of detected frameworks
        detail_level: "detailed" (default) or "summary"
        attack_chains: Optional list of detected attack chains

    Returns:
        Markdown-formatted threat model document
    """
    is_summary = detail_level == "summary"
    if attack_chains is None:
        attack_chains = []

    md: list[str] = []
    md.append("# Threat Model Report")
    md.append("")
    md.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    md.append(f"**Repository:** {repo_path}")
    md.append(f"**Frameworks Detected:** {', '.join(frameworks) if frameworks else 'None detected'}")
    md.append("")

    # Executive Summary
    md.append("## Executive Summary")
    md.append("")

    critical = len([t for t in threats if t.risk.level == RiskLevel.CRITICAL])
    high = len([t for t in threats if t.risk.level == RiskLevel.HIGH])
    medium = len([t for t in threats if t.risk.level == RiskLevel.MEDIUM])

    if critical > 0:
        md.append(f"⚠️ **{critical} CRITICAL** threats require immediate attention.")
    if high > 0:
        md.append(f"🔴 **{high} HIGH** severity threats identified.")
    if medium > 0:
        md.append(f"🟡 **{medium} MEDIUM** severity threats should be reviewed.")

    md.append("")
    md.append("| Risk Level | Count |")
    md.append("|------------|-------|")
    md.append(f"| 🔴 Critical | {critical} |")
    md.append(f"| 🟠 High | {high} |")
    md.append(f"| 🟡 Medium | {medium} |")
    md.append(f"| 🟢 Low | {len([t for t in threats if t.risk.level == RiskLevel.LOW])} |")
    md.append(f"| ℹ️ Info | {len([t for t in threats if t.risk.level == RiskLevel.INFORMATIONAL])} |")
    md.append("")

    # Asset Inventory
    md.append("## Asset Inventory")
    md.append("")
    md.append("### Entry Points")
    md.append("")
    if assets.entry_points:
        md.append("| ID | Type | Path | Method | Auth Required | File |")
        md.append("|----|------|------|--------|---------------|------|")
        for ep in assets.entry_points[:20]:
            auth_icon = "✅" if ep.authentication_required else "❌"
            md.append(f"| {ep.id} | {ep.entry_type} | `{ep.path}` | {ep.method} | {auth_icon} | {ep.file}:{ep.line} |")
        if len(assets.entry_points) > 20:
            md.append(f"| ... | | | | | *{len(assets.entry_points) - 20} more* |")
    else:
        md.append("No API entry points detected.")
    md.append("")

    md.append("### Authentication Mechanisms")
    md.append("")
    if assets.authentication:
        for auth in assets.authentication:
            md.append(f"- **{auth.auth_type}** ({auth.file}:{auth.line})")
            md.append(f"  - Assets: {', '.join(auth.assets)}")
    else:
        md.append("⚠️ No authentication framework detected.")
    md.append("")

    md.append("### Data Stores")
    md.append("")
    if assets.data_stores:
        for ds in assets.data_stores:
            md.append(f"- **{ds.technology}** ({ds.store_type}) - {ds.file}:{ds.line}")
    else:
        md.append("No data stores detected.")
    md.append("")

    # Data Flow Diagram (detailed mode only)
    if not is_summary:
        dfd = generate_mermaid_dfd(assets, threats)
        if dfd:
            md.append("## Data Flow Diagram")
            md.append("")
            md.append(dfd)
            md.append("")

    # STRIDE Threats — show all 6 categories
    md.append("## Threat Analysis (STRIDE)")
    md.append("")

    for category in StrideCategory:
        category_threats = [t for t in threats if t.category == category]
        cat_info = _CATEGORY_DESCRIPTIONS.get(category, {"name": category.value.replace("_", " ").title(), "checked": ""})
        category_name = cat_info["name"]

        md.append(f"### {category_name}")
        md.append("")

        if not category_threats:
            # FR-009: Show what was checked for empty categories
            md.append(f"No threats identified. {cat_info['checked']}")
            md.append("")
            continue

        # FR-010: Group and summarize if >10 findings
        if len(category_threats) > 10:
            md.append(f"**{len(category_threats)} threats identified.** Showing representative examples:")
            md.append("")
            # Show top 3 by risk, then summarize the rest
            sorted_threats = sorted(category_threats, key=lambda t: t.risk.overall, reverse=True)
            display_threats = sorted_threats[:3]
            remaining = len(category_threats) - 3
        else:
            display_threats = category_threats
            remaining = 0

        for threat in display_threats:
            if is_summary:
                md.append(_render_threat_summary(threat))
            else:
                md.extend(_render_threat_detailed(threat))

        if remaining > 0:
            md.append("")
            md.append(f"*...and {remaining} additional {category_name.lower()} threats (see SARIF/JSON output for full details).*")
            md.append("")

    # Attack Chains (detailed mode only)
    if not is_summary:
        md.append("## Attack Chains")
        md.append("")
        if attack_chains:
            for chain in attack_chains:
                risk_icon = _RISK_ICONS.get(chain.composite_risk.level, "⚪")
                md.append(f"### {risk_icon} {chain.id}: {chain.name}")
                md.append("")
                md.append(f"**Composite Risk:** {chain.composite_risk.overall:.2f} ({chain.composite_risk.level.value.upper()})")
                md.append("")
                md.append(f"**Description:** {chain.description}")
                md.append("")
                md.append(f"**Constituent Threats:** {', '.join(chain.threat_ids)}")
                md.append("")
                md.append(f"**Shared Assets:** {', '.join(chain.shared_assets[:5])}")
                md.append("")
        else:
            md.append("No compound attack paths identified.")
            md.append("")

    # Control Gaps
    if control_gaps:
        md.append("## Control Gaps")
        md.append("")
        for gap in control_gaps:
            priority_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(gap.get("priority", ""), "⚪")
            md.append(f"### {priority_icon} {gap['control']}")
            md.append("")
            md.append(f"**Gap:** {gap['gap']}")
            if "recommendation" in gap:
                md.append(f"**Recommendation:** {gap['recommendation']}")
            md.append("")

    # Recommendations Summary
    md.append("## Recommendations Summary")
    md.append("")
    md.append("### Immediate Actions (Critical/High)")
    md.append("")

    immediate_threats = [t for t in threats if t.risk.level in [RiskLevel.CRITICAL, RiskLevel.HIGH]]
    if immediate_threats:
        for i, threat in enumerate(immediate_threats[:10], 1):
            if threat.ranked_controls:
                control = threat.ranked_controls[0].control
            elif threat.recommended_controls:
                control = threat.recommended_controls[0]
            else:
                control = "Review required"
            md.append(f"{i}. **{threat.title}** - {control}")
    else:
        md.append("No critical or high severity threats identified.")
    md.append("")

    md.append("### Short-term Actions (Medium)")
    md.append("")
    medium_threats = [t for t in threats if t.risk.level == RiskLevel.MEDIUM]
    if medium_threats:
        for i, threat in enumerate(medium_threats[:5], 1):
            md.append(f"{i}. **{threat.title}**")
    else:
        md.append("No medium severity threats identified.")
    md.append("")

    # Methodology
    md.append("## Methodology")
    md.append("")
    md.append("This threat model was generated using automated static analysis with the STRIDE methodology:")
    md.append("")
    md.append("- **S**poofing - Identity verification threats")
    md.append("- **T**ampering - Data integrity threats")
    md.append("- **R**epudiation - Audit and accountability threats")
    md.append("- **I**nformation Disclosure - Confidentiality threats")
    md.append("- **D**enial of Service - Availability threats")
    md.append("- **E**levation of Privilege - Authorization threats")
    md.append("")
    md.append("### Limitations")
    md.append("")
    md.append("- Static analysis only - runtime behavior not analyzed")
    md.append("- Pattern-based detection may have false positives/negatives")
    md.append("- Business context and risk priorities require human review")
    md.append("- This is not a substitute for professional penetration testing")
    md.append("")

    return "\n".join(md)


def generate_sarif_threat_model(
    repo_path: str,
    threats: list[Threat],
    attack_chains: list[AttackChain] | None = None,
) -> dict[str, Any]:
    """Generate SARIF format for IDE/CI integration.

    Args:
        repo_path: Path to the repository
        threats: List of identified threats
        attack_chains: Optional list of detected attack chains

    Returns:
        SARIF-formatted dictionary
    """
    if attack_chains is None:
        attack_chains = []

    severity_map = {
        RiskLevel.CRITICAL: "error",
        RiskLevel.HIGH: "error",
        RiskLevel.MEDIUM: "warning",
        RiskLevel.LOW: "note",
        RiskLevel.INFORMATIONAL: "note"
    }

    rules = []
    results = []

    for threat in threats:
        # Create rule with extended properties
        rule: dict[str, Any] = {
            "id": threat.id,
            "name": threat.title.replace(" ", ""),
            "shortDescription": {
                "text": threat.title
            },
            "fullDescription": {
                "text": threat.description
            },
            "help": {
                "text": "\n".join(threat.recommended_controls)
            },
            "defaultConfiguration": {
                "level": severity_map.get(threat.risk.level, "warning")
            },
            "properties": {
                "exploitationScenario": threat.exploitation_scenario,
                "dataFlowImpact": threat.data_flow_impact,
                "rankedControls": [
                    {
                        "control": rc.control,
                        "effectiveness": rc.effectiveness,
                        "rationale": rc.rationale,
                    }
                    for rc in threat.ranked_controls
                ],
                "attackChainIds": threat.attack_chain_ids,
            },
        }
        rules.append(rule)

        # Create results for each code location
        for cl in threat.code_locations:
            result = {
                "ruleId": threat.id,
                "level": severity_map.get(threat.risk.level, "warning"),
                "message": {
                    "text": f"{threat.title}: {threat.description}"
                },
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {
                            "uri": cl.file
                        },
                        "region": {
                            "startLine": cl.line_start,
                            "startColumn": 1
                        }
                    }
                }]
            }
            results.append(result)

    sarif: dict[str, Any] = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "threat-model-analyzer",
                    "version": "1.0.0",
                    "informationUri": "https://github.com/openssf/baseline",
                    "rules": rules
                }
            },
            "results": results,
            "properties": {
                "attackChains": [
                    {
                        "id": c.id,
                        "name": c.name,
                        "description": c.description,
                        "threatIds": c.threat_ids,
                        "categories": [cat.value for cat in c.categories],
                        "sharedAssets": c.shared_assets,
                        "compositeRisk": {
                            "overall": c.composite_risk.overall,
                            "level": c.composite_risk.level.value,
                        },
                    }
                    for c in attack_chains
                ],
            },
        }]
    }

    return sarif


def generate_json_summary(
    repo_path: str,
    frameworks: list[str],
    assets: AssetInventory,
    threats: list[Threat],
    control_gaps: list[dict],
    attack_chains: list[AttackChain] | None = None,
) -> dict[str, Any]:
    """Generate a JSON summary of the threat model.

    Args:
        repo_path: Path to the repository
        frameworks: List of detected frameworks
        assets: Discovered asset inventory
        threats: List of identified threats
        control_gaps: List of control gaps
        attack_chains: Optional list of detected attack chains

    Returns:
        JSON-serializable dictionary
    """
    if attack_chains is None:
        attack_chains = []

    return {
        "version": "1.0",
        "repository": repo_path,
        "frameworks": frameworks,
        "assets": {
            "entry_points": len(assets.entry_points),
            "auth_mechanisms": len(assets.authentication),
            "data_stores": len(assets.data_stores),
            "sensitive_fields": len(assets.sensitive_data),
            "secrets": len(assets.secrets)
        },
        "threats": [
            {
                "id": t.id,
                "category": t.category.value,
                "title": t.title,
                "risk_level": t.risk.level.value,
                "risk_score": t.risk.overall,
                "exploitation_scenario": t.exploitation_scenario,
                "data_flow_impact": t.data_flow_impact,
                "ranked_controls": [
                    {
                        "control": rc.control,
                        "effectiveness": rc.effectiveness,
                        "rationale": rc.rationale,
                    }
                    for rc in t.ranked_controls
                ],
                "attack_chain_ids": t.attack_chain_ids,
            } for t in threats
        ],
        "attack_chains": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "threat_ids": c.threat_ids,
                "categories": [cat.value for cat in c.categories],
                "shared_assets": c.shared_assets,
                "composite_risk": {
                    "overall": c.composite_risk.overall,
                    "level": c.composite_risk.level.value,
                },
            }
            for c in attack_chains
        ],
        "control_gaps": control_gaps,
    }


__all__ = [
    "generate_markdown_threat_model",
    "generate_mermaid_dfd",
    "generate_sarif_threat_model",
    "generate_json_summary",
]
