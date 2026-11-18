"""Shared constants, helpers, and configuration for threat model renderers.

Extracted from ``ts_generators.py`` to support the multi-file output layout.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass

from ..discovery_models import CandidateFinding
from ..models import StrideCategory

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

VERIFICATION_PROMPT_OPEN = "<!-- darnit:verification-prompt-block -->"
VERIFICATION_PROMPT_CLOSE = "<!-- /darnit:verification-prompt-block -->"


@dataclass(frozen=True)
class GeneratorOptions:
    """Tunables passed to the Markdown / SARIF / JSON emitters."""

    detail_level: str = "detailed"  # "detailed" | "summary"
    max_dfd_nodes: int = 50
    top_risks_cap: int = 20


# ---------------------------------------------------------------------------
# STRIDE category ordering & titles
# ---------------------------------------------------------------------------

STRIDE_ORDER: tuple[StrideCategory, ...] = (
    StrideCategory.SPOOFING,
    StrideCategory.TAMPERING,
    StrideCategory.REPUDIATION,
    StrideCategory.INFORMATION_DISCLOSURE,
    StrideCategory.DENIAL_OF_SERVICE,
    StrideCategory.ELEVATION_OF_PRIVILEGE,
)

STRIDE_HEADINGS: dict[StrideCategory, str] = {
    StrideCategory.SPOOFING: "Spoofing",
    StrideCategory.TAMPERING: "Tampering",
    StrideCategory.REPUDIATION: "Repudiation",
    StrideCategory.INFORMATION_DISCLOSURE: "Information Disclosure",
    StrideCategory.DENIAL_OF_SERVICE: "Denial of Service",
    StrideCategory.ELEVATION_OF_PRIVILEGE: "Elevation of Privilege",
}

STRIDE_ABBREV: dict[StrideCategory, str] = {
    StrideCategory.SPOOFING: "S",
    StrideCategory.TAMPERING: "T",
    StrideCategory.REPUDIATION: "R",
    StrideCategory.INFORMATION_DISCLOSURE: "I",
    StrideCategory.DENIAL_OF_SERVICE: "D",
    StrideCategory.ELEVATION_OF_PRIVILEGE: "E",
}


# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------


def severity_band(severity: int, confidence: float) -> str:
    """Map ``severity * confidence`` to a human-readable band."""
    score = severity * confidence
    if score >= 7.0:
        return "CRITICAL"
    if score >= 4.5:
        return "HIGH"
    if score >= 2.0:
        return "MEDIUM"
    return "LOW"


def risk_counts(findings: list[CandidateFinding]) -> dict[str, int]:
    """Count findings per severity band."""
    counts: dict[str, int] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
    for f in findings:
        band = severity_band(f.severity, f.confidence)
        counts[band] += 1
    return counts


# ---------------------------------------------------------------------------
# Slug helper
# ---------------------------------------------------------------------------


def query_id_to_slug(query_id: str) -> str:
    """Convert a tree-sitter query ID to a filesystem-safe slug.

    Example: ``python.sink.dangerous_attr`` → ``python-sink-dangerous_attr``
    """
    return query_id.replace(".", "-")


# ---------------------------------------------------------------------------
# Repo display name
# ---------------------------------------------------------------------------


def _remote_owner_repo(repo_path: str) -> tuple[str | None, str | None]:
    for remote in ("origin", "upstream"):
        try:
            proc = subprocess.run(  # noqa: S603,S607
                ["git", "-C", repo_path, "remote", "get-url", remote],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0:
                url = proc.stdout.strip().rstrip("/")
                m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", url)
                if m:
                    return m.group(1), m.group(2)
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            pass
    return None, None


def repo_display_name(
    repo_path: str,
    owner: str | None = None,
    repo: str | None = None,
) -> str:
    """Derive a safe display name for the repository.

    Uses the explicitly given repository identity first (``owner/repo``),
    then tries git remote URL (``owner/repo``), and finally falls back to
    the directory basename. Never leaks an absolute local path.
    """
    clean_owner = (owner or "").strip().strip("/")
    clean_repo = (repo or "").strip().strip("/")

    if "/" in clean_repo:
        return clean_repo

    if clean_owner and clean_repo:
        return f"{clean_owner}/{clean_repo}"

    remote_owner, remote_repo = _remote_owner_repo(repo_path)
    final_owner = clean_owner or remote_owner
    final_repo = clean_repo or remote_repo or os.path.basename(os.path.abspath(repo_path))

    if final_owner:
        return f"{final_owner}/{final_repo}"
    return final_repo
