"""Tests for threat model data model extensions."""

from darnit_baseline.threat_model.models import (
    AttackChain,
    DetailLevel,
    RankedControl,
    RiskLevel,
    RiskScore,
    StrideCategory,
    Threat,
    ThreatAnalysis,
)


def _make_risk() -> RiskScore:
    return RiskScore(
        overall=0.5,
        level=RiskLevel.MEDIUM,
        likelihood=0.6,
        impact=0.5,
        control_effectiveness=0.0,
    )


class TestThreatBackwardCompat:
    """Verify Threat can be constructed without new fields."""

    def test_threat_without_new_fields(self):
        t = Threat(
            id="TM-S-001",
            category=StrideCategory.SPOOFING,
            title="Test",
            description="desc",
            affected_assets=[],
            attack_vector="vec",
            prerequisites=[],
            risk=_make_risk(),
            existing_controls=[],
            recommended_controls=["ctrl"],
            code_locations=[],
        )
        assert t.exploitation_scenario == []
        assert t.data_flow_impact == ""
        assert t.ranked_controls == []
        assert t.attack_chain_ids == []

    def test_threat_with_new_fields(self):
        rc = RankedControl(control="Use MFA", effectiveness="high", rationale="Prevents spoofing")
        t = Threat(
            id="TM-S-001",
            category=StrideCategory.SPOOFING,
            title="Test",
            description="desc",
            affected_assets=[],
            attack_vector="vec",
            prerequisites=[],
            risk=_make_risk(),
            existing_controls=[],
            recommended_controls=[],
            code_locations=[],
            exploitation_scenario=["Step 1", "Step 2", "Step 3"],
            data_flow_impact="client → endpoint → db",
            ranked_controls=[rc],
            attack_chain_ids=["TC-001"],
        )
        assert len(t.exploitation_scenario) == 3
        assert t.data_flow_impact == "client → endpoint → db"
        assert t.ranked_controls[0].effectiveness == "high"
        assert t.attack_chain_ids == ["TC-001"]


class TestThreatAnalysisBackwardCompat:
    """Verify ThreatAnalysis can be constructed without new fields."""

    def test_without_attack_chains(self):
        ta = ThreatAnalysis(
            methodology="STRIDE",
            threats=[],
            control_gaps=[],
            summary={},
        )
        assert ta.attack_chains == []

    def test_with_attack_chains(self):
        chain = AttackChain(
            id="TC-001",
            name="Test Chain",
            description="desc",
            threat_ids=["TM-S-001", "TM-I-002"],
            categories=[StrideCategory.SPOOFING, StrideCategory.INFORMATION_DISCLOSURE],
            shared_assets=["ep-1"],
            composite_risk=_make_risk(),
        )
        ta = ThreatAnalysis(
            methodology="STRIDE",
            threats=[],
            control_gaps=[],
            summary={},
            attack_chains=[chain],
        )
        assert len(ta.attack_chains) == 1
        assert ta.attack_chains[0].id == "TC-001"


class TestNewDataclasses:
    """Verify new dataclasses work correctly."""

    def test_ranked_control(self):
        rc = RankedControl(control="Enable WAF", effectiveness="medium", rationale="Filters malicious traffic")
        assert rc.control == "Enable WAF"
        assert rc.effectiveness == "medium"

    def test_attack_chain(self):
        chain = AttackChain(
            id="TC-001",
            name="Credential Theft → Data Exfiltration",
            description="desc",
            threat_ids=["TM-S-001", "TM-I-002"],
            categories=[StrideCategory.SPOOFING, StrideCategory.INFORMATION_DISCLOSURE],
            shared_assets=["ep-1"],
            composite_risk=_make_risk(),
        )
        assert len(chain.threat_ids) == 2
        assert len(chain.categories) == 2

    def test_detail_level_enum(self):
        assert DetailLevel.SUMMARY.value == "summary"
        assert DetailLevel.DETAILED.value == "detailed"
