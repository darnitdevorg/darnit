"""Tests for plugin verification using Sigstore."""

import json
import time
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from darnit.config.operator.schema import PluginSettings
from darnit.core.verification import (
    CACHE_SCHEMA_VERSION,
    DEFAULT_TRUSTED_PUBLISHERS,
    AttestationInfo,
    PluginVerifier,
    VerificationCache,
    VerificationCacheEntry,
    VerificationConfig,
    _AttestationLookup,
    verify_plugin,
)

INSTALLED = {"name": "evil-plugin", "version": "1.2.3", "metadata": {}}


def _entry(**overrides: object) -> VerificationCacheEntry:
    """A raw cache entry. Keyword arguments replace the unsigned default."""
    fields: dict[str, object] = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "package": "test-package",
        "version": "1.0.0",
        "cached_at": 0,
        "status": "unsigned",
    }
    fields.update(overrides)
    return VerificationCacheEntry(**fields)  # type: ignore[arg-type]


def _verifier(cache_dir: Path, **overrides: object) -> PluginVerifier:
    """A verifier whose disk cache is ``cache_dir`` and whose defaults are strict."""
    fields: dict[str, object] = {
        "allow_unsigned": False,
        "trusted_publishers": [],
        "use_default_publishers": False,
        "cache_dir": cache_dir,
        "verify_online": True,
    }
    fields.update(overrides)
    return PluginVerifier(VerificationConfig(**fields))  # type: ignore[arg-type]


class _Response:
    """A context-manager stand-in for ``urlopen``."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _response(payload: dict) -> _Response:
    return _Response(payload)


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


class TestFromPluginSettings:
    """Tests for building a VerificationConfig from operator [plugins] settings."""

    def test_none_yields_defaults(self) -> None:
        """No operator settings leaves every default in place."""
        config = VerificationConfig.from_plugin_settings(None)

        assert config.allow_unsigned is True
        assert config.trusted_publishers == []

    def test_unset_allow_unsigned_keeps_default(self) -> None:
        """A [plugins] table that never mentions signing does not conclude the policy."""
        config = VerificationConfig.from_plugin_settings(PluginSettings())

        assert config.allow_unsigned is True

    def test_other_keys_do_not_conclude_allow_unsigned(self) -> None:
        """Setting an unrelated key leaves allow_unsigned unconfigured."""
        settings = PluginSettings(allowed=["openssf-baseline"])
        config = VerificationConfig.from_plugin_settings(settings)

        assert config.allow_unsigned is True

    def test_explicit_allow_unsigned_true(self) -> None:
        """An explicit true is honored."""
        config = VerificationConfig.from_plugin_settings(PluginSettings(allow_unsigned=True))

        assert config.allow_unsigned is True

    def test_explicit_allow_unsigned_false(self) -> None:
        """An explicit false is honored."""
        config = VerificationConfig.from_plugin_settings(PluginSettings(allow_unsigned=False))

        assert config.allow_unsigned is False

    def test_trusted_publishers_pass_through(self) -> None:
        """The operator's publishers reach the config as a list."""
        settings = PluginSettings(trusted_publishers=["https://github.com/my-org"])
        config = VerificationConfig.from_plugin_settings(settings)

        assert config.trusted_publishers == ["https://github.com/my-org"]

    def test_defaults_still_included(self) -> None:
        """Operator publishers add to DEFAULT_TRUSTED_PUBLISHERS rather than replacing them."""
        settings = PluginSettings(trusted_publishers=["https://github.com/my-org"])
        config = VerificationConfig.from_plugin_settings(settings)
        all_publishers = config.get_all_trusted_publishers()

        assert "https://github.com/my-org" in all_publishers
        for default in DEFAULT_TRUSTED_PUBLISHERS:
            assert default in all_publishers


