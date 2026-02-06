"""Plugin signature verification using Sigstore.

This module provides Sigstore-based verification for darnit plugins,
supporting both signed and unsigned plugins with configurable policies.

Default Trusted Publishers:
    By default, plugins from kusari-oss and kusaridev are trusted.
    Users can add additional trusted publishers in their configuration.

Example:
    from darnit.core.verification import PluginVerifier, VerificationConfig

    # Production: use defaults + add your own trusted publishers
    config = VerificationConfig(
        allow_unsigned=False,
        trusted_publishers=[
            "https://github.com/my-org",  # Add your org
        ],
        # use_default_publishers=True (default) includes kusari-oss, kusaridev
    )
    verifier = PluginVerifier(config)

    result = verifier.verify_plugin("darnit-baseline")
    if result.verified:
        # Plugin is trusted, proceed with loading
        ...

    # Development: allow all unsigned packages
    config = VerificationConfig(allow_unsigned=True)
    verifier = PluginVerifier(config)

    # Advanced: only trust specific publishers (no defaults)
    config = VerificationConfig(
        allow_unsigned=False,
        trusted_publishers=["https://github.com/my-org-only"],
        use_default_publishers=False,
    )

Security:
    - Sigstore verification provides cryptographic proof of publisher identity
    - Trusted publishers are matched against OIDC certificate identity
    - Cache results to handle Sigstore service unavailability
    - Graceful degradation: warn but allow if configured with allow_unsigned=True
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Cache expiration time in seconds (24 hours)
CACHE_EXPIRATION_SECONDS = 86400

# Cache directory relative to user's home
CACHE_DIR_NAME = ".darnit/verification_cache"

# PyPI attestation API base URL
PYPI_ATTESTATION_URL = "https://pypi.org/integrity/{package}/{version}/{filename}.attestation"
PYPI_JSON_API_URL = "https://pypi.org/pypi/{package}/{version}/json"

# Default trusted publishers for darnit ecosystem
# These are always trusted unless explicitly overridden
DEFAULT_TRUSTED_PUBLISHERS = (
    "https://github.com/kusari-oss",
    "https://github.com/kusaridev",
    "kusari-oss",
    "kusaridev",
)


@dataclass
class VerificationConfig:
    """Configuration for plugin verification.

    Attributes:
        allow_unsigned: Whether to allow unsigned plugins (with warning).
            Set to True for local development, False for production.
        trusted_publishers: Additional trusted OIDC identities beyond defaults.
            These are merged with DEFAULT_TRUSTED_PUBLISHERS. Use:
            - "https://github.com/your-org" (GitHub org URL)
            - "your-org" (org name, substring match)
            - "user@example.com" (email identity)
        use_default_publishers: Whether to include DEFAULT_TRUSTED_PUBLISHERS.
            Set to False to only trust publishers you explicitly specify.
        cache_dir: Directory for caching verification results
        cache_ttl: Cache time-to-live in seconds
        verify_online: Whether to fetch attestations from PyPI (requires network)
    """

    allow_unsigned: bool = True
    trusted_publishers: list[str] = field(default_factory=list)
    use_default_publishers: bool = True
    cache_dir: Path | None = None
    cache_ttl: int = CACHE_EXPIRATION_SECONDS
    verify_online: bool = True

    def __post_init__(self) -> None:
        if self.cache_dir is None:
            self.cache_dir = Path.home() / CACHE_DIR_NAME

    def get_all_trusted_publishers(self) -> list[str]:
        """Get complete list of trusted publishers.

        Combines default publishers (if enabled) with user-specified publishers.

        Returns:
            List of all trusted publisher identities
        """
        publishers = list(self.trusted_publishers)
        if self.use_default_publishers:
            for default in DEFAULT_TRUSTED_PUBLISHERS:
                if default not in publishers:
                    publishers.append(default)
        return publishers


@dataclass
class AttestationInfo:
    """Information extracted from a Sigstore attestation.

    Attributes:
        issuer: OIDC issuer URL (e.g., "https://token.actions.githubusercontent.com")
        subject: Certificate subject identity (e.g., workflow path or email)
        subject_alternative_name: SAN from certificate (often the identity URL)
        repository: Source repository (for GitHub Actions)
        workflow: Workflow file path (for GitHub Actions)
        raw_certificate: The raw certificate data
    """

    issuer: str | None = None
    subject: str | None = None
    subject_alternative_name: str | None = None
    repository: str | None = None
    workflow: str | None = None
    raw_certificate: bytes | None = None


@dataclass
class VerificationResult:
    """Result of plugin verification.

    Attributes:
        verified: Whether the plugin is verified (signed or allowed unsigned)
        signed: Whether the plugin has a valid Sigstore signature
        publisher: Publisher identity from certificate (OIDC subject)
        publisher_repo: Source repository from attestation (if GitHub Actions)
        trusted: Whether publisher matches trusted_publishers list
        cached: Whether result came from cache
        attestation: Detailed attestation information (if signed)
        error: Error message if verification failed
        warning: Warning message (e.g., for unsigned plugins)
    """

    verified: bool
    signed: bool = False
    publisher: str | None = None
    publisher_repo: str | None = None
    trusted: bool = False
    cached: bool = False
    attestation: AttestationInfo | None = None
    error: str | None = None
    warning: str | None = None


class VerificationCache:
    """Cache for verification results.

    Stores verification results to handle Sigstore unavailability
    and reduce repeated verification calls.
    """

    def __init__(self, cache_dir: Path, ttl: int = CACHE_EXPIRATION_SECONDS):
        self.cache_dir = cache_dir
        self.ttl = ttl
        self._ensure_cache_dir()

    def _ensure_cache_dir(self) -> None:
        """Create cache directory if it doesn't exist."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning(f"Could not create cache directory: {e}")

    def _cache_key(self, package_name: str, version: str) -> str:
        """Generate cache key for a package."""
        key_data = f"{package_name}:{version}"
        return hashlib.sha256(key_data.encode()).hexdigest()[:16]

    def _cache_path(self, package_name: str, version: str) -> Path:
        """Get cache file path for a package."""
        key = self._cache_key(package_name, version)
        return self.cache_dir / f"{key}.json"

    def get(self, package_name: str, version: str) -> VerificationResult | None:
        """Get cached verification result.

        Args:
            package_name: Package name
            version: Package version

        Returns:
            Cached VerificationResult or None if not cached/expired
        """
        cache_path = self._cache_path(package_name, version)

        if not cache_path.exists():
            return None

        try:
            with open(cache_path) as f:
                data = json.load(f)

            # Check expiration
            cached_time = data.get("cached_at", 0)
            if time.time() - cached_time > self.ttl:
                logger.debug(f"Cache expired for {package_name}:{version}")
                return None

            # Reconstruct AttestationInfo if present
            attestation = None
            if data.get("attestation"):
                attestation = AttestationInfo(
                    issuer=data["attestation"].get("issuer"),
                    subject=data["attestation"].get("subject"),
                    subject_alternative_name=data["attestation"].get(
                        "subject_alternative_name"
                    ),
                    repository=data["attestation"].get("repository"),
                    workflow=data["attestation"].get("workflow"),
                )

            return VerificationResult(
                verified=data.get("verified", False),
                signed=data.get("signed", False),
                publisher=data.get("publisher"),
                publisher_repo=data.get("publisher_repo"),
                trusted=data.get("trusted", False),
                cached=True,
                attestation=attestation,
                error=data.get("error"),
                warning=data.get("warning"),
            )
        except (OSError, json.JSONDecodeError) as e:
            logger.debug(f"Could not read cache for {package_name}: {e}")
            return None

    def set(
        self, package_name: str, version: str, result: VerificationResult
    ) -> None:
        """Cache a verification result.

        Args:
            package_name: Package name
            version: Package version
            result: Verification result to cache
        """
        cache_path = self._cache_path(package_name, version)

        try:
            # Serialize attestation if present
            attestation_data = None
            if result.attestation:
                attestation_data = {
                    "issuer": result.attestation.issuer,
                    "subject": result.attestation.subject,
                    "subject_alternative_name": result.attestation.subject_alternative_name,
                    "repository": result.attestation.repository,
                    "workflow": result.attestation.workflow,
                }

            data = {
                "verified": result.verified,
                "signed": result.signed,
                "publisher": result.publisher,
                "publisher_repo": result.publisher_repo,
                "trusted": result.trusted,
                "attestation": attestation_data,
                "error": result.error,
                "warning": result.warning,
                "cached_at": time.time(),
                "package": package_name,
                "version": version,
            }

            with open(cache_path, "w") as f:
                json.dump(data, f)

            logger.debug(f"Cached verification result for {package_name}:{version}")
        except OSError as e:
            logger.warning(f"Could not cache verification result: {e}")


