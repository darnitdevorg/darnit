"""Tests for threat model generators."""

from darnit_baseline.threat_model.generators import (
    generate_json_summary,
    generate_markdown_threat_model,
    generate_mermaid_dfd,
    generate_sarif_threat_model,
)
from darnit_baseline.threat_model.models import (
    AssetInventory,
    AttackChain,
    AuthMechanism,
    CodeLocation,
    DataStore,
    EntryPoint,
    RankedControl,
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
    tid: str = "TM-S-001",
    category: StrideCategory = StrideCategory.SPOOFING,
    overall: float = 0.5,
    with_scenario: bool = True,
) -> Threat:
    t = Threat(
        id=tid,
        category=category,
        title=f"Test Threat {tid}",
        description="Test description",
        affected_assets=["ep-1"],
        attack_vector="Test vector",
        prerequisites=[],
        risk=_make_risk(overall),
        existing_controls=[],
        recommended_controls=["Control A", "Control B"],
        code_locations=[CodeLocation(file="src/app.py", line_start=10, line_end=10, annotation="test")],
        references=["REF-1"],
    )
    if with_scenario:
        t.exploitation_scenario = ["Step 1", "Step 2", "Step 3"]
        t.data_flow_impact = "client → endpoint → database"
        t.ranked_controls = [
            RankedControl(control="Use MFA", effectiveness="high", rationale="Prevents spoofing"),
            RankedControl(control="Add logging", effectiveness="medium", rationale="Enables detection"),
        ]
    return t


def _make_assets(
    num_entry_points: int = 2,
    num_data_stores: int = 1,
    with_auth: bool = False,
) -> AssetInventory:
    eps = [
        EntryPoint(
            id=f"ep-{i}",
            entry_type="api_route",
            path=f"/api/test{i}",
            method="GET",
            file="src/app.py",
            line=i * 10,
            authentication_required=(i % 2 == 0),
            framework="express",
        )
        for i in range(1, num_entry_points + 1)
    ]
    dss = [
        DataStore(
            id=f"ds-{i}",
            store_type="database",
            technology="postgresql",
            file="src/db.py",
            line=i * 5,
        )
        for i in range(1, num_data_stores + 1)
    ]
    auths = []
    if with_auth:
        auths = [AuthMechanism(id="auth-1", auth_type="jwt", file="src/auth.py", line=1, framework="express")]
    return AssetInventory(
        entry_points=eps,
        data_stores=dss,
        sensitive_data=[],
        secrets=[],
        authentication=auths,
        frameworks_detected=["express"],
    )


class TestMarkdownDetailed:
    """Verify detailed Markdown output."""

    def test_contains_exploitation_scenario(self):
        threat = _make_threat()
        assets = _make_assets()
        md = generate_markdown_threat_model("/repo", assets, [threat], [], ["express"])
        assert "Exploitation Scenario" in md
        assert "Step 1" in md
        assert "Step 2" in md
        assert "Step 3" in md

    def test_contains_data_flow_impact(self):
        threat = _make_threat()
        assets = _make_assets()
        md = generate_markdown_threat_model("/repo", assets, [threat], [], ["express"])
        assert "Data Flow Impact" in md
        assert "client → endpoint → database" in md

    def test_contains_ranked_controls_table(self):
        threat = _make_threat()
        assets = _make_assets()
        md = generate_markdown_threat_model("/repo", assets, [threat], [], ["express"])
        assert "| Control | Effectiveness | Rationale |" in md
        assert "Use MFA" in md
        assert "high" in md

    def test_empty_category_explanation(self):
        # Only spoofing threat — other categories should show explanation
        threat = _make_threat(category=StrideCategory.SPOOFING)
        assets = _make_assets()
        md = generate_markdown_threat_model("/repo", assets, [threat], [], ["express"])
        assert "No threats identified." in md
        assert "Tampering" in md
        assert "Repudiation" in md

    def test_all_six_categories_present(self):
        threat = _make_threat(category=StrideCategory.SPOOFING)
        assets = _make_assets()
        md = generate_markdown_threat_model("/repo", assets, [threat], [], ["express"])
        for category_name in ["Spoofing", "Tampering", "Repudiation", "Information Disclosure", "Denial Of Service", "Elevation Of Privilege"]:
            assert category_name in md

    def test_attack_chains_section(self):
        chain = AttackChain(
            id="TC-001",
            name="Test Chain",
            description="Test chain desc",
            threat_ids=["TM-S-001", "TM-I-001"],
            categories=[StrideCategory.SPOOFING, StrideCategory.INFORMATION_DISCLOSURE],
            shared_assets=["ep-1"],
            composite_risk=_make_risk(0.85),
        )
        assets = _make_assets()
        md = generate_markdown_threat_model("/repo", assets, [], [], ["express"], attack_chains=[chain])
        assert "Attack Chains" in md
        assert "TC-001" in md
        assert "Test Chain" in md

    def test_no_chains_message(self):
        assets = _make_assets()
        md = generate_markdown_threat_model("/repo", assets, [], [], ["express"], attack_chains=[])
        assert "No compound attack paths identified." in md


