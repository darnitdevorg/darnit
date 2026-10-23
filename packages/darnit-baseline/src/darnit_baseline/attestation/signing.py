"""Sigstore signing for attestations.

This module provides cryptographic signing of attestations using
Sigstore keyless signing through the sigstore ``ClientTrustConfig`` API.
Older sigstore releases without it leave attestation signing unavailable.
"""

import json
from typing import Any

from darnit.core.logging import get_logger

logger = get_logger("attestation.signing")

# Optional imports for attestation support
try:
    import hashlib

    from sigstore.dsse import DigestSet, StatementBuilder, Subject
    from sigstore.oidc import Issuer
    from sigstore.sign import ClientTrustConfig, SigningContext

    SIGSTORE_API_VERSION = 3
    ATTESTATION_AVAILABLE = True
except ImportError:
    ATTESTATION_AVAILABLE = False
    SIGSTORE_API_VERSION = 0


def is_attestation_available() -> bool:
    """Check if attestation signing is available.

    Returns:
        True if sigstore dependencies are installed
    """
    return ATTESTATION_AVAILABLE


def get_sigstore_api_version() -> int:
    """Get the detected Sigstore API version.

    Returns:
        0 if not available, 3 for the supported ``ClientTrustConfig`` API
    """
    return SIGSTORE_API_VERSION


def sign_attestation(
    predicate: dict[str, Any],
    predicate_type: str,
    subject_name: str,
    commit: str,
    use_staging: bool = False
) -> dict[str, Any]:
    """Sign an attestation using Sigstore.

    In CI environments (GitHub Actions, GitLab CI, etc.), this uses ambient
    OIDC credentials automatically - no browser interaction needed.

    Locally, this will open a browser for OIDC authentication.

    Args:
        predicate: The attestation predicate to sign
        predicate_type: The predicate type URI
        subject_name: The subject name (e.g., git+https://github.com/owner/repo)
        commit: The git commit SHA
        use_staging: Use Sigstore staging environment for testing

    Returns:
        Signed attestation bundle as dictionary

    Raises:
        RuntimeError: If sigstore dependencies are not installed
    """
    if not ATTESTATION_AVAILABLE:
        raise RuntimeError(
            "Attestation signing requires optional dependencies. "
            "Install with: pip install baseline-mcp[attestation]"
        )

    # Create sigstore-compatible subject
    # Sigstore requires standard hash algorithms (sha256, etc.), not gitCommit
    # We include the commit in the subject name and use sha256 of commit as digest
    commit_digest = hashlib.sha256(commit.encode()).hexdigest()

    subject = Subject(
        name=f"{subject_name}@{commit}",  # e.g., git+https://github.com/owner/repo@abc123
        digest=DigestSet(root={'sha256': commit_digest})
    )

    # Build the in-toto statement using sigstore's StatementBuilder
    builder = StatementBuilder(
        subjects=[subject],
        predicate_type=predicate_type,
        predicate=predicate
    )
    stmt = builder.build()

    # Sign with Sigstore
    # Uses ambient credentials in CI (GitHub Actions, GitLab CI, etc.)
    # Falls back to browser OIDC flow locally
    trust_config = ClientTrustConfig.staging() if use_staging else ClientTrustConfig.production()
    ctx = SigningContext.from_trust_config(trust_config)

    # Get OIDC identity token (ambient in CI, browser flow locally)
    oidc_url = trust_config.signing_config.get_oidc_url()
    issuer = Issuer(oidc_url)
    token = issuer.identity_token()

    with ctx.signer(token, cache=True) as signer:
        bundle = signer.sign_dsse(stmt)

    return json.loads(bundle.to_json())


__all__ = [
    "ATTESTATION_AVAILABLE",
    "SIGSTORE_API_VERSION",
    "is_attestation_available",
    "get_sigstore_api_version",
    "sign_attestation",
]