class TestVerificationCache:
    """Tests for VerificationCache."""

    def test_cache_set_and_get(self, tmp_path: Path) -> None:
        """A stored observation round-trips without a policy decision."""
        cache = VerificationCache(tmp_path, ttl=3600)

        attestation = AttestationInfo(
            subject="https://github.com/test/repo",
            repository="https://github.com/test/repo",
        )
        entry = VerificationCacheEntry(
            schema_version=CACHE_SCHEMA_VERSION,
            package="test-package",
            version="1.0.0",
            cached_at=0,
            status="signed",
            publisher="test-publisher",
            publisher_repo="https://github.com/test/repo",
            attestation=attestation,
        )

        cache.set("test-package", "1.0.0", entry)
        retrieved = cache.get("test-package", "1.0.0")

        assert retrieved is not None
        assert retrieved.status == "signed"
        assert retrieved.publisher == "test-publisher"
        assert retrieved.attestation is not None
        assert retrieved.attestation.repository == "https://github.com/test/repo"

        stored = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
        assert stored["schema_version"] == CACHE_SCHEMA_VERSION
        assert stored["status"] == "signed"
        assert "verified" not in stored
        assert "trusted" not in stored
        assert "warning" not in stored
        assert "error" not in stored

    def test_undetermined_observation_is_not_stored(self, tmp_path: Path) -> None:
        """A lookup that did not establish signing state leaves no cache file."""
        cache = VerificationCache(tmp_path)
        cache.set(
            "test-package",
            "1.0.0",
            _entry(status="undetermined"),
        )

        assert cache.get("test-package", "1.0.0") is None
        assert list(tmp_path.glob("*.json")) == []

    def test_cache_miss(self, tmp_path: Path) -> None:
        """Test cache miss returns None."""
        cache = VerificationCache(tmp_path)

        result = cache.get("nonexistent-package", "1.0.0")
        assert result is None

    def test_cache_expiration(self, tmp_path: Path) -> None:
        """Test that expired cache entries return None."""
        cache = VerificationCache(tmp_path, ttl=1)  # 1 second TTL

        cache.set("test-package", "1.0.0", _entry(status="unsigned"))

        # Wait for expiration
        time.sleep(1.1)

        retrieved = cache.get("test-package", "1.0.0")
        assert retrieved is None

    def test_cache_different_versions(self, tmp_path: Path) -> None:
        """Test that different versions have separate cache entries."""
        cache = VerificationCache(tmp_path)

        cache.set("test-package", "1.0.0", _entry(version="1.0.0", status="signed", publisher="v1"))
        cache.set("test-package", "2.0.0", _entry(version="2.0.0", status="unsigned", publisher="v2"))

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
        assert result.status == "undetermined"
        assert "not found" in result.error.lower()

    def test_verify_installed_package_allow_unsigned(self, tmp_path: Path) -> None:
        """A completed unsigned lookup is accepted when allow_unsigned is set."""
        verifier = _verifier(tmp_path, allow_unsigned=True)
        with (
            patch.object(verifier, "_fetch_pypi_attestation", return_value=_AttestationLookup(kind="absent")),
            patch.object(verifier, "_get_fallback_publisher", return_value=None),
        ):
            result = verifier.verify_plugin("pytest")

        assert result.verified is True
        assert result.signed is False
        assert result.status == "unsigned"
        assert result.cached is False

    def test_unsigned_metadata_does_not_grant_trust(self, tmp_path: Path) -> None:
        """Author text that contains a trusted publisher does not verify a strict run."""
        verifier = _verifier(
            tmp_path,
            allow_unsigned=False,
            trusted_publishers=["https://github.com/pytest-dev"],
        )

        with (
            patch.object(verifier, "_fetch_pypi_attestation", return_value=_AttestationLookup(kind="absent")),
            patch.object(
                verifier,
                "_get_fallback_publisher",
                return_value="https://github.com/pytest-dev/pytest",
            ),
        ):
            result = verifier.verify_plugin("pytest")

        assert result.verified is False
        assert result.trusted is False
        assert result.signed is False

    def test_unsigned_allowed_remains_untrusted(self, tmp_path: Path) -> None:
        """allow_unsigned accepts an unsigned package without marking it trusted."""
        verifier = _verifier(
            tmp_path,
            allow_unsigned=True,
            trusted_publishers=["https://github.com/pytest-dev"],
        )

        with (
            patch.object(verifier, "_fetch_pypi_attestation", return_value=_AttestationLookup(kind="absent")),
            patch.object(
                verifier,
                "_get_fallback_publisher",
                return_value="https://github.com/pytest-dev/pytest",
            ),
        ):
            result = verifier.verify_plugin("pytest")

        assert result.verified is True
        assert result.trusted is False

    def test_verify_uses_cache(self, tmp_path: Path) -> None:
        """A second call reuses the raw observation."""
        verifier = _verifier(tmp_path, allow_unsigned=True)
        fetch = MagicMock(return_value=_AttestationLookup(kind="absent"))
        with (
            patch.object(verifier, "_fetch_pypi_attestation", fetch),
            patch.object(verifier, "_get_fallback_publisher", return_value=None),
        ):
            result1 = verifier.verify_plugin("pytest")
            result2 = verifier.verify_plugin("pytest")

        assert result1.cached is False
        assert result2.cached is True
        assert result2.verified is True
        assert fetch.call_count == 1

    def test_verify_skip_cache(self, tmp_path: Path) -> None:
        """Test verification can skip cache."""
        config = VerificationConfig(
            allow_unsigned=True,
            cache_dir=tmp_path,
            verify_online=False,
        )
        verifier = PluginVerifier(config)

        with patch.object(verifier, "_fetch_pypi_attestation", return_value=_AttestationLookup(kind="absent")):
            verifier.verify_plugin("pytest")

            # Second call with cache disabled
            result = verifier.verify_plugin("pytest", use_cache=False)
        assert result.cached is False

    def test_verify_multiple_plugins(self, tmp_path: Path) -> None:
        """Test verifying multiple plugins at once."""
        verifier = _verifier(tmp_path, allow_unsigned=True)
        with patch.object(verifier, "_fetch_pypi_attestation", return_value=_AttestationLookup(kind="absent")):
            results = verifier.verify_plugins(["pytest", "nonexistent-pkg-123"])

        assert "pytest" in results
        assert "nonexistent-pkg-123" in results
        assert results["pytest"].verified is True
        assert results["nonexistent-pkg-123"].verified is False

    @patch("darnit.core.verification.PluginVerifier._check_sigstore_available")
    def test_sigstore_unavailable(self, mock_check: MagicMock, tmp_path: Path) -> None:
        """Provenance that cannot be read is undetermined, even when unsigned packages are allowed."""
        mock_check.return_value = False

        verifier = _verifier(tmp_path, allow_unsigned=True)
        verifier._sigstore_available = False
        fetch = MagicMock(
            return_value=_AttestationLookup(
                kind="provenance",
                data={"has_provenance": True, "provenance_url": "https://example.test/prov"},
            )
        )

        with patch.object(
            verifier, "_get_package_info", return_value={"name": "test", "version": "1.0.0", "metadata": {}}
        ):
            with patch.object(verifier, "_fetch_pypi_attestation", fetch):
                result = verifier.verify_plugin("test-package")
                again = verifier.verify_plugin("test-package")

        assert result.verified is False
        assert result.signed is False
        assert result.cached is False
        assert again.cached is False
        assert list(tmp_path.glob("*.json")) == []
        assert fetch.call_count == 2


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

    def test_org_url_rejects_owner_lookalike(self) -> None:
        """An org URL does not match an owner that merely begins with that name."""
        config = VerificationConfig(
            allow_unsigned=False,
            trusted_publishers=["https://github.com/my-org"],
            use_default_publishers=False,
        )
        verifier = PluginVerifier(config)

        assert (
            verifier._is_publisher_trusted(AttestationInfo(subject="https://github.com/my-org-attacker/repo")) is False
        )
        assert verifier._is_publisher_trusted(AttestationInfo(repository="https://github.com/my-org/repo")) is True

    def test_bare_owner_rejects_embedded_name(self) -> None:
        """A bare owner matches that GitHub owner segment and no longer name."""
        config = VerificationConfig(
            allow_unsigned=False,
            trusted_publishers=["kusari-oss"],
            use_default_publishers=False,
        )
        verifier = PluginVerifier(config)

        assert (
            verifier._is_publisher_trusted(AttestationInfo(repository="https://github.com/not-kusari-oss/repo"))
            is False
        )
        assert (
            verifier._is_publisher_trusted(AttestationInfo(repository="https://github.com/kusari-oss-attacker/repo"))
            is False
        )
        assert (
            verifier._is_publisher_trusted(AttestationInfo(repository="https://github.com/kusari-oss/darnit")) is True
        )

    def test_github_host_must_be_exact(self) -> None:
        config = VerificationConfig(
            allow_unsigned=False,
            trusted_publishers=["https://github.com/my-org"],
            use_default_publishers=False,
        )
        verifier = PluginVerifier(config)

        assert verifier._is_publisher_trusted(AttestationInfo(subject="https://evilgithub.com/my-org/repo")) is False

    def test_repo_url_rejects_repo_lookalike(self) -> None:
        config = VerificationConfig(
            allow_unsigned=False,
            trusted_publishers=["https://github.com/my-org/repo"],
            use_default_publishers=False,
        )
        verifier = PluginVerifier(config)

        assert verifier._is_publisher_trusted(AttestationInfo(subject="https://github.com/my-org/repo-evil")) is False
        assert verifier._is_publisher_trusted(AttestationInfo(subject="https://github.com/my-org/repo")) is True

    def test_email_does_not_match_by_substring(self) -> None:
        config = VerificationConfig(
            allow_unsigned=False,
            trusted_publishers=["user@example.com"],
            use_default_publishers=False,
        )
        verifier = PluginVerifier(config)

        assert verifier._is_publisher_trusted(AttestationInfo(subject="user@example.com.attacker")) is False
        assert verifier._is_publisher_trusted(AttestationInfo(subject="user@example.com")) is True


