"""Tests for exploitation scenario templates."""

from darnit_baseline.threat_model.scenarios import SCENARIO_TEMPLATES, get_scenario


class TestScenarioTemplates:
    """Verify scenario template bank coverage and quality."""

    EXPECTED_SUB_TYPES = [
        "unauthenticated_endpoint",
        "hardcoded_secret",
        "injection_sql",
        "injection_xss",
        "injection_command",
        "injection_path_traversal",
        "injection_ssrf",
        "injection_code",
        "missing_rate_limit",
        "missing_audit_log",
        "server_action_no_auth",
    ]

    def test_all_sub_types_have_templates(self):
        for sub_type in self.EXPECTED_SUB_TYPES:
            assert sub_type in SCENARIO_TEMPLATES, f"Missing template for {sub_type}"

    def test_each_template_has_at_least_3_steps(self):
        for sub_type, template in SCENARIO_TEMPLATES.items():
            assert "steps" in template, f"No steps in {sub_type}"
            assert len(template["steps"]) >= 3, (
                f"{sub_type} has {len(template['steps'])} steps, need >=3"
            )

    def test_each_template_has_data_flow_pattern(self):
        for sub_type, template in SCENARIO_TEMPLATES.items():
            assert "data_flow_pattern" in template, f"No data_flow_pattern in {sub_type}"
            assert len(template["data_flow_pattern"]) > 0

    def test_each_template_has_control_rankings(self):
        for sub_type, template in SCENARIO_TEMPLATES.items():
            assert "control_rankings" in template, f"No control_rankings in {sub_type}"
            assert len(template["control_rankings"]) >= 1
            for rc in template["control_rankings"]:
                assert rc.effectiveness in ("high", "medium", "low")
                assert len(rc.control) > 0
                assert len(rc.rationale) > 0


class TestGetScenario:
    """Verify get_scenario function behavior."""

    def test_returns_template_for_known_type(self):
        result = get_scenario("unauthenticated_endpoint")
        assert result is not None
        assert "steps" in result

    def test_returns_none_for_unknown_type(self):
        result = get_scenario("nonexistent_type")
        assert result is None

    def test_returns_none_for_empty_string(self):
        result = get_scenario("")
        assert result is None
