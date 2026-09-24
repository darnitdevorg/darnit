"""Tests for darnit.core.discovery module."""

from unittest.mock import MagicMock

import pytest

from darnit.config.framework_schema import PluginsConfig
from darnit.core import discovery
from darnit.core.discovery import (
    _policy_cache_key,
    _resolve_distribution_name,
    clear_cache,
    discover_implementations,
    get_implementation,
)
from darnit.core.verification import VerificationResult


class _StubImplementation:
    """Minimal object satisfying the ComplianceImplementation protocol."""

    name = "stub-framework"
    display_name = "Stub Framework"
    version = "9.9.9"
    spec_version = "Stub v1"

    def get_all_controls(self):
        return []

    def get_controls_by_level(self, level):
        return []

    def get_rules_catalog(self):
        return {}

    def get_remediation_registry(self):
        return {}

    def get_framework_config_path(self):
        return None

    def register_controls(self):
        return None


def _fake_entry_point(name: str, dist_name: str | None) -> MagicMock:
    """Build an entry-point double for the ``darnit.implementations`` group.

    ``dist_name=None`` models an entry point with no distribution metadata.
    """
    ep = MagicMock()
    ep.name = name
    ep.load.return_value = _StubImplementation
    if dist_name is None:
        # MagicMock would otherwise autocreate a truthy `dist`.
        ep.dist = None
    else:
        dist = MagicMock()
        dist.name = dist_name
        ep.dist = dist
    return ep


@pytest.fixture
def fake_entry_points(monkeypatch):
    """Install fake entry points for the ``darnit.implementations`` group.

    ``discovery`` imports ``entry_points`` inside the function, so the patch
    must land on ``importlib.metadata``.
    """

    def _install(*eps):
        def _entry_points(group=None, **kwargs):
            return list(eps) if group == "darnit.implementations" else []

        monkeypatch.setattr("importlib.metadata.entry_points", _entry_points)

    return _install


@pytest.fixture
def verified_package_names(monkeypatch):
    """Record names passed to the verifier, without network or cache access."""
    recorded: list[str] = []

    class _RecordingVerifier:
        def __init__(self, config):
            self.config = config

        def verify_plugin(self, package_name, use_cache=True):
            recorded.append(package_name)
            return VerificationResult(verified=True, signed=True, trusted=True)

    monkeypatch.setattr(discovery, "PluginVerifier", _RecordingVerifier)
    return recorded


@pytest.fixture
def unverified_plugins(monkeypatch):
    """Verifier that records (name, allow_unsigned) and never verifies."""
    recorded: list[tuple[str, bool]] = []

    class _Unverified:
        def __init__(self, config):
            self.config = config

        def verify_plugin(self, package_name, use_cache=True):
            recorded.append((package_name, self.config.allow_unsigned))
            return VerificationResult(verified=False, error="not found")

    monkeypatch.setattr(discovery, "PluginVerifier", _Unverified)
    return recorded


def _write_plugins(repo, body: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / ".baseline.toml").write_text(body, encoding="utf-8")


class TestDiscoverImplementations:
    """Tests for discover_implementations function."""

    @pytest.fixture(autouse=True)
    def clear_discovery_cache(self):
        """Clear cache before each test."""
        clear_cache()
        yield
        clear_cache()

    @pytest.mark.unit
    def test_discovers_openssf_baseline(self):
        """Test that openssf-baseline implementation is discovered."""
        implementations = discover_implementations()
        assert "openssf-baseline" in implementations

    @pytest.mark.unit
    def test_clear_cache_works(self):
        """Test that clear_cache resets the cache."""
        impl1 = discover_implementations()
        clear_cache()
        impl2 = discover_implementations()
        # Should be different dict objects after cache clear
        assert impl1 is not impl2


class TestGetImplementation:
    """Tests for get_implementation function."""

    @pytest.fixture(autouse=True)
    def clear_discovery_cache(self):
        """Clear cache before each test."""
        clear_cache()
        yield
        clear_cache()

    @pytest.mark.unit
    def test_get_existing_implementation(self):
        """Test getting an existing implementation by name."""
        impl = get_implementation("openssf-baseline")
        assert impl is not None
        assert impl.name == "openssf-baseline"

    @pytest.mark.unit
    def test_get_nonexistent_implementation(self):
        """Test getting a nonexistent implementation returns None."""
        impl = get_implementation("nonexistent-implementation")
        assert impl is None