class TestVerifyPluginFunction:
    """Tests for the verify_plugin convenience function."""

    def test_verify_plugin_function(self, tmp_path: Path) -> None:
        """Test the module-level verify_plugin function."""
        with (
            patch("darnit.core.verification.Path.home", return_value=tmp_path),
            patch.object(PluginVerifier, "_fetch_pypi_attestation", return_value=_AttestationLookup(kind="absent")),
            patch.object(PluginVerifier, "_get_fallback_publisher", return_value=None),
        ):
            result = verify_plugin("pytest", allow_unsigned=True)

        assert result.verified is True

    def test_verify_plugin_with_trusted_publishers(self, tmp_path: Path) -> None:
        """Test verify_plugin with trusted publishers list."""
        with (
            patch("darnit.core.verification.Path.home", return_value=tmp_path),
            patch.object(PluginVerifier, "_fetch_pypi_attestation", return_value=_AttestationLookup(kind="absent")),
            patch.object(PluginVerifier, "_get_fallback_publisher", return_value=None),
        ):
            result = verify_plugin(
                "pytest",
                allow_unsigned=True,
                trusted_publishers=["pytest-dev"],
            )

        assert result.verified is True


class TestVerificationIntegration:
    """Integration tests for verification with darnit packages."""

    def test_verify_darnit_baseline(self, tmp_path: Path) -> None:
        """Test verifying darnit-baseline package."""
        verifier = _verifier(
            tmp_path,
            allow_unsigned=True,
            trusted_publishers=["kusari-oss", "openssf"],
        )
        with patch.object(verifier, "_fetch_pypi_attestation", return_value=_AttestationLookup(kind="absent")):
            result = verifier.verify_plugin("darnit-baseline")

        assert result.verified is True

    def test_verify_darnit_core(self, tmp_path: Path) -> None:
        """Test verifying darnit core package.

        The PyPI distribution name is `darnit-core`; the import name and
        CLI command stay `darnit`. PluginVerifier looks up the
        distribution name to find package metadata.
        """
        verifier = _verifier(tmp_path, allow_unsigned=True)
        with patch.object(verifier, "_fetch_pypi_attestation", return_value=_AttestationLookup(kind="absent")):
            result = verifier.verify_plugin("darnit-core")

        assert result.verified is True

    def test_production_mode_unsigned_rejected(self) -> None:
        """Test that production mode rejects unsigned packages."""
        config = VerificationConfig(
            allow_unsigned=False,
            trusted_publishers=["nonexistent-publisher"],
            verify_online=False,
        )
        verifier = PluginVerifier(config)

        with patch.object(verifier, "_fetch_pypi_attestation", return_value=_AttestationLookup(kind="absent")):
            result = verifier.verify_plugin("pytest")

        # Should not verify (no matching trusted publisher)
        assert result.verified is False or result.warning is not None