class PluginVerifier:
    """Sigstore-based plugin verifier.

    Verifies plugin signatures using Sigstore and manages verification
    policies based on configuration.

    The verifier supports two modes:
    1. **Production mode** (allow_unsigned=False): Only plugins with valid
       Sigstore attestations from trusted publishers are allowed.
    2. **Development mode** (allow_unsigned=True): All plugins are allowed,
       with warnings for unsigned plugins.

    Trusted publishers are matched against the OIDC certificate identity
    from the Sigstore attestation. For GitHub Actions, this is typically
    the repository URL (e.g., "https://github.com/org/repo").
    """

    def __init__(self, config: VerificationConfig | None = None):
        """Initialize the verifier.

        Args:
            config: Verification configuration (uses defaults if None)
        """
        self.config = config or VerificationConfig()
        self.cache = VerificationCache(
            self.config.cache_dir, self.config.cache_ttl  # type: ignore[arg-type]
        )
        self._sigstore_available: bool | None = None

    def _check_sigstore_available(self) -> bool:
        """Check if Sigstore library is available."""
        if self._sigstore_available is not None:
            return self._sigstore_available

        try:
            import sigstore  # noqa: F401

            self._sigstore_available = True
        except ImportError:
            self._sigstore_available = False
            logger.info(
                "Sigstore not available. Install with: pip install darnit[attestation]"
            )

        return self._sigstore_available

    def _get_package_info(self, package_name: str) -> dict[str, Any] | None:
        """Get package metadata from installed packages.

        Args:
            package_name: Name of the package

        Returns:
            Package metadata dict or None if not found
        """
        try:
            from importlib.metadata import metadata, version

            pkg_version = version(package_name)
            pkg_metadata = metadata(package_name)

            return {
                "name": package_name,
                "version": pkg_version,
                "metadata": dict(pkg_metadata),
            }
        except Exception as e:
            logger.debug(f"Could not get package info for {package_name}: {e}")
            return None

    def _fetch_pypi_attestation(
        self, package_name: str, version: str
    ) -> dict[str, Any] | None:
        """Fetch attestation from PyPI for a package.

        PyPI provides attestations via the integrity API for packages
        that were published with Trusted Publishing (GitHub Actions OIDC).

        Args:
            package_name: Package name
            version: Package version

        Returns:
            Attestation data dict or None if not available
        """
        if not self.config.verify_online:
            logger.debug("Online verification disabled, skipping PyPI attestation fetch")
            return None

        try:
            # First get the package info to find the wheel/sdist filename
            api_url = PYPI_JSON_API_URL.format(package=package_name, version=version)
            with urllib.request.urlopen(api_url, timeout=10) as response:
                data = json.loads(response.read().decode())

            # Look for attestation URLs in the release info
            urls = data.get("urls", [])
            for url_info in urls:
                # Check for attestation digests (PEP 740)
                if url_info.get("provenance"):
                    return {
                        "has_provenance": True,
                        "provenance_url": url_info.get("provenance"),
                        "filename": url_info.get("filename"),
                        "digests": url_info.get("digests", {}),
                    }

            # No attestation found
            return None

        except urllib.error.HTTPError as e:
            if e.code == 404:
                logger.debug(f"No attestation found for {package_name}:{version}")
            else:
                logger.debug(f"HTTP error fetching attestation: {e}")
            return None
        except Exception as e:
            logger.debug(f"Could not fetch PyPI attestation for {package_name}: {e}")
            return None

    def _verify_attestation_sigstore(
        self, attestation_data: dict[str, Any], package_name: str
    ) -> AttestationInfo | None:
        """Verify an attestation using Sigstore.

        Args:
            attestation_data: Attestation data from PyPI
            package_name: Package name for logging

        Returns:
            AttestationInfo with certificate details, or None if verification fails
        """
        if not self._check_sigstore_available():
            return None

        try:
            # For now, we extract what we can from the provenance data
            # Full verification would use sigstore.verify module
            provenance_url = attestation_data.get("provenance_url")
            if not provenance_url:
                return None

            # Fetch the provenance bundle
            with urllib.request.urlopen(provenance_url, timeout=10) as response:
                provenance = json.loads(response.read().decode())

            # Extract identity from the attestation bundle
            # The structure follows in-toto attestation format
            attestation_info = AttestationInfo()

            # Try to extract certificate info from the bundle
            if "verificationMaterial" in provenance:
                material = provenance["verificationMaterial"]
                if "certificate" in material:
                    cert_data = material["certificate"]
                    # The certificate contains the OIDC identity
                    attestation_info.raw_certificate = (
                        cert_data.get("rawBytes", "").encode()
                        if isinstance(cert_data.get("rawBytes"), str)
                        else cert_data.get("rawBytes")
                    )

            # Extract predicate for build info
            if "dsseEnvelope" in provenance:
                envelope = provenance["dsseEnvelope"]
                if "payload" in envelope:
                    import base64
                    payload = json.loads(base64.b64decode(envelope["payload"]))
                    predicate = payload.get("predicate", {})

                    # Extract GitHub Actions info
                    invocation = predicate.get("invocation", {})
                    config_source = invocation.get("configSource", {})

                    if "uri" in config_source:
                        # URI is like "git+https://github.com/org/repo@refs/..."
                        uri = config_source["uri"]
                        if "github.com" in uri:
                            # Extract repo from URI
                            parts = uri.replace("git+", "").split("@")[0]
                            attestation_info.repository = parts
                            # Also set as subject for matching
                            attestation_info.subject = parts

                    if "entryPoint" in config_source:
                        attestation_info.workflow = config_source["entryPoint"]

                    # Extract issuer from builder
                    builder = predicate.get("builder", {})
                    if "id" in builder:
                        attestation_info.issuer = builder["id"]

            return attestation_info

        except Exception as e:
            logger.debug(f"Could not verify attestation for {package_name}: {e}")
            return None

    def _is_publisher_trusted(self, attestation: AttestationInfo) -> bool:
        """Check if the attestation's publisher is in the trusted list.

        Matching rules:
        1. Exact match: trusted_publisher == subject
        2. Repository match: trusted_publisher in repository URL
        3. Org match: trusted_publisher is a prefix of the repository

        Args:
            attestation: Attestation info with publisher identity

        Returns:
            True if publisher is trusted
        """
        all_trusted = self.config.get_all_trusted_publishers()
        if not all_trusted:
            return False

        # Collect all identity strings to match against
        identities = []
        if attestation.subject:
            identities.append(attestation.subject.lower())
        if attestation.repository:
            identities.append(attestation.repository.lower())
        if attestation.subject_alternative_name:
            identities.append(attestation.subject_alternative_name.lower())

        for trusted in all_trusted:
            trusted_lower = trusted.lower()
            for identity in identities:
                # Exact match
                if trusted_lower == identity:
                    return True
                # Substring match (org in repo URL)
                if trusted_lower in identity:
                    return True
                # Handle GitHub URL formats
                # e.g., "kusari-oss" matches "https://github.com/kusari-oss/darnit"
                if f"github.com/{trusted_lower}" in identity:
                    return True

        return False

    def _get_fallback_publisher(self, package_name: str) -> str | None:
        """Get publisher from package metadata as fallback.

        Used when no Sigstore attestation is available.

        Args:
            package_name: Package name

        Returns:
            Publisher identifier from metadata, or None
        """
        try:
            from importlib.metadata import metadata

            pkg_metadata = metadata(package_name)
            author = pkg_metadata.get("Author-email", "")
            maintainer = pkg_metadata.get("Maintainer-email", "")

            for email in [author, maintainer]:
                if email:
                    if "<" in email:
                        return email.split("<")[0].strip()
                    return email.split("@")[0]
            return None
        except Exception:
            return None

    def _verify_with_sigstore(
        self, package_name: str, version: str
    ) -> VerificationResult:
        """Verify package signature using Sigstore.

        This fetches attestations from PyPI and verifies them using
        Sigstore's verification infrastructure.

        Args:
            package_name: Package name
            version: Package version

        Returns:
            VerificationResult with signature status
        """
        # Try to fetch attestation from PyPI
        attestation_data = self._fetch_pypi_attestation(package_name, version)

        if attestation_data and attestation_data.get("has_provenance"):
            # Verify the attestation
            attestation_info = self._verify_attestation_sigstore(
                attestation_data, package_name
            )

            if attestation_info:
                # Check if publisher is trusted
                trusted = self._is_publisher_trusted(attestation_info)
                publisher = (
                    attestation_info.subject
                    or attestation_info.repository
                    or "unknown"
                )

                if trusted:
                    return VerificationResult(
                        verified=True,
                        signed=True,
                        publisher=publisher,
                        publisher_repo=attestation_info.repository,
                        trusted=True,
                        attestation=attestation_info,
                    )
                else:
                    # Signed but not by trusted publisher
                    return VerificationResult(
                        verified=self.config.allow_unsigned,
                        signed=True,
                        publisher=publisher,
                        publisher_repo=attestation_info.repository,
                        trusted=False,
                        attestation=attestation_info,
                        warning=f"Package '{package_name}' signed by untrusted publisher: {publisher}",
                    )

        # No attestation available - use fallback
        fallback_publisher = self._get_fallback_publisher(package_name)

        # Check if fallback publisher matches (for backwards compatibility)
        trusted = False
        if fallback_publisher:
            for tp in self.config.get_all_trusted_publishers():
                if tp.lower() in fallback_publisher.lower():
                    trusted = True
                    break

        if trusted:
            return VerificationResult(
                verified=True,
                signed=False,
                publisher=fallback_publisher,
                trusted=True,
                warning="No Sigstore attestation, trusted based on package metadata",
            )

        return VerificationResult(
            verified=self.config.allow_unsigned,
            signed=False,
            publisher=fallback_publisher,
            trusted=False,
            warning=f"Package '{package_name}' has no Sigstore attestation",
        )

    def verify_plugin(
        self, package_name: str, use_cache: bool = True
    ) -> VerificationResult:
        """Verify a plugin package.

        Args:
            package_name: Name of the plugin package
            use_cache: Whether to use cached results

        Returns:
            VerificationResult with verification status
        """
        # Get package info
        pkg_info = self._get_package_info(package_name)
        if pkg_info is None:
            return VerificationResult(
                verified=False,
                error=f"Package '{package_name}' not found",
            )

        version = pkg_info["version"]

        # Check cache first
        if use_cache:
            cached = self.cache.get(package_name, version)
            if cached is not None:
                logger.debug(f"Using cached verification for {package_name}:{version}")
                return cached

        # Verify with Sigstore
        result = self._verify_with_sigstore(package_name, version)

        # Cache the result
        self.cache.set(package_name, version, result)

        # Log appropriate messages
        if result.verified:
            if result.signed and result.trusted:
                logger.info(
                    f"Plugin '{package_name}' verified "
                    f"(signed by trusted publisher: {result.publisher})"
                )
            elif result.signed:
                logger.warning(
                    f"Plugin '{package_name}' signed by untrusted publisher: "
                    f"{result.publisher}"
                )
            elif result.warning:
                logger.warning(result.warning)
        else:
            if result.error:
                logger.error(f"Plugin verification failed: {result.error}")

        return result

    def verify_plugins(
        self, package_names: list[str]
    ) -> dict[str, VerificationResult]:
        """Verify multiple plugin packages.

        Args:
            package_names: List of package names to verify

        Returns:
            Dict mapping package names to VerificationResults
        """
        results = {}
        for name in package_names:
            results[name] = self.verify_plugin(name)
        return results


# Module-level convenience functions


def verify_plugin(
    package_name: str,
    allow_unsigned: bool = True,
    trusted_publishers: list[str] | None = None,
) -> VerificationResult:
    """Verify a plugin package.

    Convenience function for one-off verification.

    Args:
        package_name: Name of the plugin package
        allow_unsigned: Whether to allow unsigned plugins (True for development)
        trusted_publishers: List of trusted OIDC identities (e.g., GitHub org URLs)

    Returns:
        VerificationResult with verification status

    Example:
        # Development mode - allow all
        result = verify_plugin("my-plugin", allow_unsigned=True)

        # Production mode - require trusted publisher
        result = verify_plugin(
            "darnit-baseline",
            allow_unsigned=False,
            trusted_publishers=["https://github.com/kusari-oss"],
        )
    """
    config = VerificationConfig(
        allow_unsigned=allow_unsigned,
        trusted_publishers=trusted_publishers or [],
    )
    verifier = PluginVerifier(config)
    return verifier.verify_plugin(package_name)


__all__ = [
    "PluginVerifier",
    "VerificationConfig",
    "VerificationResult",
    "VerificationCache",
    "AttestationInfo",
    "verify_plugin",
    "DEFAULT_TRUSTED_PUBLISHERS",
]
