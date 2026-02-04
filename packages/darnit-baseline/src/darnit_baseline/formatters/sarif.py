"""SARIF 2.1.0 output generator for OpenSSF Baseline audits.

This module generates SARIF (Static Analysis Results Interchange Format)
output compatible with GitHub Code Scanning and other SARIF tools.

SARIF metadata is read from the framework TOML config (openssf-baseline.toml).
The rules/catalog.py is deprecated and used only as a fallback.

Specification: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html
"""

import hashlib
import os
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from darnit.core.logging import get_logger
from darnit.core.models import AuditResult

logger = get_logger("formatters.sarif")


# =============================================================================
# Framework Config Loading (Primary source - TOML)
# =============================================================================


@lru_cache(maxsize=1)
def _load_framework_config():
    """Load framework config from TOML (cached).

    Returns:
        FrameworkConfig or None if loading fails
    """
    try:
        from darnit.config.merger import load_framework_by_name
        return load_framework_by_name("openssf-baseline")
    except Exception as e:
        logger.debug(f"Could not load framework config: {e}")
        return None


def _get_control_from_toml(control_id: str) -> dict[str, Any] | None:
    """Get control metadata from TOML framework config.

    Args:
        control_id: OSPS control ID

    Returns:
        Control metadata dict or None if not found
    """
    config = _load_framework_config()
    if not config:
        return None

    control = config.controls.get(control_id)
    if not control:
        return None

    # Convert ControlConfig to dict compatible with old catalog format
    # Extract level/domain/security_severity from tags if not top-level
    level = control.level
    if level is None and control.tags:
        level = control.tags.get("level", 1)

    domain = control.domain
    if domain is None and control.tags:
        domain = control.tags.get("domain", "")

    security_severity = control.security_severity
    if security_severity is None and control.tags:
        security_severity = control.tags.get("security_severity", 5.0)

    # Build tags list from tags dict keys that have truthy values
    tag_list = []
    if control.tags:
        for key, value in control.tags.items():
            if isinstance(value, bool) and value:
                tag_list.append(key)
            elif key not in ("level", "domain", "security_severity"):
                # Include non-metadata tags
                if isinstance(value, bool) and value:
                    tag_list.append(key)

    # Map severity to default_level
    if security_severity is not None:
        if security_severity >= 7.0:
            default_level = "error"
        elif security_severity >= 4.0:
            default_level = "warning"
        else:
            default_level = "note"
    else:
        default_level = "warning"

    return {
        "name": control.name,
        "domain": domain or "",
        "level": level or 1,
        "short": control.description[:100] if control.description else control.name,
        "full": control.description or "",
        "help_md": control.help_md or "",
        "security_severity": security_severity or 5.0,
        "tags": tag_list,
        "location_hint": "",  # TODO: Extract from locator if present
        "default_level": default_level,
        "docs_url": control.docs_url or f"https://baseline.openssf.org/versions/2025-10-10#{control_id}",
    }


# =============================================================================
# Legacy Catalog Fallback (Deprecated)
# =============================================================================


def _get_rule_from_catalog(control_id: str) -> dict[str, Any] | None:
    """Get rule from legacy catalog (fallback).

    DEPRECATED: This function will be removed once all metadata
    is migrated to TOML.
    """
    try:
        from darnit_baseline.rules.catalog import get_rule
        return get_rule(control_id)
    except ImportError:
        return None


def _get_domain_info_from_catalog(domain: str) -> dict[str, Any]:
    """Get domain info from legacy catalog (fallback)."""
    try:
        from darnit_baseline.rules.catalog import DOMAIN_INFO
        return DOMAIN_INFO.get(domain, {})
    except ImportError:
        return {}


def get_rule(control_id: str) -> dict[str, Any] | None:
    """Get rule metadata for a control ID.

    Primary source: TOML framework config
    Fallback: Legacy rules/catalog.py

    Args:
        control_id: OSPS control ID

    Returns:
        Rule metadata dict or None
    """
    # Try TOML first
    rule = _get_control_from_toml(control_id)
    if rule:
        return rule

    # Fallback to legacy catalog
    return _get_rule_from_catalog(control_id)


