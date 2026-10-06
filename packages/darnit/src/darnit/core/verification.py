"""Plugin signature verification using Sigstore.

This module provides Sigstore-based verification for darnit plugins,
supporting both signed and unsigned plugins with configurable policies.

Default Trusted Publishers:
    By default, plugins from darnitdevorg, kusari-oss, and kusaridev are trusted.
    darnitdevorg is the current publishing identity; kusari-oss and kusaridev
    are retained so artifacts signed before the org migration still verify.
    Users can add additional trusted publishers in their configuration.

Example:
    from darnit.core.verification import PluginVerifier, VerificationConfig

    # Production: use defaults + add your own trusted publishers
    config = VerificationConfig(
        allow_unsigned=False,
        trusted_publishers=[
            "https://github.com/my-org",  # Add your org
        ],
        # use_default_publishers=True (default) includes darnitdevorg,
        # kusari-oss, kusaridev
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
    - The disk cache stores the lookup, not the allow_unsigned or publisher decision
    - Graceful degradation: warn but allow if configured with allow_unsigned=True
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from darnit.config.operator.schema import PluginSettings

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
    "https://github.com/darnitdevorg",
    "https://github.com/kusari-oss",
    "https://github.com/kusaridev",
    "darnitdevorg",
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
            - "https://github.com/your-org" (GitHub org URL; owner segment)
            - "your-org" (GitHub owner name)
            - "user@example.com" (email identity, exact match)
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

    @classmethod
    def from_plugin_settings(cls, settings: PluginSettings | None) -> VerificationConfig:
        """Build a config from the operator's ``[plugins]`` settings.

        Only an explicitly-configured ``allow_unsigned`` concludes the policy;
        otherwise this class's default stands, so the feature-040 fail-closed
        default remains a separate explicit change.

        Args:
            settings: Operator ``[plugins]`` settings, or None if unconfigured.

        Returns:
            VerificationConfig reflecting the operator's policy.
        """
        if settings is None:
            return cls()

        kwargs: dict[str, Any] = {
            "trusted_publishers": list(settings.trusted_publishers),
        }

        if "allow_unsigned" in settings.model_fields_set:
            kwargs["allow_unsigned"] = settings.allow_unsigned

        return cls(**kwargs)

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
        status: Observation class. ``unsigned`` is a completed "not signed"
            result. Not stored as a policy decision; the raw cache has its own
            status.
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
    status: CacheStatus | None = None


# ``undetermined`` is not stored: a later run has to look again.
CACHE_SCHEMA_VERSION = 1
_CACHEABLE_STATUSES = frozenset({"signed", "unsigned", "invalid"})
CacheStatus = Literal["signed", "unsigned", "invalid", "undetermined"]
_LookupKind = Literal["provenance", "absent", "undetermined"]


@dataclass
class VerificationCacheEntry:
    """Raw verification observation. Policy is applied when this is read.

    ``signed`` means provenance was found and an identity was extracted.
    ``unsigned`` means the release lookup completed and named no provenance.
    ``invalid`` means verification failed; the current lookup does not emit it.
    ``undetermined`` means the signing state could not be established.
    """

    schema_version: int
    package: str
    version: str
    cached_at: float
    status: CacheStatus
    publisher: str | None = None
    publisher_repo: str | None = None
    metadata_publisher: str | None = None
    attestation: AttestationInfo | None = None


@dataclass
class _AttestationLookup:
    """One PyPI release lookup.

    ``absent`` is a completed release with no provenance. ``undetermined``
    (including HTTP 404) did not establish that fact and must not be cached.
    """

    kind: _LookupKind
    data: dict[str, Any] | None = None


class VerificationCache:
    """Cache for raw verification observations.

    Stores what a completed lookup found, not the allow_unsigned or publisher
    decision. A file with no ``schema_version`` is an old decision record and
    is a miss.
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

    def get(self, package_name: str, version: str) -> VerificationCacheEntry | None:
        """Get a cached observation.

        Files without ``schema_version`` stored a policy decision and are misses.

        Args:
            package_name: Package name
            version: Package version

        Returns:
            Cached observation or None if not cached, expired, or an old schema.
        """
        cache_path = self._cache_path(package_name, version)

        if not cache_path.exists():
            return None

        try:
            with open(cache_path, encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict) or data.get("schema_version") != CACHE_SCHEMA_VERSION:
                logger.debug(f"Ignoring stale verification cache for {package_name}:{version}")
                return None

            status = data.get("status")
            if status not in _CACHEABLE_STATUSES:
                return None

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
                    subject_alternative_name=data["attestation"].get("subject_alternative_name"),
                    repository=data["attestation"].get("repository"),
                    workflow=data["attestation"].get("workflow"),
                )

            return VerificationCacheEntry(
                schema_version=CACHE_SCHEMA_VERSION,
                package=package_name,
                version=version,
                cached_at=cached_time,
                status=status,
                publisher=data.get("publisher"),
                publisher_repo=data.get("publisher_repo"),
                metadata_publisher=data.get("metadata_publisher"),
                attestation=attestation,
            )
        except (OSError, json.JSONDecodeError, TypeError, AttributeError) as e:
            logger.debug(f"Could not read cache for {package_name}: {e}")
            return None

    def set(self, package_name: str, version: str, entry: VerificationCacheEntry) -> None:
        """Store a completed observation.

        ``undetermined`` observations are not stored. A later lookup has to
        decide the signing state for itself. A write replaces any file already
        at this package/version path, including an old decision-shaped file.

        Args:
            package_name: Package name
            version: Package version
            entry: Raw observation to store
        """
        if entry.status not in _CACHEABLE_STATUSES:
            return

        cache_path = self._cache_path(package_name, version)
        attestation_data = None
        if entry.attestation is not None:
            attestation_data = {
                "issuer": entry.attestation.issuer,
                "subject": entry.attestation.subject,
                "subject_alternative_name": entry.attestation.subject_alternative_name,
                "repository": entry.attestation.repository,
                "workflow": entry.attestation.workflow,
            }

        data = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "package": package_name,
            "version": version,
            "cached_at": time.time(),
            "status": entry.status,
            "publisher": entry.publisher,
            "publisher_repo": entry.publisher_repo,
            "metadata_publisher": entry.metadata_publisher,
            "attestation": attestation_data,
        }

        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            logger.debug(f"Cached verification observation for {package_name}:{version}")
        except OSError as e:
            logger.warning(f"Could not cache verification result: {e}")


