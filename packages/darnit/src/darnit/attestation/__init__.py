"""In-toto attestation generation for OpenSSF Baseline.

This module provides cryptographically signed attestations that prove
a repository's compliance status at a specific git commit. Attestations
follow the in-toto Statement v1 format and use Sigstore for keyless signing.

Usage:
    from darnit.attestation import (
        generate_attestation_from_results,
        build_assessment_predicate,
        sign_attestation,
    )

    # Build predicate from check results
    predicate = build_assessment_predicate(
        owner="owner",
        repo="repo",
        commit="abc123",
        ref="main",
        level=3,
        results=check_results,
        project_config=config,
        adapters_used=["builtin"]
    )

    # Sign with Sigstore
    if is_attestation_available():
        bundle = sign_attestation(
            predicate=predicate,
            predicate_type="https://openssf.org/baseline/assessment/v1",
            subject_name="git+https://github.com/owner/repo",
            commit="abc123"
        )

Signing behavior:
    - In CI (GitHub Actions, GitLab CI): Uses ambient OIDC credentials
    - Locally: Opens browser for OIDC authentication

Note:
    Signing requires optional dependencies: pip install baseline-mcp[attestation]
"""

# Git helpers
# Generation
from .generator import (
    BASELINE_PREDICATE_TYPE,
    build_unsigned_statement,
    generate_attestation_from_results,
)
from .git import (
    get_git_commit,
    get_git_ref,
)

# Predicate building
from .predicate import (
    build_assessment_predicate,
)

# Signing
from .signing import (
    ATTESTATION_AVAILABLE,
    SIGSTORE_API_VERSION,
    get_sigstore_api_version,
    is_attestation_available,
    sign_attestation,
)

__all__ = [
    # Git helpers
    "get_git_commit",
    "get_git_ref",
    # Predicate
    "build_assessment_predicate",
    # Signing
    "ATTESTATION_AVAILABLE",
    "SIGSTORE_API_VERSION",
    "is_attestation_available",
    "get_sigstore_api_version",
    "sign_attestation",
    # Generation
    "BASELINE_PREDICATE_TYPE",
    "build_unsigned_statement",
    "generate_attestation_from_results",
]