class TestDistributionNameResolution:
    """Tests that verification receives the distribution name, not the slug."""

    @pytest.fixture(autouse=True)
    def clear_discovery_cache(self):
        """Clear cache before each test."""
        clear_cache()
        yield
        clear_cache()

    @pytest.mark.unit
    def test_resolves_to_distribution_name(self):
        """``ep.dist.name`` wins over the entry-point slug."""
        ep = _fake_entry_point("openssf-baseline", dist_name="darnit-baseline")
        assert _resolve_distribution_name(ep) == "darnit-baseline"

    @pytest.mark.unit
    def test_falls_back_when_dist_is_none(self):
        """Falls back to the slug when ``ep.dist`` is None."""
        ep = _fake_entry_point("reproducibility", dist_name=None)
        assert _resolve_distribution_name(ep) == "reproducibility"

    @pytest.mark.unit
    def test_falls_back_when_dist_name_is_blank(self):
        """An empty distribution name is treated as absent."""
        ep = _fake_entry_point("gittuf", dist_name="")
        assert _resolve_distribution_name(ep) == "gittuf"

    @pytest.mark.unit
    def test_verifier_receives_distribution_name(
        self, fake_entry_points, verified_package_names
    ):
        """Discovery verifies the distribution, not the entry-point slug."""
        fake_entry_points(
            _fake_entry_point("openssf-baseline", dist_name="darnit-baseline")
        )

        discover_implementations()

        assert verified_package_names == ["darnit-baseline"]

    @pytest.mark.unit
    def test_verifier_receives_slug_when_dist_is_none(
        self, fake_entry_points, verified_package_names
    ):
        """The fallback reaches the verifier and discovery still loads the plugin."""
        fake_entry_points(_fake_entry_point("hello", dist_name=None))

        implementations = discover_implementations()

        assert verified_package_names == ["hello"]
        assert "stub-framework" in implementations


