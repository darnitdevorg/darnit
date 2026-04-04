"""Tests for audit profile schema and resolution."""

import pytest

from darnit.config.framework_schema import AuditProfileConfig
from darnit.config.profile_resolver import (
    ProfileAmbiguousError,
    ProfileNotFoundError,
    resolve_profile,
    resolve_profile_control_ids,
)
from darnit.core.plugin import ControlSpec

# =============================================================================
# AuditProfileConfig validation tests
# =============================================================================


class TestAuditProfileConfig:
    """Tests for AuditProfileConfig Pydantic model."""

    def test_valid_with_controls(self):
        profile = AuditProfileConfig(
            description="Test profile",
            controls=["CTRL-01", "CTRL-02"],
        )
        assert profile.description == "Test profile"
        assert profile.controls == ["CTRL-01", "CTRL-02"]
        assert profile.tags == {}

    def test_valid_with_tags(self):
        profile = AuditProfileConfig(
            description="Tag-based profile",
            tags={"level": 1},
        )
        assert profile.tags == {"level": 1}
        assert profile.controls == []

    def test_valid_with_both(self):
        profile = AuditProfileConfig(
            description="Combined profile",
            controls=["CTRL-01"],
            tags={"domain": "AC"},
        )
        assert profile.controls == ["CTRL-01"]
        assert profile.tags == {"domain": "AC"}

    def test_rejects_empty_selectors(self):
        with pytest.raises(ValueError, match="at least one"):
            AuditProfileConfig(description="Empty profile")

    def test_rejects_empty_controls_and_tags(self):
        with pytest.raises(ValueError, match="at least one"):
            AuditProfileConfig(
                description="Empty",
                controls=[],
                tags={},
            )


# =============================================================================
# resolve_profile() tests
# =============================================================================


def _make_impls(**kwargs):
    """Helper to build implementations dict for resolve_profile."""
    return {
        name: {
            pname: AuditProfileConfig(description=f"{pname} profile", controls=["C1"])
            for pname in profiles
        }
        for name, profiles in kwargs.items()
    }


class TestResolveProfile:
    """Tests for resolve_profile() function."""

    def test_short_name_single_match(self):
        impls = _make_impls(baseline=["onboard", "verify"])
        impl_name, profile = resolve_profile("onboard", impls)
        assert impl_name == "baseline"
        assert profile.description == "onboard profile"

    def test_qualified_name(self):
        impls = _make_impls(baseline=["onboard"], gittuf=["onboard"])
        impl_name, profile = resolve_profile("gittuf:onboard", impls)
        assert impl_name == "gittuf"

    def test_short_name_ambiguous(self):
        impls = _make_impls(baseline=["onboard"], gittuf=["onboard"])
        with pytest.raises(ProfileAmbiguousError) as exc_info:
            resolve_profile("onboard", impls)
        assert "baseline" in str(exc_info.value)
        assert "gittuf" in str(exc_info.value)

    def test_not_found(self):
        impls = _make_impls(baseline=["onboard"])
        with pytest.raises(ProfileNotFoundError) as exc_info:
            resolve_profile("nonexistent", impls)
        assert "nonexistent" in str(exc_info.value)
        assert "onboard" in str(exc_info.value)

    def test_qualified_name_not_found(self):
        impls = _make_impls(baseline=["onboard"])
        with pytest.raises(ProfileNotFoundError):
            resolve_profile("baseline:nonexistent", impls)

    def test_empty_implementations(self):
        with pytest.raises(ProfileNotFoundError):
            resolve_profile("anything", {})


# =============================================================================
# resolve_profile_control_ids() tests
# =============================================================================


def _make_control(control_id, level=None, domain=None, severity=None):
    """Helper to create a ControlSpec for testing."""
    tags = {}
    if level is not None:
        tags["level"] = level
    if domain is not None:
        tags["domain"] = domain
    if severity is not None:
        tags["security_severity"] = severity
    return ControlSpec(
        control_id=control_id,
        name=control_id,
        description=f"Test control {control_id}",
        level=level,
        domain=domain,
        metadata={},
        tags=tags,
    )


class TestResolveProfileControlIds:
    """Tests for resolve_profile_control_ids() function."""

    def test_explicit_controls(self):
        controls = [_make_control("C1"), _make_control("C2"), _make_control("C3")]
        profile = AuditProfileConfig(
            description="Explicit",
            controls=["C1", "C3"],
        )
        result = resolve_profile_control_ids(profile, controls)
        assert result == ["C1", "C3"]

    def test_tag_filter_exact(self):
        controls = [
            _make_control("C1", level=1),
            _make_control("C2", level=2),
            _make_control("C3", level=1),
        ]
        profile = AuditProfileConfig(
            description="Level 1",
            tags={"level": 1},
        )
        result = resolve_profile_control_ids(profile, controls)
        assert result == ["C1", "C3"]

    def test_tag_filter_gte(self):
        controls = [
            _make_control("C1", severity=5.0),
            _make_control("C2", severity=8.0),
            _make_control("C3", severity=9.5),
        ]
        profile = AuditProfileConfig(
            description="High severity",
            tags={"security_severity_gte": 8.0},
        )
        result = resolve_profile_control_ids(profile, controls)
        assert result == ["C2", "C3"]

    def test_union_of_controls_and_tags(self):
        controls = [
            _make_control("C1", level=1),
            _make_control("C2", level=2),
            _make_control("C3", level=1),
        ]
        profile = AuditProfileConfig(
            description="Union",
            controls=["C2"],
            tags={"level": 1},
        )
        result = resolve_profile_control_ids(profile, controls)
        assert result == ["C1", "C2", "C3"]

    def test_invalid_control_id_skipped(self):
        controls = [_make_control("C1")]
        profile = AuditProfileConfig(
            description="Has invalid",
            controls=["C1", "NONEXISTENT"],
        )
        result = resolve_profile_control_ids(profile, controls)
        assert result == ["C1"]

    def test_empty_result(self):
        controls = [_make_control("C1", level=1)]
        profile = AuditProfileConfig(
            description="No match",
            tags={"level": 99},
        )
        result = resolve_profile_control_ids(profile, controls)
        assert result == []

    def test_deduplication(self):
        controls = [_make_control("C1", level=1)]
        profile = AuditProfileConfig(
            description="Dedupe",
            controls=["C1"],
            tags={"level": 1},
        )
        result = resolve_profile_control_ids(profile, controls)
        assert result == ["C1"]