class TestMarkdownSummary:
    """Verify summary Markdown output."""

    def test_summary_is_shorter(self):
        threat = _make_threat()
        assets = _make_assets()
        detailed = generate_markdown_threat_model("/repo", assets, [threat], [], ["express"], detail_level="detailed")
        summary = generate_markdown_threat_model("/repo", assets, [threat], [], ["express"], detail_level="summary")
        assert len(summary) < len(detailed)

    def test_summary_contains_title_risk_control(self):
        threat = _make_threat()
        assets = _make_assets()
        md = generate_markdown_threat_model("/repo", assets, [threat], [], ["express"], detail_level="summary")
        assert "TM-S-001" in md
        assert "0.50" in md
        assert "Use MFA" in md

    def test_summary_omits_detailed_sections(self):
        threat = _make_threat()
        assets = _make_assets()
        md = generate_markdown_threat_model("/repo", assets, [threat], [], ["express"], detail_level="summary")
        assert "Exploitation Scenario" not in md
        assert "Data Flow Impact" not in md
        assert "| Control | Effectiveness | Rationale |" not in md

    def test_summary_omits_dfd(self):
        threat = _make_threat()
        assets = _make_assets()
        md = generate_markdown_threat_model("/repo", assets, [threat], [], ["express"], detail_level="summary")
        assert "```mermaid" not in md

    def test_summary_omits_attack_chains(self):
        chain = AttackChain(
            id="TC-001",
            name="Test Chain",
            description="desc",
            threat_ids=["TM-S-001"],
            categories=[StrideCategory.SPOOFING],
            shared_assets=["ep-1"],
            composite_risk=_make_risk(0.85),
        )
        assets = _make_assets()
        md = generate_markdown_threat_model("/repo", assets, [], [], ["express"], detail_level="summary", attack_chains=[chain])
        assert "Attack Chains" not in md


class TestMermaidDFD:
    """Verify Mermaid data-flow diagram generation."""

    def test_diagram_when_assets_exist(self):
        assets = _make_assets(num_entry_points=2, num_data_stores=1)
        dfd = generate_mermaid_dfd(assets, [])
        assert "```mermaid" in dfd
        assert "flowchart LR" in dfd

    def test_trust_boundaries_with_auth(self):
        assets = _make_assets(num_entry_points=4, with_auth=True)
        dfd = generate_mermaid_dfd(assets, [])
        assert "Public Zone" in dfd or "Authenticated Zone" in dfd

    def test_empty_when_no_assets(self):
        assets = AssetInventory(
            entry_points=[], data_stores=[], sensitive_data=[],
            secrets=[], authentication=[], frameworks_detected=[],
        )
        dfd = generate_mermaid_dfd(assets, [])
        assert dfd == ""

    def test_simplification_note_for_large_diagrams(self):
        # Create >50 nodes worth of entry points
        eps = [
            EntryPoint(
                id=f"ep-{i}", entry_type="api_route", path=f"/api/{i}",
                method="GET", file="src/app.py", line=i,
                authentication_required=False, framework="express",
            )
            for i in range(55)
        ]
        assets = AssetInventory(
            entry_points=eps,
            data_stores=[DataStore(id="ds-1", store_type="database", technology="pg", file="db.py", line=1)],
            sensitive_data=[], secrets=[], authentication=[], frameworks_detected=[],
        )
        dfd = generate_mermaid_dfd(assets, [])
        assert "simplified" in dfd.lower() or "Note" in dfd


class TestFindingGrouping:
    """Verify >10 finding grouping in Markdown."""

    def test_groups_when_over_10_threats(self):
        threats = [
            _make_threat(tid=f"TM-S-{i:03d}", category=StrideCategory.SPOOFING, overall=0.5 - i * 0.01)
            for i in range(15)
        ]
        assets = _make_assets()
        md = generate_markdown_threat_model("/repo", assets, threats, [], ["express"])
        assert "15 threats identified" in md
        assert "additional" in md.lower()


class TestSARIFNewFields:
    """Verify SARIF includes new fields."""

    def test_sarif_has_exploitation_scenario(self):
        threat = _make_threat()
        sarif = generate_sarif_threat_model("/repo", [threat])
        rule = sarif["runs"][0]["tool"]["driver"]["rules"][0]
        assert "exploitationScenario" in rule["properties"]
        assert len(rule["properties"]["exploitationScenario"]) == 3

    def test_sarif_has_attack_chains(self):
        chain = AttackChain(
            id="TC-001", name="Test", description="desc",
            threat_ids=["T1"], categories=[StrideCategory.SPOOFING],
            shared_assets=["ep-1"], composite_risk=_make_risk(),
        )
        sarif = generate_sarif_threat_model("/repo", [], attack_chains=[chain])
        chains = sarif["runs"][0]["properties"]["attackChains"]
        assert len(chains) == 1
        assert chains[0]["id"] == "TC-001"


class TestJSONNewFields:
    """Verify JSON includes new fields."""

    def test_json_has_exploitation_scenario(self):
        threat = _make_threat()
        assets = _make_assets()
        result = generate_json_summary("/repo", ["express"], assets, [threat], [])
        t = result["threats"][0]
        assert "exploitation_scenario" in t
        assert len(t["exploitation_scenario"]) == 3
        assert "data_flow_impact" in t
        assert "ranked_controls" in t

    def test_json_has_attack_chains(self):
        chain = AttackChain(
            id="TC-001", name="Test", description="desc",
            threat_ids=["T1"], categories=[StrideCategory.SPOOFING],
            shared_assets=["ep-1"], composite_risk=_make_risk(),
        )
        assets = _make_assets()
        result = generate_json_summary("/repo", [], assets, [], [], attack_chains=[chain])
        assert len(result["attack_chains"]) == 1
        assert result["attack_chains"][0]["id"] == "TC-001"