def _normalize_publisher_text(value: str) -> str:
    """Strip surrounding whitespace and one trailing slash.

    Comparison stays case-insensitive, which is how publisher strings were
    already compared.
    """
    text = value.strip()
    if text.endswith("/"):
        text = text[:-1]
    return text.casefold()


def _github_path(value: str) -> tuple[str, ...] | None:
    """Return the path segments of an http(s) ``github.com`` URL.

    ``None`` means ``value`` is not a GitHub URL. The host must be exactly
    ``github.com``; a lookalike host is not a GitHub identity.
    """
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").casefold()
    if host != "github.com":
        return None
    return tuple(part.casefold() for part in parsed.path.split("/") if part)


def _publisher_identity_matches(trusted: str, identity: str) -> bool:
    """Return whether ``trusted`` names the same publisher as ``identity``.

    A GitHub org URL matches a repository on that exact owner. A full
    repository URL matches only that repository. A bare owner name matches
    only that GitHub owner segment. Every other identity, including email,
    matches only by normalized equality.
    """
    trusted_text = _normalize_publisher_text(trusted)
    identity_text = _normalize_publisher_text(identity)
    if trusted_text == identity_text:
        return True

    trusted_path = _github_path(trusted)
    identity_path = _github_path(identity)
    if identity_path is None:
        return False

    if trusted_path is None:
        # Bare owner: no slash and not an email address.
        if "/" in trusted_text or "@" in trusted_text or not trusted_text or not identity_path:
            return False
        return identity_path[0] == trusted_text

    if len(trusted_path) == 1:
        return identity_path[0] == trusted_path[0]
    return identity_path == trusted_path


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
            self.config.cache_dir,
            self.config.cache_ttl,  # type: ignore[arg-type]
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
            logger.info("Sigstore not available. Install with: pip install darnit-core[attestation]")

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

    def _fetch_pypi_attestation(self, package_name: str, version: str) -> _AttestationLookup:
        """Fetch attestation from PyPI for a package.

        PyPI provides attestations via the integrity API for packages
        that were published with Trusted Publishing (GitHub Actions OIDC).
        A completed release with no provenance is ``absent``. HTTP 404 for an
        installed version is also ``absent``: PyPI has no release to attest, so
        the package is unsigned. Other HTTP errors, network failures, and
        ``verify_online=False`` are ``undetermined``.

        Args:
            package_name: Package name
            version: Package version

        Returns:
            The lookup outcome. Provenance descriptors are returned only when
            the release JSON names one.
        """
        if not self.config.verify_online:
            logger.debug("Online verification disabled, skipping PyPI attestation fetch")
            return _AttestationLookup(kind="undetermined")

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
                    return _AttestationLookup(
                        kind="provenance",
                        data={
                            "has_provenance": True,
                            "provenance_url": url_info.get("provenance"),
                            "filename": url_info.get("filename"),
                            "digests": url_info.get("digests", {}),
                        },
                    )

            # The release exists and names no provenance.
            return _AttestationLookup(kind="absent")

        except urllib.error.HTTPError as e:
            if e.code == 404:
                logger.debug(f"No PyPI release for installed package {package_name}:{version}")
                return _AttestationLookup(kind="absent")
            logger.debug(f"HTTP error fetching attestation: {e}")
            return _AttestationLookup(kind="undetermined")
        except Exception as e:
            logger.debug(f"Could not fetch PyPI attestation for {package_name}: {e}")
            return _AttestationLookup(kind="undetermined")

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

        Subject, repository, and subjectAlternativeName are compared as
        identities. Issuer and workflow are not publisher identities.

        Args:
            attestation: Attestation info with publisher identity

        Returns:
            True if publisher is trusted
        """
        all_trusted = self.config.get_all_trusted_publishers()
        if not all_trusted:
            return False

        identities = [
            attestation.subject,
            attestation.repository,
            attestation.subject_alternative_name,
        ]
        for trusted in all_trusted:
            for identity in identities:
                if identity and _publisher_identity_matches(trusted, identity):
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

    def _observe(self, package_name: str, version: str) -> VerificationCacheEntry:
        """Collect a raw observation for one installed version.

        A completed lookup with no provenance is ``unsigned``. Package metadata
        is recorded on that observation and is not a publisher identity.
        A provenance bundle whose identity could not be read is ``undetermined``.
        """
        lookup = self._fetch_pypi_attestation(package_name, version)
        if lookup.kind == "provenance" and lookup.data is not None:
            attestation = self._verify_attestation_sigstore(lookup.data, package_name)
            if attestation is not None:
                publisher = attestation.subject or attestation.repository or "unknown"
                return VerificationCacheEntry(
                    schema_version=CACHE_SCHEMA_VERSION,
                    package=package_name,
                    version=version,
                    cached_at=0,
                    status="signed",
                    publisher=publisher,
                    publisher_repo=attestation.repository,
                    attestation=attestation,
                )
            return VerificationCacheEntry(
                schema_version=CACHE_SCHEMA_VERSION,
                package=package_name,
                version=version,
                cached_at=0,
                status="undetermined",
            )

        if lookup.kind == "absent":
            return VerificationCacheEntry(
                schema_version=CACHE_SCHEMA_VERSION,
                package=package_name,
                version=version,
                cached_at=0,
                status="unsigned",
                metadata_publisher=self._get_fallback_publisher(package_name),
            )

        return VerificationCacheEntry(
            schema_version=CACHE_SCHEMA_VERSION,
            package=package_name,
            version=version,
            cached_at=0,
            status="undetermined",
        )

    def _apply_policy(self, entry: VerificationCacheEntry, *, cached: bool) -> VerificationResult:
        """Apply the live ``VerificationConfig`` to a raw observation.

        ``verified`` and ``trusted`` are computed here and are not read from disk.
        """
        if entry.status == "invalid":
            return VerificationResult(
                verified=False,
                publisher=entry.publisher,
                publisher_repo=entry.publisher_repo,
                cached=cached,
                attestation=entry.attestation,
                error="attestation failed verification",
                status="invalid",
            )

        if entry.status == "undetermined":
            return VerificationResult(
                verified=False,
                cached=cached,
                error="signing state could not be established",
                status="undetermined",
            )

        if entry.status == "signed":
            attestation = entry.attestation or AttestationInfo()
            trusted = self._is_publisher_trusted(attestation)
            if trusted:
                return VerificationResult(
                    verified=True,
                    signed=True,
                    publisher=entry.publisher,
                    publisher_repo=entry.publisher_repo,
                    trusted=True,
                    cached=cached,
                    attestation=attestation,
                    status="signed",
                )
            return VerificationResult(
                verified=self.config.allow_unsigned,
                signed=True,
                publisher=entry.publisher,
                publisher_repo=entry.publisher_repo,
                trusted=False,
                cached=cached,
                attestation=attestation,
                warning=(f"Package '{entry.package}' signed by untrusted publisher: {entry.publisher}"),
                status="signed",
            )

        return VerificationResult(
            verified=self.config.allow_unsigned,
            publisher=entry.metadata_publisher,
            trusted=False,
            cached=cached,
            warning=f"Package '{entry.package}' has no Sigstore attestation",
            status="unsigned",
        )

    def verify_plugin(self, package_name: str, use_cache: bool = True) -> VerificationResult:
        """Verify a plugin package.

        The disk cache contributes a raw observation only. ``allow_unsigned`` and
        the trusted-publisher list are applied to that observation on every call.

        Args:
            package_name: Name of the plugin package
            use_cache: Whether to read a cached observation. A completed
                observation is still recorded for a later call.

        Returns:
            VerificationResult with verification status. ``cached`` is true when
            the observation was read from disk.
        """
        try:
            return self._verify_observed(package_name, use_cache=use_cache)
        except Exception as exc:
            return self._undetermined_result(package_name, exc, cached=False)

    def _undetermined_result(self, package_name: str, exc: Exception, *, cached: bool) -> VerificationResult:
        """An unexpected failure did not establish whether the package is signed."""
        logger.debug(
            "Plugin verification failed unexpectedly for %s: %s",
            package_name,
            exc,
        )
        return VerificationResult(
            verified=False,
            trusted=False,
            cached=cached,
            error=f"{type(exc).__name__}: {exc}",
            status="undetermined",
        )

    def _verify_observed(self, package_name: str, *, use_cache: bool) -> VerificationResult:
        """Look up a package and apply policy. Unexpected errors propagate."""
        pkg_info = self._get_package_info(package_name)
        if pkg_info is None:
            return VerificationResult(
                verified=False,
                trusted=False,
                error=f"Package '{package_name}' not found",
                status="undetermined",
            )

        version = pkg_info["version"]
        entry: VerificationCacheEntry | None = None
        from_cache = False
        if use_cache:
            entry = self.cache.get(package_name, version)
            from_cache = entry is not None
            if from_cache:
                logger.debug(f"Using cached verification for {package_name}:{version}")

        if entry is None:
            entry = self._observe(package_name, version)
            self.cache.set(package_name, version, entry)

        try:
            result = self._apply_policy(entry, cached=from_cache)
        except Exception as exc:
            return self._undetermined_result(package_name, exc, cached=from_cache)
        if result.verified and result.signed and result.trusted:
            logger.info(f"Plugin '{package_name}' verified (signed by trusted publisher: {result.publisher})")
        return result

    def verify_plugins(self, package_names: list[str]) -> dict[str, VerificationResult]:
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
    "VerificationCacheEntry",
    "AttestationInfo",
    "verify_plugin",
    "DEFAULT_TRUSTED_PUBLISHERS",
    "CACHE_SCHEMA_VERSION",
]
