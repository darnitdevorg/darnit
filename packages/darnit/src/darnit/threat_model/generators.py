"""Output generators for threat models.

This module provides functions to generate threat model reports
in various formats including Markdown and SARIF.
"""

from datetime import datetime
from typing import Any

from .models import (
    AssetInventory,
    RiskLevel,
    StrideCategory,
    Threat,
)


def generate_markdown_threat_model(
    repo_path: str,
    assets: AssetInventory,
    threats: list[Threat],
    control_gaps: list[dict],
    frameworks: list[str]
) -> str:
    """Generate a markdown-formatted threat model document.

    Args:
        repo_path: Path to the repository
        assets: Discovered asset inventory
        threats: List of identified threats
        control_gaps: List of control gaps
        frameworks: List of detected frameworks

    Returns:
        Markdown-formatted threat model document
    """
    md = []
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

    # STRIDE Threats
    md.append("## Threat Analysis (STRIDE)")
    md.append("")

    for category in StrideCategory:
        category_threats = [t for t in threats if t.category == category]
        if category_threats:
            category_name = category.value.replace("_", " ").title()
            md.append(f"### {category_name}")
            md.append("")

            for threat in category_threats:
                risk_icon = {
                    RiskLevel.CRITICAL: "🔴",
                    RiskLevel.HIGH: "🟠",
                    RiskLevel.MEDIUM: "🟡",
                    RiskLevel.LOW: "🟢",
                    RiskLevel.INFORMATIONAL: "ℹ️"
                }.get(threat.risk.level, "⚪")

                md.append(f"#### {risk_icon} {threat.id}: {threat.title}")
                md.append("")
                md.append(f"**Risk Score:** {threat.risk.overall:.2f} ({threat.risk.level.value.upper()})")
                md.append("")
                md.append(f"**Description:** {threat.description}")
                md.append("")
                md.append(f"**Attack Vector:** {threat.attack_vector}")
                md.append("")

                if threat.code_locations:
                    md.append("**Code Locations:**")
                    for cl in threat.code_locations[:3]:
                        md.append(f"- `{cl.file}:{cl.line_start}` - {cl.annotation}")
                    md.append("")

                if threat.recommended_controls:
                    md.append("**Recommended Controls:**")
                    for control in threat.recommended_controls:
                        md.append(f"- {control}")
                    md.append("")

                if threat.references:
                    md.append("**References:**")
                    for ref in threat.references:
                        md.append(f"- {ref}")
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
            control = threat.recommended_controls[0] if threat.recommended_controls else 'Review required'
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


def generate_sarif_threat_model(repo_path: str, threats: list[Threat]) -> dict[str, Any]:
    """Generate SARIF format for IDE/CI integration.

    Args:
        repo_path: Path to the repository
        threats: List of identified threats

    Returns:
        SARIF-formatted dictionary
    """
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
        # Create rule
        rule = {
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
            }
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

    sarif = {
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
            "results": results
        }]
    }

    return sarif


def generate_json_summary(
    repo_path: str,
    frameworks: list[str],
    assets: AssetInventory,
    threats: list[Threat],
    control_gaps: list[dict]
) -> dict[str, Any]:
    """Generate a JSON summary of the threat model.

    Args:
        repo_path: Path to the repository
        frameworks: List of detected frameworks
        assets: Discovered asset inventory
        threats: List of identified threats
        control_gaps: List of control gaps

    Returns:
        JSON-serializable dictionary
    """
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
                "risk_score": t.risk.overall
            } for t in threats
        ],
        "control_gaps": control_gaps
    }


__all__ = [
    "generate_markdown_threat_model",
    "generate_sarif_threat_model",
    "generate_json_summary",
]
