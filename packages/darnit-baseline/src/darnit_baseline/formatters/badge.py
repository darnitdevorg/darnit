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

Key transform:  OSPS-AC-01.01 -> osps_ac_01_01
Status mapping: PASS -> Met | FAIL -> Unmet | WARN -> ? | NA/N/A -> N/A

Justification policy:
    Only Met (PASS) and Unmet (FAIL) results include a justification.
    Inconclusive (WARN -> ?) and N/A results never include one, to avoid
    surfacing error messages or command-not-found noise in badge submissions.

URL budget:
    Total URL is capped at _URL_BUDGET_BYTES (6 KB). All _status params are
    always included. Justifications are appended only while the running total
    stays within budget.
"""

from urllib.parse import quote, urlencode

BADGE_BASE_URL = "https://www.bestpractices.dev/projects"

# Maximum per-justification length (characters) before truncation.
# Short justifications keep URLs well within browser and server limits
# and match the badge form's expectation of human-readable notes.
_MAX_JUSTIFICATION_LEN = 200

# Total URL budget in bytes. Common server/proxy limits are 8 KB; we leave
# headroom so the URL reliably works everywhere.
_URL_BUDGET_BYTES = 6 * 1024  # 6 KB

# Only these badge statuses warrant a justification in the URL.
_JUSTIFICATION_STATUSES = {"Met", "Unmet"}

# Status mapping from darnit audit statuses to badge site values.
_STATUS_MAP: dict[str, str] = {
    "PASS": "Met",
    "FAIL": "Unmet",
    "WARN": "?",   # inconclusive — cannot assert Met or Unmet
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
    # Replace hyphens and dots with underscores, then lowercase.
    key = control_id.replace("-", "_").replace(".", "_").lower()
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

    Builds a URL that pre-fills the badge entry form at
    https://www.bestpractices.dev with the status and (where appropriate) the
    justification for each OSPS control in the audit results. The maintainer
    can follow the link, review the pre-filled fields, and submit to earn
    their badge.

    Rules applied to keep the URL safe and clean:

    * Every control gets a ``_status`` parameter (always included).
    * Justifications are only added for **Met** (PASS) and **Unmet** (FAIL)
      results. Inconclusive (``?``) and N/A results never get a justification,
      preventing error messages or command-not-found text from reaching a real
      badge submission.
    * The total URL is capped at 6 KB. Justifications are added in result
      order until the budget is exhausted; the remaining status params are
      still included without justification.

    Args:
        results:     List of audit result dicts, each containing at minimum
                     ``"id"`` (str), ``"status"`` (str), and optionally
                     ``"details"`` (str).
        project_url: The project's canonical repository URL
                     (e.g. ``"https://github.com/curl/curl"``).
                     Required for a valid badge submission but the URL is
                     still generated without it (with a warning).

    Returns:
        A formatted string containing a header and the automation-proposal URL.
    """
    # --- Pass 1: build all _status params (always included) -----------------
    status_params: list[tuple[str, str]] = [("as", "edit")]
    if project_url:
        status_params.append(("url", project_url))

    valid_results: list[tuple[str, str, str]] = []  # (key_prefix, badge_status, details)
    for result in results:
        control_id: str = result.get("id", "")
        status: str = result.get("status", "")
        details: str = result.get("details", "") or ""

        if not control_id or not status:
            continue

        key_prefix = control_id_to_key(control_id)
        badge_status = status_to_badge_status(status)
        status_params.append((f"{key_prefix}_status", badge_status))
        valid_results.append((key_prefix, badge_status, details))

    # --- Pass 2: add justifications within the URL budget -------------------
    # Calculate the base URL length with all status params but no justifications.
    base_query = urlencode(status_params, quote_via=quote)
    base_url = f"{BADGE_BASE_URL}?{base_query}"
    remaining_budget = _URL_BUDGET_BYTES - len(base_url.encode())

    # Build final params: status params first, then interleave justifications.
    final_params: list[tuple[str, str]] = list(status_params)
    justification_pairs: list[tuple[str, str]] = []

    for key_prefix, badge_status, details in valid_results:
        # Only Met/Unmet warrant justification text
        if badge_status not in _JUSTIFICATION_STATUSES:
            continue

        justification = details.strip()
        if not justification:
            continue

        if len(justification) > _MAX_JUSTIFICATION_LEN:
            justification = justification[:_MAX_JUSTIFICATION_LEN] + "..."

        # Estimate the encoded cost of adding this param
        encoded_pair = urlencode(
            [(f"{key_prefix}_justification", justification)], quote_via=quote
        )
        cost = len(f"&{encoded_pair}".encode())

        if remaining_budget < cost:
            # Budget exhausted — skip remaining justifications
            break

        remaining_budget -= cost
        justification_pairs.append((f"{key_prefix}_justification", justification))

    final_params.extend(justification_pairs)

    query = urlencode(final_params, quote_via=quote)
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
            "> WARNING: No project URL detected.  The link above is missing the `url=` parameter.",
            "> Pass `project_url=` to `audit_openssf_baseline` to include it,",
            "> which is required for a valid badge submission.",
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