# Domain info - merged from both sources
DOMAIN_INFO = {
    "AC": {"name": "Access Control", "tags": ["access-control", "authentication", "authorization"]},
    "BR": {"name": "Build and Release", "tags": ["build", "release", "ci-cd", "supply-chain"]},
    "DO": {"name": "Documentation", "tags": ["documentation"]},
    "GV": {"name": "Governance", "tags": ["governance", "maintainership"]},
    "LE": {"name": "Legal", "tags": ["legal", "licensing"]},
    "QA": {"name": "Quality Assurance", "tags": ["quality", "testing"]},
    "SA": {"name": "Security Assessment", "tags": ["security-analysis", "architecture"]},
    "VM": {"name": "Vulnerability Management", "tags": ["vulnerability", "security"]},
}


# SARIF schema URL
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
SARIF_VERSION = "2.1.0"

# Tool information
TOOL_NAME = "openssf-baseline-audit"
TOOL_VERSION = "0.1.0"
TOOL_INFO_URI = "https://baseline.openssf.org/"

# Status to SARIF level mapping
STATUS_TO_LEVEL = {
    "FAIL": "error",
    "ERROR": "error",
    "WARN": "warning",
    "PASS": "note",
    "N/A": "none",
}

# Level to base severity mapping (0.1-10.0 scale)
LEVEL_BASE_SEVERITY = {
    1: 8.0,  # Level 1: Critical security hygiene
    2: 5.5,  # Level 2: Enhanced security
    3: 3.5,  # Level 3: Advanced security
}


