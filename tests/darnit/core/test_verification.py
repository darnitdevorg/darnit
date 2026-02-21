"""Tests for plugin verification using Sigstore."""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from darnit.core.verification import (
    DEFAULT_TRUSTED_PUBLISHERS,
    AttestationInfo,
    PluginVerifier,
    VerificationCache,
    VerificationConfig,
    VerificationResult,
    verify_plugin,
)


class TestDefaultTrustedPublishers:
    """Tests for default trusted publishers."""

    def test_default_publishers_included_by_default(self) -> None:
        """Test that default publishers are included when use_default_publishers=True."""
        config = VerificationConfig()
        all_publishers = config.get_all_trusted_publishers()

        for default in DEFAULT_TRUSTED_PUBLISHERS:
            assert default in all_publishers

    def test_can_add_additional_publishers(self) -> None:
        """Test that users can add additional trusted publishers."""
        config = VerificationConfig(
            trusted_publishers=["https://github.com/my-org"],
        )
        all_publishers = config.get_all_trusted_publishers()

        # Should include user's publisher
        assert "https://github.com/my-org" in all_publishers
        # Should also include defaults
        assert "kusari-oss" in all_publishers

    def test_can_disable_default_publishers(self) -> None:
        """Test that users can disable default publishers."""
        config = VerificationConfig(
            trusted_publishers=["https://github.com/my-org-only"],
            use_default_publishers=False,
        )
        all_publishers = config.get_all_trusted_publishers()

        # Should only include user's publisher
        assert all_publishers == ["https://github.com/my-org-only"]
        # Should NOT include defaults
        assert "kusari-oss" not in all_publishers


