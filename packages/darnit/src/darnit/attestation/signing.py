"""Sigstore signing for attestations.

This module provides cryptographic signing of attestations using
Sigstore keyless signing. It supports multiple Sigstore API versions
(1.x, 2.x, and 3.x) for broad compatibility.
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

    # Import the correct API based on sigstore version
    # sigstore >= 3.0 uses ClientTrustConfig
    try:
        from sigstore.sign import ClientTrustConfig, SigningContext
        SIGSTORE_API_VERSION = 3
    except ImportError:
        # sigstore < 3.0 - try older API
        try:
            from sigstore.sign import Signer
            SIGSTORE_API_VERSION = 2
        except ImportError:
            from sigstore.sign import SigningContext
            SIGSTORE_API_VERSION = 1

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
        0 if not available, 1-3 for supported API versions
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

    # Sign with Sigstore using version-appropriate API
    # Uses ambient credentials in CI (GitHub Actions, GitLab CI, etc.)
    # Falls back to browser OIDC flow locally

    if SIGSTORE_API_VERSION >= 3:
        # sigstore >= 3.0 API
        trust_config = ClientTrustConfig.staging() if use_staging else ClientTrustConfig.production()
        ctx = SigningContext.from_trust_config(trust_config)

        # Get OIDC identity token (ambient in CI, browser flow locally)
        oidc_url = trust_config.signing_config.get_oidc_url()
        issuer = Issuer(oidc_url)
        token = issuer.identity_token()

        with ctx.signer(token, cache=True) as signer:
            bundle = signer.sign_dsse(stmt)

        return json.loads(bundle.to_json())

    elif SIGSTORE_API_VERSION == 2:
        # sigstore 2.x API
        signer = Signer.staging() if use_staging else Signer.production()
        issuer = Issuer.staging() if use_staging else Issuer.production()
        token = issuer.identity_token()

        result = signer.sign_dsse(stmt, identity_token=token)
        return json.loads(result.to_json())

    else:
        # sigstore 1.x API (fallback)
        ctx = SigningContext.staging() if use_staging else SigningContext.production()
        issuer = Issuer.staging() if use_staging else Issuer.production()
        token = issuer.identity_token()

        with ctx.signer(identity_token=token) as signer:
            result = signer.sign(stmt)

        return json.loads(result.bundle.to_json())


__all__ = [
    "ATTESTATION_AVAILABLE",
    "SIGSTORE_API_VERSION",
    "is_attestation_available",
    "get_sigstore_api_version",
    "sign_attestation",
]