def _installed(verifier: PluginVerifier):
    """Point one verifier at the shared fake distribution."""
    return patch.object(verifier, "_get_package_info", return_value=dict(INSTALLED))


def _plant(cache: VerificationCache, payload: dict) -> Path:
    """Write a raw cache file for the fake distribution."""
    path = cache._cache_path("evil-plugin", "1.2.3")
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run_pair(
    tmp_path: Path, first: dict, second: dict, lookup: _AttestationLookup, identity: AttestationInfo | None = None
):
    """Run the same package through two verifiers that share ``tmp_path``."""
    left = _verifier(tmp_path, **first)
    right = _verifier(tmp_path, **second)
    fetch = MagicMock(return_value=lookup)
    extract = MagicMock(return_value=identity)
    with (
        _installed(left),
        _installed(right),
        patch.object(left, "_fetch_pypi_attestation", fetch),
        patch.object(right, "_fetch_pypi_attestation", fetch),
        patch.object(left, "_get_fallback_publisher", return_value=None),
        patch.object(right, "_get_fallback_publisher", return_value=None),
        patch.object(left, "_verify_attestation_sigstore", extract),
        patch.object(right, "_verify_attestation_sigstore", extract),
    ):
        return left.verify_plugin("evil-plugin"), right.verify_plugin("evil-plugin"), fetch


