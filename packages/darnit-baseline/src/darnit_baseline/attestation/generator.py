"""Attestation generation from audit results.

This module provides the main entry point for generating
in-toto attestations from OpenSSF Baseline audit results.
"""

import json
import os
from typing import TYPE_CHECKING, Any

from darnit.core.logging import get_logger

from .predicate import build_assessment_predicate
from .signing import ATTESTATION_AVAILABLE, sign_attestation

if TYPE_CHECKING:
    from darnit.core.models import AuditResult

logger = get_logger("attestation.generator")


# Predicate type for OpenSSF Baseline assessments
BASELINE_PREDICATE_TYPE = "https://openssf.org/baseline/assessment/v1"


def build_unsigned_statement(
    subject_name: str,
    commit: str,
    predicate_type: str,
    predicate: dict[str, Any]
) -> dict[str, Any]:
    """Build an unsigned in-toto statement.

    Args:
        subject_name: The subject name (e.g., git+https://github.com/owner/repo)
        commit: The git commit SHA
        predicate_type: The predicate type URI
        predicate: The attestation predicate

    Returns:
        Unsigned in-toto statement
    """
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": subject_name, "digest": {"gitCommit": commit}}],
        "predicateType": predicate_type,
        "predicate": predicate
    }


def generate_attestation_from_results(
    audit_result: "AuditResult",
    sign: bool = True,
    staging: bool = False,
    output_path: str | None = None,
    output_dir: str | None = None,
    storage_config: dict | None = None,
    attestation_store: Any = None,
) -> str:
    """Generate attestation from audit results.

    Args:
        audit_result: The audit result containing check results and metadata
        sign: Whether to sign with Sigstore (default True)
        staging: Use Sigstore staging environment for testing
        output_path: Explicit path for the attestation file (legacy)
        output_dir: Directory to save attestation (legacy; default: repo dir)
        attestation_store: Feature 033 pluggable AttestationStore. When
            provided, the bundle is written via ``store.write(bundle_id,
            bytes, content_type)`` instead of the legacy filesystem
            path. When None, ``output_path`` / ``output_dir`` control
            the on-disk write (unchanged pre-feature behavior).

    Returns:
        JSON string with attestation or error message
    """
    if not audit_result.commit:
        return json.dumps({
            "error": "Could not determine git commit. Is this a git repository?"
        }, indent=2)

    # Build the predicate
    predicate = build_assessment_predicate(
        owner=audit_result.owner,
        repo=audit_result.repo,
        commit=audit_result.commit,
        ref=audit_result.ref,
        level=audit_result.level,
        results=audit_result.all_results,
        project_config=audit_result.project_config,
        adapters_used=["builtin"]
    )

    predicate_type = BASELINE_PREDICATE_TYPE
    subject_name = f"git+https://github.com/{audit_result.owner}/{audit_result.repo}"

    if sign:
        if not ATTESTATION_AVAILABLE:
            unsigned = build_unsigned_statement(
                subject_name, audit_result.commit, predicate_type, predicate
            )
            return json.dumps({
                "error": "Signing requires optional dependencies. Install with: pip install baseline-mcp[attestation]",
                "unsigned_statement": unsigned
            }, indent=2)

        try:
            bundle = sign_attestation(
                predicate=predicate,
                predicate_type=predicate_type,
                subject_name=subject_name,
                commit=audit_result.commit,
                use_staging=staging
            )
            output = json.dumps(bundle, indent=2)
            unsigned = build_unsigned_statement(
                subject_name, audit_result.commit, predicate_type, predicate
            )
        except (RuntimeError, ValueError, TypeError, OSError) as e:
            unsigned = build_unsigned_statement(
                subject_name, audit_result.commit, predicate_type, predicate
            )
            return json.dumps({
                "error": f"Signing failed: {str(e)}",
                "hint": "In CI, ensure 'id-token: write' permission is set. Locally, ensure browser access for OIDC.",
                "unsigned_statement": unsigned
            }, indent=2)
    else:
        unsigned = build_unsigned_statement(
            subject_name, audit_result.commit, predicate_type, predicate
        )
        output = json.dumps(unsigned, indent=2)

    # Feature 033 T027: prefer the pluggable AttestationStore when
    # supplied. The legacy `output_path` / `output_dir` remain the
    # zero-config path so pre-feature callers keep the same on-disk
    # semantics without change.
    if attestation_store is not None:
        content_type = (
            "application/vnd.dev.sigstore.bundle+json"
            if sign
            else "application/vnd.in-toto+json"
        )
        bundle_id = f"{audit_result.repo}-baseline-attestation"
        try:
            attestation_store.write(
                bundle_id, output.encode("utf-8"), content_type
            )
            logger.info(f"Attestation written via store: bundle_id={bundle_id}")
        except Exception as e:  # noqa: BLE001
            return json.dumps({
                "error": f"AttestationStore write failed: {e}",
                "attestation": json.loads(output),
            }, indent=2)
    else:
        # Determine output file path (pre-feature filesystem path).
        if not output_path:
            extension = ".sigstore.json" if sign else ".intoto.json"
            filename = f"{audit_result.repo}-baseline-attestation{extension}"
            save_dir = output_dir if output_dir else audit_result.local_path
            output_path = os.path.join(save_dir, filename)

        try:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, 'w', encoding="utf-8") as f:
                f.write(output)
            logger.info(f"Attestation saved to: {output_path}")
        except OSError as e:
            return json.dumps({
                "error": f"Failed to write to {output_path}: {e}",
                "attestation": json.loads(output)
            }, indent=2)

    # Store via pluggable storage backend if configured
    if storage_config is not None:
        # TODO: repo_url is hardcoded to GitHub — will break for GitLab/Gitea/etc.
        # Open issue to track multi-forge support
        repo_url = f"https://github.com/{audit_result.owner}/{audit_result.repo}"
        try:
            from darnit.storage.backends import get_backend
            storage = get_backend(storage_config)
            storage_ref = storage.store_attestation(
                repo_url=repo_url,
                commit=audit_result.commit,
                attestation=unsigned,
            )
            logger.info(f"Attestation stored via backend: {storage_ref}")
        except Exception as e:
            logger.warning(f"Storage backend failed (file save succeeded): {e}")

    return f"✅ Attestation saved to: {output_path}\n\n{output}"


__all__ = [
    "BASELINE_PREDICATE_TYPE",
    "build_unsigned_statement",
    "generate_attestation_from_results",
]