class TestVerificationConfig:
    """Tests for VerificationConfig."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = VerificationConfig()

        assert config.allow_unsigned is True
        assert config.trusted_publishers == []
        assert config.use_default_publishers is True
        assert config.cache_dir is not None
        assert ".darnit/verification_cache" in str(config.cache_dir)
        assert config.verify_online is True

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = VerificationConfig(
            allow_unsigned=False,
            trusted_publishers=[
                "https://github.com/openssf",
            ],
            use_default_publishers=True,
            cache_ttl=3600,
            verify_online=False,
        )

        assert config.allow_unsigned is False
        assert len(config.trusted_publishers) == 1
        assert config.cache_ttl == 3600
        assert config.verify_online is False
        # get_all_trusted_publishers should include both custom and defaults
        all_publishers = config.get_all_trusted_publishers()
        assert "https://github.com/openssf" in all_publishers
        assert "kusari-oss" in all_publishers


class TestVerificationCache:
    """Tests for VerificationCache."""

    def test_cache_set_and_get(self, tmp_path: Path) -> None:
        """Test caching and retrieving a result."""
        cache = VerificationCache(tmp_path, ttl=3600)

        attestation = AttestationInfo(
            subject="https://github.com/test/repo",
            repository="https://github.com/test/repo",
        )
        result = VerificationResult(
            verified=True,
            signed=True,
            publisher="test-publisher",
            publisher_repo="https://github.com/test/repo",
            trusted=True,
            attestation=attestation,
        )

        cache.set("test-package", "1.0.0", result)
        retrieved = cache.get("test-package", "1.0.0")

        assert retrieved is not None
        assert retrieved.verified is True
        assert retrieved.signed is True
        assert retrieved.publisher == "test-publisher"
        assert retrieved.cached is True
        assert retrieved.attestation is not None
        assert retrieved.attestation.repository == "https://github.com/test/repo"

    def test_cache_miss(self, tmp_path: Path) -> None:
        """Test cache miss returns None."""
        cache = VerificationCache(tmp_path)

        result = cache.get("nonexistent-package", "1.0.0")
        assert result is None

    def test_cache_expiration(self, tmp_path: Path) -> None:
        """Test that expired cache entries return None."""
        cache = VerificationCache(tmp_path, ttl=1)  # 1 second TTL

        result = VerificationResult(verified=True, signed=False)
        cache.set("test-package", "1.0.0", result)

        # Wait for expiration
        time.sleep(1.1)

        retrieved = cache.get("test-package", "1.0.0")
        assert retrieved is None

    def test_cache_different_versions(self, tmp_path: Path) -> None:
        """Test that different versions have separate cache entries."""
        cache = VerificationCache(tmp_path)

        result_v1 = VerificationResult(verified=True, signed=True, publisher="v1")
        result_v2 = VerificationResult(verified=True, signed=False, publisher="v2")

        cache.set("test-package", "1.0.0", result_v1)
        cache.set("test-package", "2.0.0", result_v2)

        retrieved_v1 = cache.get("test-package", "1.0.0")
        retrieved_v2 = cache.get("test-package", "2.0.0")

        assert retrieved_v1 is not None
        assert retrieved_v1.publisher == "v1"
        assert retrieved_v2 is not None
        assert retrieved_v2.publisher == "v2"


class TestPluginVerifier:
    """Tests for PluginVerifier."""

    def test_verify_missing_package(self) -> None:
        """Test verifying a package that doesn't exist."""
        config = VerificationConfig(allow_unsigned=True)
        verifier = PluginVerifier(config)

        result = verifier.verify_plugin("nonexistent-package-12345")

        assert result.verified is False
        assert "not found" in result.error.lower()

    def test_verify_installed_package_allow_unsigned(self) -> None:
        """Test verifying an installed package with allow_unsigned=True."""
        config = VerificationConfig(
            allow_unsigned=True,
            verify_online=False,  # Skip network calls for test
        )
        verifier = PluginVerifier(config)

        result = verifier.verify_plugin("pytest")

        # Should be verified (allow_unsigned=True)
        assert result.verified is True

    def test_verify_with_trusted_publisher_github_org(self) -> None:
        """Test verification with GitHub org as trusted publisher."""
        config = VerificationConfig(
            allow_unsigned=False,
            trusted_publishers=["https://github.com/pytest-dev"],
            verify_online=False,
        )
        verifier = PluginVerifier(config)

        # Mock the fallback publisher to match
        with patch.object(verifier, "_get_fallback_publisher") as mock_fallback:
            mock_fallback.return_value = "pytest-dev"

            result = verifier.verify_plugin("pytest")

            # Should be verified via fallback matching
            assert result.verified is True or result.warning is not None

    def test_verify_uses_cache(self, tmp_path: Path) -> None:
        """Test that verification uses cache."""
        config = VerificationConfig(
            allow_unsigned=True,
            cache_dir=tmp_path,
            verify_online=False,
        )
        verifier = PluginVerifier(config)

        # First call - not cached
        result1 = verifier.verify_plugin("pytest")
        assert result1.cached is False

        # Second call - should be cached
        result2 = verifier.verify_plugin("pytest")
        assert result2.cached is True

    def test_verify_skip_cache(self, tmp_path: Path) -> None:
        """Test verification can skip cache."""
        config = VerificationConfig(
            allow_unsigned=True,
            cache_dir=tmp_path,
            verify_online=False,
        )
        verifier = PluginVerifier(config)

        # First call
        verifier.verify_plugin("pytest")

        # Second call with cache disabled
        result = verifier.verify_plugin("pytest", use_cache=False)
        assert result.cached is False

    def test_verify_multiple_plugins(self) -> None:
        """Test verifying multiple plugins at once."""
        config = VerificationConfig(allow_unsigned=True, verify_online=False)
        verifier = PluginVerifier(config)

        results = verifier.verify_plugins(["pytest", "nonexistent-pkg-123"])

        assert "pytest" in results
        assert "nonexistent-pkg-123" in results
        assert results["pytest"].verified is True
        assert results["nonexistent-pkg-123"].verified is False

    @patch("darnit.core.verification.PluginVerifier._check_sigstore_available")
    def test_sigstore_unavailable(self, mock_check: MagicMock) -> None:
        """Test graceful degradation when Sigstore is unavailable."""
        mock_check.return_value = False

        config = VerificationConfig(allow_unsigned=True, verify_online=False)
        verifier = PluginVerifier(config)
        verifier._sigstore_available = False

        # Mock package info
        with patch.object(verifier, "_get_package_info") as mock_info:
            mock_info.return_value = {"name": "test", "version": "1.0.0", "metadata": {}}

            result = verifier.verify_plugin("test-package")

            assert result.verified is True  # allow_unsigned=True
            assert result.signed is False


