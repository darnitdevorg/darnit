"""Reference validation for baseline MCP server."""

import os
import subprocess

from darnit.config.models import ReferenceStatus, ResourceReference
from darnit.core.logging import get_logger
from darnit.core.utils import gh_api_safe

logger = get_logger("config.validation")


def validate_local_reference(ref: ResourceReference, local_path: str) -> tuple[ReferenceStatus, str]:
    """Validate a local file reference."""
    if not ref.path:
        return ReferenceStatus.UNKNOWN, "No path specified"

    full_path = os.path.join(local_path, ref.path)
    if os.path.exists(full_path):
        return ReferenceStatus.VERIFIED, f"File exists: {ref.path}"
    else:
        return ReferenceStatus.MISSING, f"File not found: {ref.path}"


def validate_url_reference(ref: ResourceReference) -> tuple[ReferenceStatus, str]:
    """Validate a URL reference by checking accessibility."""
    if not ref.url:
        return ReferenceStatus.UNKNOWN, "No URL specified"

    try:
        # Use curl for URL validation (available on most systems)
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-L",
             "--max-time", "10", ref.url],
            capture_output=True,
            text=True,
            timeout=15
        )
        status_code = result.stdout.strip()
        if status_code.startswith("2"):
            return ReferenceStatus.VERIFIED, f"URL accessible (HTTP {status_code})"
        elif status_code.startswith("3"):
            return ReferenceStatus.VERIFIED, f"URL redirects (HTTP {status_code})"
        elif status_code == "404":
            return ReferenceStatus.MISSING, "URL not found (HTTP 404)"
        else:
            return ReferenceStatus.EXTERNAL, f"URL returned HTTP {status_code}"
    except subprocess.TimeoutExpired:
        return ReferenceStatus.EXTERNAL, "URL check timed out"
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
        return ReferenceStatus.EXTERNAL, f"Could not validate URL: {e}"


def validate_repo_reference(ref: ResourceReference) -> tuple[ReferenceStatus, str]:
    """Validate a cross-repository reference using GitHub API."""
    if not ref.repo:
        return ReferenceStatus.UNKNOWN, "No repository specified"

    # Check if repo exists
    repo_data = gh_api_safe(f"repos/{ref.repo}")
    if not repo_data:
        return ReferenceStatus.MISSING, f"Repository not found: {ref.repo}"

    # If path specified, check if it exists
    if ref.repo_path:
        # Note: ref_name could be used to check specific branches in future
        _ = ref.repo_ref or repo_data.get("default_branch", "main")
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{ref.repo}/contents/{ref.repo_path}",
                 "-H", "Accept: application/vnd.github.v3+json",
                 "--jq", ".type"],
                capture_output=True,
                text=True,
                timeout=15
            )
            if result.returncode == 0:
                return ReferenceStatus.VERIFIED, f"File exists in {ref.repo}: {ref.repo_path}"
            else:
                return ReferenceStatus.MISSING, f"File not found in {ref.repo}: {ref.repo_path}"
        except subprocess.TimeoutExpired:
            return ReferenceStatus.EXTERNAL, "Repository check timed out"
        except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
            return ReferenceStatus.EXTERNAL, f"Could not validate repository reference: {e}"

    return ReferenceStatus.VERIFIED, f"Repository exists: {ref.repo}"


def validate_reference(ref: ResourceReference, local_path: str) -> tuple[ReferenceStatus, str]:
    """Validate any type of reference."""
    if ref.ref_type == "na":
        return ReferenceStatus.NA, ref.reason or "Marked as not applicable"

    if ref.ref_type == "path":
        return validate_local_reference(ref, local_path)

    if ref.ref_type == "url":
        return validate_url_reference(ref)

    if ref.ref_type == "repo":
        return validate_repo_reference(ref)

    if ref.ref_type == "section":
        # Section references point to headings in other files
        # Parse format: "section.key#heading" or "path#heading"
        if ref.section and "#" in ref.section:
            base, heading = ref.section.rsplit("#", 1)
            # Try to resolve base as a config reference or path
            return ReferenceStatus.EXTERNAL, f"Section reference: {ref.section}"
        return ReferenceStatus.UNKNOWN, "Invalid section reference format"

    return ReferenceStatus.UNKNOWN, f"Unknown reference type: {ref.ref_type}"