class TestPolicyAwareDiscovery:

    @pytest.fixture(autouse=True)
    def clear_discovery_cache(self):
        clear_cache()
        yield
        clear_cache()

    @pytest.mark.unit
    def test_strict_policy_skips_unverifiable_plugin(
        self, tmp_path, fake_entry_points, unverified_plugins
    ):
        fake_entry_points(
            _fake_entry_point("openssf-baseline", dist_name="darnit-baseline")
        )
        _write_plugins(tmp_path, "[plugins]\nallow_unsigned = false\n")

        implementations = discover_implementations(tmp_path)

        assert implementations == {}
        assert unverified_plugins == [("darnit-baseline", False)]

    @pytest.mark.unit
    def test_permissive_policy_loads_unverifiable_plugin(
        self, tmp_path, fake_entry_points, unverified_plugins
    ):
        fake_entry_points(
            _fake_entry_point("openssf-baseline", dist_name="darnit-baseline")
        )
        _write_plugins(tmp_path, "[plugins]\nallow_unsigned = true\n")

        implementations = discover_implementations(tmp_path)

        assert "stub-framework" in implementations
        assert unverified_plugins == [("darnit-baseline", True)]

    @pytest.mark.unit
    def test_absent_policy_uses_permissive_default(
        self, tmp_path, fake_entry_points, unverified_plugins
    ):
        fake_entry_points(
            _fake_entry_point("openssf-baseline", dist_name="darnit-baseline")
        )
        tmp_path.mkdir(exist_ok=True)

        implementations = discover_implementations(tmp_path)

        assert "stub-framework" in implementations
        assert unverified_plugins == [("darnit-baseline", True)]

    @pytest.mark.unit
    def test_repo_b_strict_does_not_reuse_repo_a_result(
        self, tmp_path, fake_entry_points, unverified_plugins
    ):
        fake_entry_points(
            _fake_entry_point("openssf-baseline", dist_name="darnit-baseline")
        )
        repo_a = tmp_path / "a"
        repo_b = tmp_path / "b"
        _write_plugins(repo_a, "[plugins]\nallow_unsigned = true\n")
        _write_plugins(repo_b, "[plugins]\nallow_unsigned = false\n")

        loaded_a = discover_implementations(repo_a)
        loaded_b = discover_implementations(repo_b)

        assert "stub-framework" in loaded_a
        assert "stub-framework" not in loaded_b
        assert loaded_a is not loaded_b
        assert unverified_plugins == [
            ("darnit-baseline", True),
            ("darnit-baseline", False),
        ]

    @pytest.mark.unit
    def test_identical_policies_share_cache_entry(
        self, tmp_path, fake_entry_points, unverified_plugins
    ):
        fake_entry_points(
            _fake_entry_point("openssf-baseline", dist_name="darnit-baseline")
        )
        repo_a = tmp_path / "a"
        repo_b = tmp_path / "b"
        body = "[plugins]\nallow_unsigned = false\n"
        _write_plugins(repo_a, body)
        _write_plugins(repo_b, body)

        loaded_a = discover_implementations(repo_a)
        loaded_b = discover_implementations(repo_b)

        assert loaded_a is loaded_b
        assert len(unverified_plugins) == 1

    @pytest.mark.unit
    def test_unconfigured_repositories_share_cache_entry(
        self, tmp_path, fake_entry_points, unverified_plugins
    ):
        fake_entry_points(
            _fake_entry_point("openssf-baseline", dist_name="darnit-baseline")
        )
        repo_a = tmp_path / "a"
        repo_b = tmp_path / "b"
        repo_a.mkdir()
        repo_b.mkdir()

        loaded_a = discover_implementations(repo_a)
        loaded_b = discover_implementations(repo_b)
        loaded_none = discover_implementations()

        assert loaded_a is loaded_b is loaded_none
        assert len(unverified_plugins) == 1

    @pytest.mark.unit
    def test_clear_cache_clears_all_policy_entries(
        self, tmp_path, fake_entry_points, unverified_plugins
    ):
        fake_entry_points(
            _fake_entry_point("openssf-baseline", dist_name="darnit-baseline")
        )
        repo_a = tmp_path / "a"
        repo_b = tmp_path / "b"
        _write_plugins(repo_a, "[plugins]\nallow_unsigned = true\n")
        _write_plugins(repo_b, "[plugins]\nallow_unsigned = false\n")

        first_a = discover_implementations(repo_a)
        first_b = discover_implementations(repo_b)
        clear_cache()
        second_a = discover_implementations(repo_a)

        assert first_a is not second_a
        assert first_b is not second_a
        assert unverified_plugins.count(("darnit-baseline", True)) == 2

    @pytest.mark.unit
    def test_explicit_true_and_unset_do_not_share_fingerprint(self):
        unset = _policy_cache_key(None)
        empty = _policy_cache_key(PluginsConfig())
        explicit_true = _policy_cache_key(PluginsConfig(**{"allow_unsigned": True}))

        assert unset == empty == ""
        assert unset != explicit_true

    @pytest.mark.unit
    def test_missing_and_empty_plugins_share_unconfigured_key(
        self, tmp_path, fake_entry_points, unverified_plugins
    ):
        fake_entry_points(
            _fake_entry_point("openssf-baseline", dist_name="darnit-baseline")
        )
        missing = tmp_path / "missing"
        empty = tmp_path / "empty"
        missing.mkdir()
        (missing / ".baseline.toml").write_text('version = "1.0"\n', encoding="utf-8")
        _write_plugins(empty, "[plugins]\n")

        loaded_none = discover_implementations()
        loaded_missing = discover_implementations(missing)
        loaded_empty = discover_implementations(empty)

        assert loaded_none is loaded_missing is loaded_empty
        assert len(unverified_plugins) == 1

    @pytest.mark.unit
    def test_version_only_difference_shares_cache_key(self):
        older = PluginsConfig(**{"darnit-baseline": {"version": ">=1.0.0"}})
        newer = PluginsConfig(**{"darnit-baseline": {"version": ">=2.0.0"}})

        assert _policy_cache_key(older) == _policy_cache_key(newer) == ""

    @pytest.mark.unit
    def test_allow_unsigned_difference_does_not_share_cache_key(self):
        permissive = _policy_cache_key(PluginsConfig(**{"allow_unsigned": True}))
        strict = _policy_cache_key(PluginsConfig(**{"allow_unsigned": False}))

        assert permissive != strict
        assert permissive != ""

    @pytest.mark.unit
    def test_trusted_publishers_difference_does_not_share_cache_key(self):
        one = _policy_cache_key(PluginsConfig(**{"trusted_publishers": ["org-a"]}))
        other = _policy_cache_key(PluginsConfig(**{"trusted_publishers": ["org-b"]}))

        assert one != other
        assert one != ""

    @pytest.mark.unit
    def test_per_plugin_config_uses_distribution_name(
        self, tmp_path, fake_entry_points, unverified_plugins
    ):
        """Keyed by distribution name, not the entry-point slug."""
        fake_entry_points(
            _fake_entry_point("openssf-baseline", dist_name="darnit-baseline")
        )
        _write_plugins(
            tmp_path,
            "\n".join(
                [
                    "[plugins]",
                    "allow_unsigned = false",
                    "",
                    '[plugins."darnit-baseline"]',
                    "allow_unsigned = true",
                    "",
                ]
            ),
        )

        implementations = discover_implementations(tmp_path)

        assert "stub-framework" in implementations
        assert unverified_plugins == [("darnit-baseline", True)]

    @pytest.mark.unit
    def test_no_repo_path_still_discovers(
        self, fake_entry_points, unverified_plugins
    ):
        fake_entry_points(
            _fake_entry_point("openssf-baseline", dist_name="darnit-baseline")
        )

        implementations = discover_implementations()

        assert "stub-framework" in implementations
        assert get_implementation("stub-framework") is implementations["stub-framework"]

    @pytest.mark.unit
    def test_malformed_baseline_toml_does_not_fail_open(
        self, tmp_path, fake_entry_points, unverified_plugins
    ):
        import tomllib

        fake_entry_points(
            _fake_entry_point("openssf-baseline", dist_name="darnit-baseline")
        )
        _write_plugins(tmp_path, "this is not = valid [toml\n")

        with pytest.raises(tomllib.TOMLDecodeError):
            discover_implementations(tmp_path)

        assert unverified_plugins == []
