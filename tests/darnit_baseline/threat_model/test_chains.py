"""Tests for attack chain detection."""

from darnit_baseline.threat_model.chains import (
    CHAIN_PATTERNS,
    calculate_composite_risk,
    detect_attack_chains,
)
from darnit_baseline.threat_model.models import (
    AssetInventory,
    CodeLocation,
    EntryPoint,
    RiskLevel,
    RiskScore,
    StrideCategory,
    Threat,
)


def _make_risk(overall: float = 0.5) -> RiskScore:
    if overall >= 0.8:
        level = RiskLevel.CRITICAL
    elif overall >= 0.6:
        level = RiskLevel.HIGH
    elif overall >= 0.4:
        level = RiskLevel.MEDIUM
    elif overall >= 0.2:
        level = RiskLevel.LOW
    else:
        level = RiskLevel.INFORMATIONAL
    return RiskScore(overall=overall, level=level, likelihood=0.6, impact=0.5, control_effectiveness=0.0)


def _make_threat(
    tid: str,
    category: StrideCategory,
    affected_assets: list[str] | None = None,
    code_file: str = "src/app.py",
    overall: float = 0.5,
) -> Threat:
    return Threat(
        id=tid,
        category=category,
        title=f"Test {tid}",
        description="desc",
        affected_assets=affected_assets or [],
        attack_vector="vec",
        prerequisites=[],
        risk=_make_risk(overall),
        existing_controls=[],
        recommended_controls=["ctrl"],
        code_locations=[CodeLocation(file=code_file, line_start=1, line_end=1)],
    )


def _make_assets(entry_points: list[EntryPoint] | None = None) -> AssetInventory:
    return AssetInventory(
        entry_points=entry_points or [],
        data_stores=[],
        sensitive_data=[],
        secrets=[],
        authentication=[],
        frameworks_detected=[],
    )


class TestChainPatterns:
    """Verify chain pattern definitions."""

    def test_five_patterns_defined(self):
        assert len(CHAIN_PATTERNS) == 5

    def test_each_pattern_has_name_and_description(self):
        for pair, pattern in CHAIN_PATTERNS.items():
            assert "name" in pattern
            assert "description" in pattern
            assert len(pattern["name"]) > 0
            assert len(pattern["description"]) > 0

    def test_each_pattern_has_two_categories(self):
        for pair in CHAIN_PATTERNS:
            assert len(pair) == 2
            for cat in pair:
                assert isinstance(cat, StrideCategory)


class TestCompositeRisk:
    """Verify composite risk score formula."""

    def test_basic_formula(self):
        t1 = _make_threat("T1", StrideCategory.SPOOFING, overall=0.8)
        t2 = _make_threat("T2", StrideCategory.INFORMATION_DISCLOSURE, overall=0.5)
        result = calculate_composite_risk([t1, t2])
        # max(0.8, 0.5) + 0.1 * 0.5 = 0.85
        assert result.overall == 0.85

    def test_capped_at_1(self):
        t1 = _make_threat("T1", StrideCategory.SPOOFING, overall=0.95)
        t2 = _make_threat("T2", StrideCategory.INFORMATION_DISCLOSURE, overall=0.9)
        result = calculate_composite_risk([t1, t2])
        assert result.overall <= 1.0

    def test_equal_scores(self):
        t1 = _make_threat("T1", StrideCategory.SPOOFING, overall=0.5)
        t2 = _make_threat("T2", StrideCategory.INFORMATION_DISCLOSURE, overall=0.5)
        result = calculate_composite_risk([t1, t2])
        # max(0.5) + 0.1 * 0.5 = 0.55
        assert result.overall == 0.55

    def test_risk_level_derived(self):
        t1 = _make_threat("T1", StrideCategory.SPOOFING, overall=0.8)
        t2 = _make_threat("T2", StrideCategory.INFORMATION_DISCLOSURE, overall=0.5)
        result = calculate_composite_risk([t1, t2])
        assert result.level == RiskLevel.CRITICAL  # 0.85 >= 0.8


class TestDetectAttackChains:
    """Verify chain detection logic."""

    def test_detects_chain_with_shared_assets(self):
        # S + I with shared file
        t1 = _make_threat("TM-S-001", StrideCategory.SPOOFING, affected_assets=["ep-1"], code_file="src/api.py")
        t2 = _make_threat("TM-I-001", StrideCategory.INFORMATION_DISCLOSURE, affected_assets=["ep-1"], code_file="src/api.py")
        assets = _make_assets()
        chains = detect_attack_chains([t1, t2], assets)
        assert len(chains) >= 1
        assert chains[0].id == "TC-001"
        assert len(chains[0].threat_ids) == 2

    def test_no_chain_without_shared_assets(self):
        t1 = _make_threat("TM-S-001", StrideCategory.SPOOFING, affected_assets=["ep-1"], code_file="src/a.py")
        t2 = _make_threat("TM-I-001", StrideCategory.INFORMATION_DISCLOSURE, affected_assets=["ep-2"], code_file="src/b.py")
        assets = _make_assets()
        chains = detect_attack_chains([t1, t2], assets)
        assert len(chains) == 0

    def test_no_chain_with_single_category(self):
        t1 = _make_threat("TM-S-001", StrideCategory.SPOOFING, code_file="src/a.py")
        t2 = _make_threat("TM-S-002", StrideCategory.SPOOFING, code_file="src/a.py")
        assets = _make_assets()
        chains = detect_attack_chains([t1, t2], assets)
        assert len(chains) == 0

    def test_back_references_chain_ids(self):
        t1 = _make_threat("TM-S-001", StrideCategory.SPOOFING, affected_assets=["ep-1"], code_file="src/api.py")
        t2 = _make_threat("TM-I-001", StrideCategory.INFORMATION_DISCLOSURE, affected_assets=["ep-1"], code_file="src/api.py")
        assets = _make_assets()
        chains = detect_attack_chains([t1, t2], assets)
        if chains:
            chain_id = chains[0].id
            # At least one threat should have the chain ID back-referenced
            assert chain_id in t1.attack_chain_ids or chain_id in t2.attack_chain_ids

    def test_empty_result_when_no_threats(self):
        assets = _make_assets()
        chains = detect_attack_chains([], assets)
        assert chains == []
