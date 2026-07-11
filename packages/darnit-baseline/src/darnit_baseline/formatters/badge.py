"""OpenSSF Best Practices Badge automation-proposal URL generator.

Converts an OSPS Baseline audit result set into a ready-to-follow URL that
pre-fills the Best Practices Badge entry form for the audited project.

Format reference:
    https://www.bestpractices.dev/projects?as=edit&url=ENCODED_URL&
    KEY=VALUE&KEY=VALUE&...

Example:
    https://www.bestpractices.dev/projects?as=edit&
    url=https%3A%2F%2Fgithub.com%2Fcurl%2Fcurl&
    osps_ac_01_01_status=Met&
    osps_ac_01_01_justification=GitHub+org+enforces+2FA

Key transform:  OSPS-AC-01.01 → osps_ac_01_01
Status mapping: PASS → Met | FAIL → Unmet | WARN → ? | NA/N/A → N/A
"""

import re
from urllib.parse import quote, urlencode

BADGE_BASE_URL = "https://www.bestpractices.dev/projects"

# Maximum justification length (characters) before truncation.
# Keeps URLs within practical browser/server limits.
_MAX_JUSTIFICATION_LEN = 500

# Status mapping from darnit audit statuses to badge site values.
_STATUS_MAP: dict[str, str] = {
    "PASS": "Met",
    "FAIL": "Unmet",
    "WARN": "?",      # inconclusive — cannot assert Met or Unmet
    "NA": "N/A",
    "N/A": "N/A",
}


def control_id_to_key(control_id: str) -> str:
    """Transform an OSPS control ID into a Best Practices Badge parameter key.

    Args:
        control_id: OSPS control ID, e.g. ``"OSPS-AC-01.01"``

    Returns:
        Badge parameter key, e.g. ``"osps_ac_01_01"``

    Examples:
        >>> control_id_to_key("OSPS-AC-01.01")
        'osps_ac_01_01'
        >>> control_id_to_key("OSPS-VM-03.02")
        'osps_vm_03_02'
    """
    # Replace hyphens and dots with underscores, then lowercase
    key = re.sub(r"[-.]", "_", control_id).lower()
    return key


def status_to_badge_status(status: str) -> str:
    """Map a darnit audit status to a Best Practices Badge status string.

    Args:
        status: One of ``"PASS"``, ``"FAIL"``, ``"WARN"``, ``"NA"``, ``"N/A"``

    Returns:
        Badge status: ``"Met"``, ``"Unmet"``, ``"?"``, or ``"N/A"``

    Examples:
        >>> status_to_badge_status("PASS")
        'Met'
        >>> status_to_badge_status("FAIL")
        'Unmet'
        >>> status_to_badge_status("WARN")
        '?'
        >>> status_to_badge_status("NA")
        'N/A'
    """
    return _STATUS_MAP.get(status, "?")


def generate_badge_url(
    results: list[dict],
    project_url: str = "",
) -> str:
    """Generate an OpenSSF Best Practices Badge automation-proposal URL.

    Builds a long URL that pre-fills the badge entry form at
    https://www.bestpractices.dev with the status and justification for each
    OSPS control in the audit results.  The maintainer can follow the link,
    review the pre-filled fields, and submit to earn their badge.

    Args:
        results:     List of audit result dicts, each containing at minimum
                     ``"id"`` (str), ``"status"`` (str), and optionally
                     ``"details"`` (str).
        project_url: The project's canonical repository URL
                     (e.g. ``"https://github.com/curl/curl"``).
                     Required for a valid badge submission but the URL is
                     still generated without it (with a warning comment).

    Returns:
        A fully-formed URL string ready to open in a browser.
    """
    # Collect query parameters in insertion order
    # Start with the fixed preamble
    params: list[tuple[str, str]] = [("as", "edit")]

    if project_url:
        params.append(("url", project_url))

    for result in results:
        control_id: str = result.get("id", "")
        status: str = result.get("status", "")
        details: str = result.get("details", "") or ""

        if not control_id or not status:
            continue

        key_prefix = control_id_to_key(control_id)
        badge_status = status_to_badge_status(status)

        params.append((f"{key_prefix}_status", badge_status))

        # Include justification when available; truncate to keep URL practical
        justification = details.strip()
        if justification:
            if len(justification) > _MAX_JUSTIFICATION_LEN:
                justification = justification[:_MAX_JUSTIFICATION_LEN] + "…"
            params.append((f"{key_prefix}_justification", justification))

    # urlencode uses + for spaces (application/x-www-form-urlencoded),
    # which the badge site accepts and which keeps URLs shorter than %20.
    query = urlencode(params, quote_via=quote)
    url = f"{BADGE_BASE_URL}?{query}"

    header_lines = [
        "## OpenSSF Best Practices Badge — Automation Proposal",
        "",
        "Follow this link to pre-fill your badge entry with the audit results.",
        "Review each field, then submit to claim your badge.",
        "",
    ]

    if not project_url:
        header_lines += [
            "> ⚠️  No project URL detected.  The link above is missing the `url=` parameter.",
            "> Pass `--project-url https://github.com/ORG/REPO` (CLI) or `project_url=` (MCP)",
            "> to include it, which is required for a valid badge submission.",
            "",
        ]

    header_lines.append(url)
    return "\n".join(header_lines)


__all__ = [
    "control_id_to_key",
    "status_to_badge_status",
    "generate_badge_url",
    "BADGE_BASE_URL",
]
