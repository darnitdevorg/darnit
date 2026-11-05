"""Tests for baseline implementation audit profiles."""


from darnit.config.framework_schema import AuditProfileConfig


class TestBaselineProfiles:
    """Tests for OpenSSF Baseline audit profile definitions in TOML."""

    def test_profiles_load_from_toml(self):
        """Verify profiles section parses from openssf-baseline.toml."""
        from darnit.config.merger import load_framework_by_name

        config = load_framework_by_name("openssf-baseline")
        assert config.audit_profiles is not None
        assert len(config.audit_profiles) >= 3

    def test_level1_quick_profile(self):
        """level1_quick profile uses tag filter for level 1."""
        from darnit.config.merger import load_framework_by_name

        config = load_framework_by_name("openssf-baseline")
        profile = config.audit_profiles["level1_quick"]
        assert profile.tags == {"level": 1}
        assert profile.controls == []

    def test_access_control_profile(self):
        """access_control profile filters by domain."""
        from darnit.config.merger import load_framework_by_name

        config = load_framework_by_name("openssf-baseline")
        profile = config.audit_profiles["access_control"]
        assert profile.tags == {"domain": "AC"}
        assert profile.controls == []

    def test_security_critical_profile(self):
        """security_critical profile uses gte tag filter."""
        from darnit.config.merger import load_framework_by_name

        config = load_framework_by_name("openssf-baseline")
        profile = config.audit_profiles["security_critical"]
        assert "security_severity_gte" in profile.tags

    def test_implementation_get_audit_profiles(self):
        """OSPSBaselineImplementation.get_audit_profiles() returns profiles."""
        from darnit_baseline.implementation import OSPSBaselineImplementation

        impl = OSPSBaselineImplementation()
        profiles = impl.get_audit_profiles()
        assert profiles is not None
        assert "level1_quick" in profiles
        assert isinstance(profiles["level1_quick"], AuditProfileConfig)

    def test_access_control_profile_resolves_all_ac_controls(self):
        """Profile control IDs resolve against actual controls we obtain via the tag filter."""
        from darnit.config.control_loader import load_controls_from_framework
        from darnit.config.merger import load_framework_by_name
        from darnit.config.profile_resolver import resolve_profile_control_ids

        config = load_framework_by_name("openssf-baseline")
        controls = load_controls_from_framework(config)

        profile = config.audit_profiles["access_control"]
        result = resolve_profile_control_ids(profile, controls)
        expected = {control.control_id for control in controls if control.tags.get("domain") == "AC"}
        assert expected
        assert set(result) == expected