def generate_sarif_audit(
    audit_result: AuditResult,
    include_passing: bool = False,
    include_na: bool = False,
) -> dict[str, Any]:
    """Generate SARIF 2.1.0 output for baseline audit.

    Args:
        audit_result: Complete audit result from baseline checks
        include_passing: Include PASS results in output (default: False)
        include_na: Include N/A results in output (default: False)

    Returns:
        SARIF-formatted dictionary ready for JSON serialization
    """
    # Build rules array from all controls that have results
    result_control_ids = {r["id"] for r in audit_result.all_results}
    rules = build_sarif_rules(list(result_control_ids))

    # Create rule index mapping
    rule_index_map = {rule["id"]: idx for idx, rule in enumerate(rules)}

    # Convert results to SARIF format
    sarif_results = []
    for check_result in audit_result.all_results:
        status = check_result.get("status", "ERROR")

        # Filter based on status
        if status == "PASS" and not include_passing:
            continue
        if status == "N/A" and not include_na:
            continue

        control_id = check_result["id"]
        rule_index = rule_index_map.get(control_id, 0)

        sarif_result = result_to_sarif_result(
            check_result,
            rule_index,
            audit_result.local_path,
            audit_result.repo,
        )
        sarif_results.append(sarif_result)

    # Build the complete SARIF document
    sarif = {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [{
            "tool": {
                "driver": {
                    "name": TOOL_NAME,
                    "version": TOOL_VERSION,
                    "informationUri": TOOL_INFO_URI,
                    "rules": rules,
                }
            },
            "results": sarif_results,
            "invocations": [{
                "executionSuccessful": True,
                "endTimeUtc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }],
            "properties": {
                "owner": audit_result.owner,
                "repo": audit_result.repo,
                "level": audit_result.level,
                "compliance": {
                    f"level{lvl}": compliant
                    for lvl, compliant in (audit_result.level_compliance or {}).items()
                },
                "summary": audit_result.summary or {},
                "commit": audit_result.commit,
                "ref": audit_result.ref,
            }
        }]
    }

    return sarif


def build_sarif_rules(
    control_ids: list[str] | None = None
) -> list[dict[str, Any]]:
    """Build SARIF rules array for OSPS controls.

    Args:
        control_ids: Specific control IDs to include (default: all)

    Returns:
        List of SARIF reportingDescriptor objects
    """
    rules = []

    # Use specified controls or get all from framework config
    if control_ids:
        ids_to_include = control_ids
    else:
        # Get all control IDs from framework config
        config = _load_framework_config()
        if config:
            ids_to_include = list(config.controls.keys())
        else:
            # Fallback to legacy catalog
            try:
                from darnit_baseline.rules.catalog import OSPS_RULES
                ids_to_include = list(OSPS_RULES.keys())
            except ImportError:
                ids_to_include = []

    for control_id in sorted(ids_to_include):
        rule_meta = get_rule(control_id)
        if not rule_meta:
            # Create minimal rule for unknown control
            rule_meta = {
                "name": control_id.replace("-", "").replace(".", ""),
                "domain": control_id.split("-")[1] if "-" in control_id else "XX",
                "level": 1,
                "short": control_id,
                "full": f"OSPS Control {control_id}",
                "help_md": f"See https://baseline.openssf.org for details on {control_id}",
                "security_severity": 5.0,
                "tags": [],
                "default_level": "warning",
            }

        # Get domain info for tags
        domain = rule_meta.get("domain", "")
        domain_info = DOMAIN_INFO.get(domain, {})
        domain_tags = domain_info.get("tags", [])

        # Build tags list
        tags = ["security"] + domain_tags + rule_meta.get("tags", [])
        tags.append(f"OSPS-Level-{rule_meta.get('level', 1)}")
        # Deduplicate while preserving order
        seen = set()
        unique_tags = []
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)

        rule = {
            "id": control_id,
            "name": rule_meta.get("name", control_id),
            "shortDescription": {
                "text": rule_meta.get("short", control_id)[:1024]
            },
            "fullDescription": {
                "text": rule_meta.get("full", "")[:1024]
            },
            "helpUri": f"https://baseline.openssf.org/versions/2025-10-10#{control_id}",
            "help": {
                "text": _strip_markdown(rule_meta.get("help_md", "")),
                "markdown": rule_meta.get("help_md", ""),
            },
            "defaultConfiguration": {
                "level": rule_meta.get("default_level", "warning")
            },
            "properties": {
                "tags": unique_tags[:20],  # GitHub limits to 20 tags
                "precision": "high",
                "problem.severity": rule_meta.get("default_level", "warning"),
                "security-severity": str(rule_meta.get("security_severity", 5.0)),
            }
        }
        rules.append(rule)

    return rules


def result_to_sarif_result(
    result: dict[str, Any],
    rule_index: int,
    local_path: str,
    repo: str,
) -> dict[str, Any]:
    """Convert a check result to SARIF result format.

    Args:
        result: Check result dictionary from baseline audit
        rule_index: Index of the rule in the rules array
        local_path: Repository path for location resolution
        repo: Repository name for fingerprinting

    Returns:
        SARIF result object
    """
    control_id = result["id"]
    status = result.get("status", "ERROR")
    details = result.get("details", "")
    level = result.get("level", 1)

    # Map status to SARIF level
    sarif_level = STATUS_TO_LEVEL.get(status, "warning")

    # Get location for this control
    location = get_location_for_control(control_id, local_path)

    # Generate fingerprint for alert deduplication
    fingerprint = _generate_fingerprint(control_id, repo, status)

    sarif_result = {
        "ruleId": control_id,
        "ruleIndex": rule_index,
        "level": sarif_level,
        "message": {
            "text": details or f"{control_id}: {status}"
        },
        "locations": [location],
        "partialFingerprints": {
            "primaryLocationLineHash": fingerprint
        },
        "properties": {
            "ospsLevel": level,
            "status": status,
        }
    }

    return sarif_result


def get_location_for_control(
    control_id: str,
    local_path: str,
) -> dict[str, Any]:
    """Determine file location for a control result.

    Maps controls to their most relevant file locations for
    code linking in GitHub and IDEs.

    Args:
        control_id: OSPS control ID
        local_path: Repository path

    Returns:
        SARIF physicalLocation object
    """
    # Get location hint from rules catalog
    rule_meta = get_rule(control_id)
    location_hint = rule_meta.get("location_hint", "") if rule_meta else ""

    # Default location (repository root)
    uri = "README.md"
    start_line = 1

    # Try to find the actual file
    if location_hint:
        # Handle directory hints
        if location_hint.endswith("/") or location_hint == ".github/workflows":
            # Look for files in the directory
            hint_path = os.path.join(local_path, location_hint.rstrip("/"))
            if os.path.isdir(hint_path):
                files = os.listdir(hint_path)
                if files:
                    # Use first YAML or first file
                    yaml_files = [f for f in files if f.endswith((".yml", ".yaml"))]
                    uri = f"{location_hint.rstrip('/')}/{yaml_files[0] if yaml_files else files[0]}"
        else:
            # Direct file hint
            hint_path = os.path.join(local_path, location_hint)
            if os.path.isfile(hint_path):
                uri = location_hint
            else:
                # Try common variations
                variations = [
                    location_hint,
                    f".github/{location_hint}",
                    f"docs/{location_hint}",
                ]
                for var in variations:
                    var_path = os.path.join(local_path, var)
                    if os.path.isfile(var_path):
                        uri = var
                        break

    # Ensure the file exists, fall back to README.md
    if not os.path.isfile(os.path.join(local_path, uri)):
        # Try common fallbacks based on domain
        domain = control_id.split("-")[1] if "-" in control_id else ""
        fallbacks = {
            "AC": [".github/settings.yml", "README.md"],
            "BR": [".github/workflows/ci.yml", ".github/workflows/build.yml", "README.md"],
            "DO": ["README.md", "docs/README.md"],
            "GV": ["GOVERNANCE.md", "CONTRIBUTING.md", "README.md"],
            "LE": ["LICENSE", "LICENSE.md", "README.md"],
            "QA": [".github/workflows/test.yml", "README.md"],
            "SA": ["SECURITY.md", "docs/ARCHITECTURE.md", "README.md"],
            "VM": ["SECURITY.md", "README.md"],
        }
        for fallback in fallbacks.get(domain, ["README.md"]):
            if os.path.isfile(os.path.join(local_path, fallback)):
                uri = fallback
                break
        else:
            # Last resort - just use the hint even if file doesn't exist
            uri = location_hint if location_hint else "README.md"

    return {
        "physicalLocation": {
            "artifactLocation": {
                "uri": uri,
                "uriBaseId": "%SRCROOT%"
            },
            "region": {
                "startLine": start_line,
                "startColumn": 1
            }
        }
    }


def _generate_fingerprint(control_id: str, repo: str, status: str) -> str:
    """Generate stable fingerprint for alert deduplication.

    Args:
        control_id: OSPS control ID
        repo: Repository name
        status: Check status

    Returns:
        16-character hex fingerprint
    """
    content = f"{control_id}:{repo}:{status}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _strip_markdown(text: str) -> str:
    """Strip markdown formatting for plain text help.

    Args:
        text: Markdown text

    Returns:
        Plain text version
    """
    # Simple markdown stripping
    import re

    # Remove code blocks
    text = re.sub(r"```[\s\S]*?```", "", text)
    # Remove inline code
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove bold/italic
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    # Remove links but keep text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove headers
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    # Clean up extra whitespace
    text = re.sub(r"\n\s*\n", "\n\n", text)

    return text.strip()


__all__ = [
    "generate_sarif_audit",
    "build_sarif_rules",
    "result_to_sarif_result",
    "get_location_for_control",
    "SARIF_SCHEMA",
    "SARIF_VERSION",
    "TOOL_NAME",
    "TOOL_VERSION",
]