_PROVENANCE = _AttestationLookup(
    kind="provenance",
    data={"has_provenance": True, "provenance_url": "https://example.test/prov"},
)


class TestPolicyReappliedAfterCache:
    """Disk entries are observations. The live policy decides verified and trusted."""

    def test_permissive_unsigned_does_not_satisfy_a_later_strict_run(self, tmp_path: Path) -> None:
        first, second, fetch = _run_pair(
            tmp_path, {"allow_unsigned": True}, {"allow_unsigned": False}, _AttestationLookup(kind="absent")
        )

        assert first.verified is True and first.cached is False
        assert second.verified is False and second.trusted is False and second.cached is True
        assert fetch.call_count == 1
        stored = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
        assert stored["schema_version"] == CACHE_SCHEMA_VERSION
        assert stored["status"] == "unsigned"
        assert "verified" not in stored

    def test_strict_unsigned_cache_is_accepted_by_a_later_permissive_run(self, tmp_path: Path) -> None:
        first, second, fetch = _run_pair(
            tmp_path, {"allow_unsigned": False}, {"allow_unsigned": True}, _AttestationLookup(kind="absent")
        )

        assert first.verified is False and first.cached is False
        assert second.verified is True and second.cached is True
        assert fetch.call_count == 1

    def test_publisher_policy_is_reapplied_to_a_cached_identity(self, tmp_path: Path) -> None:
        identity = AttestationInfo(
            subject="https://github.com/attacker/plugin",
            repository="https://github.com/attacker/plugin",
        )
        first, second, fetch = _run_pair(
            tmp_path,
            {"allow_unsigned": False, "trusted_publishers": ["https://github.com/attacker/plugin"]},
            {"allow_unsigned": False, "trusted_publishers": ["https://github.com/trusted-org"]},
            _PROVENANCE,
            identity,
        )

        assert first.verified is True and first.trusted is True and first.status == "signed"
        assert first.cached is False
        assert second.verified is False and second.trusted is False and second.status == "signed"
        assert second.cached is True
        assert fetch.call_count == 1

    def test_default_publishers_are_reapplied_to_a_cached_identity(self, tmp_path: Path) -> None:
        identity = AttestationInfo(
            subject="https://github.com/kusari-oss/darnit",
            repository="https://github.com/kusari-oss/darnit",
        )
        first, second, fetch = _run_pair(
            tmp_path,
            {"allow_unsigned": False, "use_default_publishers": True},
            {"allow_unsigned": False, "use_default_publishers": False},
            _PROVENANCE,
            identity,
        )

        assert first.verified is True and first.trusted is True and first.cached is False
        assert second.verified is False and second.trusted is False and second.cached is True
        assert fetch.call_count == 1

    def test_cached_lookalike_publisher_stays_rejected(self, tmp_path: Path) -> None:
        identity = AttestationInfo(
            subject="https://github.com/my-org-attacker/plugin",
            repository="https://github.com/my-org-attacker/plugin",
        )
        policy = {
            "allow_unsigned": False,
            "use_default_publishers": False,
            "trusted_publishers": ["https://github.com/my-org"],
        }
        first, second, fetch = _run_pair(tmp_path, policy, policy, _PROVENANCE, identity)

        assert first.verified is False and first.trusted is False and first.cached is False
        assert second.verified is False and second.trusted is False and second.cached is True
        assert fetch.call_count == 1

    def test_old_decision_cache_is_a_miss(self, tmp_path: Path) -> None:
        verifier = _verifier(tmp_path, allow_unsigned=False)
        path = _plant(
            verifier.cache,
            {
                "verified": True,
                "signed": False,
                "trusted": True,
                "cached_at": time.time(),
                "package": "evil-plugin",
                "version": "1.2.3",
            },
        )
        fetch = MagicMock(return_value=_AttestationLookup(kind="absent"))
        with (
            _installed(verifier),
            patch.object(verifier, "_fetch_pypi_attestation", fetch),
            patch.object(verifier, "_get_fallback_publisher", return_value=None),
        ):
            result = verifier.verify_plugin("evil-plugin")

        assert result.verified is False
        assert result.cached is False
        assert fetch.call_count == 1
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["schema_version"] == CACHE_SCHEMA_VERSION
        assert stored["status"] == "unsigned"
        assert "verified" not in stored

    def test_unknown_schema_version_is_a_miss(self, tmp_path: Path) -> None:
        verifier = _verifier(tmp_path, allow_unsigned=False)
        _plant(
            verifier.cache,
            {
                "schema_version": 99,
                "status": "signed",
                "verified": True,
                "trusted": True,
                "publisher": "https://github.com/attacker/plugin",
                "cached_at": time.time(),
                "package": "evil-plugin",
                "version": "1.2.3",
            },
        )
        fetch = MagicMock(return_value=_AttestationLookup(kind="absent"))
        with (
            _installed(verifier),
            patch.object(verifier, "_fetch_pypi_attestation", fetch),
            patch.object(verifier, "_get_fallback_publisher", return_value=None),
        ):
            result = verifier.verify_plugin("evil-plugin")

        assert result.verified is False
        assert result.cached is False
        assert fetch.call_count == 1

    def test_invalid_observation_stays_rejected_when_unsigned_is_allowed(self, tmp_path: Path) -> None:
        verifier = _verifier(tmp_path, allow_unsigned=True)
        verifier.cache.set(
            "evil-plugin",
            "1.2.3",
            _entry(
                package="evil-plugin",
                version="1.2.3",
                status="invalid",
                publisher="https://github.com/attacker/plugin",
            ),
        )
        fetch = MagicMock(return_value=_AttestationLookup(kind="absent"))
        with _installed(verifier), patch.object(verifier, "_fetch_pypi_attestation", fetch):
            result = verifier.verify_plugin("evil-plugin")

        assert result.verified is False
        assert result.status == "invalid"
        assert result.cached is True
        assert fetch.call_count == 0

    def test_transient_lookup_failure_is_not_cached(self, tmp_path: Path) -> None:
        verifier = _verifier(tmp_path, allow_unsigned=True)
        fetch = MagicMock(return_value=_AttestationLookup(kind="undetermined"))
        with _installed(verifier), patch.object(verifier, "_fetch_pypi_attestation", fetch):
            first = verifier.verify_plugin("evil-plugin")
            second = verifier.verify_plugin("evil-plugin")

        assert first.verified is False
        assert first.status == "undetermined"
        assert first.cached is False
        assert second.verified is False
        assert second.status == "undetermined"
        assert second.cached is False
        assert list(tmp_path.glob("*.json")) == []
        assert fetch.call_count == 2

    def test_unexpected_exception_is_undetermined_and_not_cached(self, tmp_path: Path) -> None:
        """An unexpected verifier error is not an unsigned success and is not stored."""
        verifier = _verifier(tmp_path, allow_unsigned=True)

        def _boom(package_name, version):
            raise RuntimeError("verifier blew up")

        with _installed(verifier), patch.object(verifier, "_observe", side_effect=_boom):
            result = verifier.verify_plugin("evil-plugin")

        assert result.verified is False
        assert result.trusted is False
        assert result.status == "undetermined"
        assert result.cached is False
        assert "RuntimeError" in result.error
        assert list(tmp_path.glob("*.json")) == []

    def test_policy_exception_after_cache_hit_keeps_cached_flag(self, tmp_path: Path) -> None:
        """A disk hit stays cached=True when policy application fails afterward."""
        verifier = _verifier(tmp_path, allow_unsigned=True)
        verifier.cache.set(
            "evil-plugin",
            "1.2.3",
            _entry(package="evil-plugin", version="1.2.3", status="unsigned"),
        )

        with (
            _installed(verifier),
            patch.object(verifier, "_apply_policy", side_effect=RuntimeError("policy")),
        ):
            result = verifier.verify_plugin("evil-plugin")

        assert result.status == "undetermined"
        assert result.verified is False
        assert result.cached is True

    def test_http_404_for_installed_package_is_unsigned(self, tmp_path: Path) -> None:
        """A 404 for an installed version is an unsigned observation and is cached."""
        verifier = _verifier(tmp_path, allow_unsigned=True)
        missing = urllib.error.HTTPError("https://pypi.org/pypi/evil-plugin/1.2.3/json", 404, "missing", None, None)
        with (
            _installed(verifier),
            patch.object(verifier, "_get_fallback_publisher", return_value=None),
            patch("darnit.core.verification.urllib.request.urlopen", side_effect=missing) as opened,
        ):
            first = verifier.verify_plugin("evil-plugin")
            second = verifier.verify_plugin("evil-plugin")

        assert first.status == "unsigned"
        assert first.verified is True
        assert first.trusted is False
        assert first.cached is False
        assert second.status == "unsigned"
        assert second.cached is True
        stored = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
        assert stored["status"] == "unsigned"
        assert stored["schema_version"] == CACHE_SCHEMA_VERSION
        assert "verified" not in stored
        assert opened.call_count == 1

    def test_unreadable_bundle_is_not_cached_as_unsigned(self, tmp_path: Path) -> None:
        verifier = _verifier(tmp_path, allow_unsigned=True)
        fetch = MagicMock(
            return_value=_AttestationLookup(
                kind="provenance",
                data={"has_provenance": True, "provenance_url": "https://example.test/prov"},
            )
        )
        with (
            _installed(verifier),
            patch.object(verifier, "_fetch_pypi_attestation", fetch),
            patch.object(verifier, "_verify_attestation_sigstore", return_value=None),
        ):
            first = verifier.verify_plugin("evil-plugin")
            second = verifier.verify_plugin("evil-plugin")

        assert first.verified is False
        assert first.cached is False
        assert second.cached is False
        assert list(tmp_path.glob("*.json")) == []
        assert fetch.call_count == 2

    def test_lookup_distinguishes_no_provenance_from_failure(self, tmp_path: Path) -> None:
        verifier = _verifier(tmp_path, verify_online=True)
        offline = _verifier(tmp_path, verify_online=False)

        with patch("darnit.core.verification.urllib.request.urlopen") as urlopen:
            lookup = offline._fetch_pypi_attestation("pkg", "1.0.0")
        assert lookup.kind == "undetermined"
        assert urlopen.call_count == 0

        missing = urllib.error.HTTPError(
            "https://pypi.org/pypi/pkg/1.0.0/json",
            404,
            "missing",
            None,
            None,
        )
        failed = urllib.error.HTTPError(
            "https://pypi.org/pypi/pkg/1.0.0/json",
            500,
            "unavailable",
            None,
            None,
        )
        with patch("darnit.core.verification.urllib.request.urlopen", side_effect=missing):
            assert verifier._fetch_pypi_attestation("pkg", "1.0.0").kind == "absent"
        with patch("darnit.core.verification.urllib.request.urlopen", side_effect=failed):
            assert verifier._fetch_pypi_attestation("pkg", "1.0.0").kind == "undetermined"
        with patch(
            "darnit.core.verification.urllib.request.urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            assert verifier._fetch_pypi_attestation("pkg", "1.0.0").kind == "undetermined"
        with patch(
            "darnit.core.verification.urllib.request.urlopen",
            return_value=_response({"urls": []}),
        ):
            assert verifier._fetch_pypi_attestation("pkg", "1.0.0").kind == "absent"
        with patch(
            "darnit.core.verification.urllib.request.urlopen",
            return_value=_response({"urls": [{"provenance": "https://example.test/prov"}]}),
        ):
            found = verifier._fetch_pypi_attestation("pkg", "1.0.0")
        assert found.kind == "provenance"
        assert found.data is not None
        assert found.data["provenance_url"] == "https://example.test/prov"