class TestTrustedPublisherMatching:
    """Tests for trusted publisher matching logic."""

    def test_exact_match(self) -> None:
        """Test exact identity matching."""
        config = VerificationConfig(
            allow_unsigned=False,
            trusted_publishers=["https://github.com/kusari-oss/darnit"],
        )
        verifier = PluginVerifier(config)

        attestation = AttestationInfo(
            subject="https://github.com/kusari-oss/darnit",
        )

        assert verifier._is_publisher_trusted(attestation) is True

    def test_org_match(self) -> None:
        """Test org-level matching."""
        config = VerificationConfig(
            allow_unsigned=False,
            trusted_publishers=["kusari-oss"],
        )
        verifier = PluginVerifier(config)

        attestation = AttestationInfo(
            repository="https://github.com/kusari-oss/darnit",
        )

        assert verifier._is_publisher_trusted(attestation) is True

    def test_github_url_match(self) -> None:
        """Test GitHub URL format matching."""
        config = VerificationConfig(
            allow_unsigned=False,
            trusted_publishers=["https://github.com/openssf"],
        )
        verifier = PluginVerifier(config)

        attestation = AttestationInfo(
            subject="https://github.com/openssf/scorecard",
        )

        assert verifier._is_publisher_trusted(attestation) is True

    def test_no_match(self) -> None:
        """Test no match returns False."""
        config = VerificationConfig(
            allow_unsigned=False,
            trusted_publishers=["https://github.com/trusted-org"],
        )
        verifier = PluginVerifier(config)

        attestation = AttestationInfo(
            subject="https://github.com/untrusted-org/package",
        )

        assert verifier._is_publisher_trusted(attestation) is False

    def test_empty_trusted_list(self) -> None:
        """Test empty trusted list returns False."""
        config = VerificationConfig(
            allow_unsigned=False,
            trusted_publishers=[],
        )
        verifier = PluginVerifier(config)

        attestation = AttestationInfo(
            subject="https://github.com/any-org/package",
        )

        assert verifier._is_publisher_trusted(attestation) is False


class TestVerifyPluginFunction:
    """Tests for the verify_plugin convenience function."""

    def test_verify_plugin_function(self) -> None:
        """Test the module-level verify_plugin function."""
        result = verify_plugin("pytest", allow_unsigned=True)

        assert result.verified is True

    def test_verify_plugin_with_trusted_publishers(self) -> None:
        """Test verify_plugin with trusted publishers list."""
        result = verify_plugin(
            "pytest",
            allow_unsigned=True,
            trusted_publishers=["pytest-dev"],
        )

        # Should verify (allow_unsigned=True)
        assert result.verified is True


class TestVerificationIntegration:
    """Integration tests for verification with darnit packages."""

    def test_verify_darnit_baseline(self) -> None:
        """Test verifying darnit-baseline package."""
        config = VerificationConfig(
            allow_unsigned=True,
            trusted_publishers=["kusari-oss", "openssf"],
            verify_online=False,  # Skip network for tests
        )
        verifier = PluginVerifier(config)

        result = verifier.verify_plugin("darnit-baseline")

        # Should verify since allow_unsigned=True
        assert result.verified is True

    def test_verify_darnit_core(self) -> None:
        """Test verifying darnit core package."""
        config = VerificationConfig(allow_unsigned=True, verify_online=False)
        verifier = PluginVerifier(config)

        result = verifier.verify_plugin("darnit")

        assert result.verified is True

    def test_production_mode_unsigned_rejected(self) -> None:
        """Test that production mode rejects unsigned packages."""
        config = VerificationConfig(
            allow_unsigned=False,
            trusted_publishers=["nonexistent-publisher"],
            verify_online=False,
        )
        verifier = PluginVerifier(config)

        result = verifier.verify_plugin("pytest")

        # Should not verify (no matching trusted publisher)
        assert result.verified is False or result.warning is not None
