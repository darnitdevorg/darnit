"""Tests for darnit.threat_model.models module."""

import pytest

from darnit.threat_model.models import (
    AssetInventory,
    AuthMechanism,
    CodeLocation,
    DataStore,
    EntryPoint,
    RiskLevel,
    RiskScore,
    SecretReference,
    SensitiveData,
    StrideCategory,
    Threat,
    ThreatAnalysis,
)


class TestStrideCategory:
    """Tests for StrideCategory enum."""

    @pytest.mark.unit
    def test_all_categories_exist(self):
        """Test all STRIDE categories are defined."""
        assert StrideCategory.SPOOFING.value == "spoofing"
        assert StrideCategory.TAMPERING.value == "tampering"
        assert StrideCategory.REPUDIATION.value == "repudiation"
        assert StrideCategory.INFORMATION_DISCLOSURE.value == "information_disclosure"
        assert StrideCategory.DENIAL_OF_SERVICE.value == "denial_of_service"
        assert StrideCategory.ELEVATION_OF_PRIVILEGE.value == "elevation_of_privilege"

    @pytest.mark.unit
    def test_category_count(self):
        """Test we have exactly 6 STRIDE categories."""
        assert len(StrideCategory) == 6


class TestRiskLevel:
    """Tests for RiskLevel enum."""

    @pytest.mark.unit
    def test_all_levels_exist(self):
        """Test all risk levels are defined."""
        assert RiskLevel.CRITICAL.value == "critical"
        assert RiskLevel.HIGH.value == "high"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.INFORMATIONAL.value == "informational"

    @pytest.mark.unit
    def test_level_count(self):
        """Test we have exactly 5 risk levels."""
        assert len(RiskLevel) == 5


class TestCodeLocation:
    """Tests for CodeLocation dataclass."""

    @pytest.mark.unit
    def test_basic_creation(self):
        """Test creating a CodeLocation."""
        loc = CodeLocation(
            file="src/api.py",
            line_start=10,
            line_end=15
        )
        assert loc.file == "src/api.py"
        assert loc.line_start == 10
        assert loc.line_end == 15
        assert loc.snippet == ""
        assert loc.annotation == ""

    @pytest.mark.unit
    def test_with_snippet(self):
        """Test CodeLocation with snippet."""
        loc = CodeLocation(
            file="src/api.py",
            line_start=10,
            line_end=12,
            snippet="@app.route('/api')",
            annotation="API endpoint"
        )
        assert loc.snippet == "@app.route('/api')"
        assert loc.annotation == "API endpoint"


class TestEntryPoint:
    """Tests for EntryPoint dataclass."""

    @pytest.mark.unit
    def test_basic_creation(self):
        """Test creating an EntryPoint."""
        ep = EntryPoint(
            id="EP-001",
            entry_type="api_route",
            path="/api/users",
            method="GET",
            file="src/routes.py",
            line=25,
            authentication_required=True,
            framework="flask"
        )
        assert ep.id == "EP-001"
        assert ep.entry_type == "api_route"
        assert ep.path == "/api/users"
        assert ep.method == "GET"
        assert ep.authentication_required is True
        assert ep.framework == "flask"
        assert ep.parameters == []

    @pytest.mark.unit
    def test_with_parameters(self):
        """Test EntryPoint with parameters."""
        ep = EntryPoint(
            id="EP-002",
            entry_type="api_route",
            path="/api/users/{id}",
            method="GET",
            file="src/routes.py",
            line=30,
            authentication_required=True,
            framework="fastapi",
            parameters=[{"name": "id", "type": "int", "source": "path"}]
        )
        assert len(ep.parameters) == 1
        assert ep.parameters[0]["name"] == "id"


class TestDataStore:
    """Tests for DataStore dataclass."""

    @pytest.mark.unit
    def test_basic_creation(self):
        """Test creating a DataStore."""
        ds = DataStore(
            id="DS-001",
            store_type="database",
            technology="postgresql",
            file="src/db.py",
            line=10
        )
        assert ds.id == "DS-001"
        assert ds.store_type == "database"
        assert ds.technology == "postgresql"
        assert ds.contains_pii is False
        assert ds.encryption_at_rest is False

    @pytest.mark.unit
    def test_with_pii(self):
        """Test DataStore containing PII."""
        ds = DataStore(
            id="DS-002",
            store_type="database",
            technology="mysql",
            file="src/models.py",
            line=50,
            contains_pii=True,
            contains_financial=True
        )
        assert ds.contains_pii is True
        assert ds.contains_financial is True


class TestSensitiveData:
    """Tests for SensitiveData dataclass."""

    @pytest.mark.unit
    def test_basic_creation(self):
        """Test creating SensitiveData."""
        sd = SensitiveData(
            id="SD-001",
            data_type="pii",
            field_name="email",
            file="src/models/user.py",
            line=15
        )
        assert sd.id == "SD-001"
        assert sd.data_type == "pii"
        assert sd.field_name == "email"
        assert sd.context == ""

    @pytest.mark.unit
    def test_with_context(self):
        """Test SensitiveData with context."""
        sd = SensitiveData(
            id="SD-002",
            data_type="financial",
            field_name="credit_card",
            file="src/payment.py",
            line=42,
            context="Payment processing"
        )
        assert sd.context == "Payment processing"


class TestSecretReference:
    """Tests for SecretReference dataclass."""

    @pytest.mark.unit
    def test_hardcoded_secret(self):
        """Test hardcoded secret reference."""
        sr = SecretReference(
            id="SR-001",
            secret_type="hardcoded",
            name="API_KEY",
            file="src/config.py",
            line=5,
            severity="critical"
        )
        assert sr.secret_type == "hardcoded"
        assert sr.severity == "critical"

    @pytest.mark.unit
    def test_env_reference(self):
        """Test environment variable reference."""
        sr = SecretReference(
            id="SR-002",
            secret_type="env_reference",
            name="DATABASE_URL",
            file="src/db.py",
            line=3
        )
        assert sr.secret_type == "env_reference"
        assert sr.severity == "high"


class TestAuthMechanism:
    """Tests for AuthMechanism dataclass."""

    @pytest.mark.unit
    def test_basic_creation(self):
        """Test creating an AuthMechanism."""
        auth = AuthMechanism(
            id="AM-001",
            auth_type="jwt",
            file="src/auth.py",
            line=20,
            framework="express"
        )
        assert auth.auth_type == "jwt"
        assert auth.framework == "express"
        assert auth.assets == []

    @pytest.mark.unit
    def test_with_assets(self):
        """Test AuthMechanism with protected assets."""
        auth = AuthMechanism(
            id="AM-002",
            auth_type="nextauth",
            file="src/auth/config.ts",
            line=10,
            framework="nextjs",
            assets=["EP-001", "EP-002", "EP-003"]
        )
        assert len(auth.assets) == 3


class TestRiskScore:
    """Tests for RiskScore dataclass."""

    @pytest.mark.unit
    def test_basic_creation(self):
        """Test creating a RiskScore."""
        score = RiskScore(
            overall=7.5,
            level=RiskLevel.HIGH,
            likelihood=0.8,
            impact=0.9,
            control_effectiveness=0.5
        )
        assert score.overall == 7.5
        assert score.level == RiskLevel.HIGH
        assert score.likelihood == 0.8
        assert score.factors == {}

    @pytest.mark.unit
    def test_with_factors(self):
        """Test RiskScore with factors."""
        score = RiskScore(
            overall=5.0,
            level=RiskLevel.MEDIUM,
            likelihood=0.5,
            impact=0.6,
            control_effectiveness=0.7,
            factors={"authentication": True, "encryption": False}
        )
        assert score.factors["authentication"] is True


class TestThreat:
    """Tests for Threat dataclass."""

    @pytest.mark.unit
    def test_basic_creation(self):
        """Test creating a Threat."""
        threat = Threat(
            id="T-001",
            category=StrideCategory.SPOOFING,
            title="Identity Spoofing",
            description="Attacker may impersonate legitimate user",
            affected_assets=["EP-001", "AM-001"],
            attack_vector="Credential theft",
            prerequisites=["Network access"],
            risk=RiskScore(
                overall=7.0,
                level=RiskLevel.HIGH,
                likelihood=0.7,
                impact=0.8,
                control_effectiveness=0.5
            ),
            existing_controls=["Password policy"],
            recommended_controls=["MFA"],
            code_locations=[]
        )
        assert threat.id == "T-001"
        assert threat.category == StrideCategory.SPOOFING
        assert len(threat.affected_assets) == 2
        assert threat.references == []


class TestAssetInventory:
    """Tests for AssetInventory dataclass."""

    @pytest.mark.unit
    def test_empty_inventory(self):
        """Test creating empty AssetInventory."""
        inventory = AssetInventory(
            entry_points=[],
            data_stores=[],
            sensitive_data=[],
            secrets=[],
            authentication=[],
            frameworks_detected=[]
        )
        assert len(inventory.entry_points) == 0
        assert len(inventory.frameworks_detected) == 0
        assert inventory.external_services == []

    @pytest.mark.unit
    def test_populated_inventory(self):
        """Test AssetInventory with assets."""
        ep = EntryPoint(
            id="EP-001",
            entry_type="api_route",
            path="/api/test",
            method="GET",
            file="test.py",
            line=1,
            authentication_required=False,
            framework="flask"
        )
        inventory = AssetInventory(
            entry_points=[ep],
            data_stores=[],
            sensitive_data=[],
            secrets=[],
            authentication=[],
            frameworks_detected=["flask"]
        )
        assert len(inventory.entry_points) == 1
        assert "flask" in inventory.frameworks_detected


class TestThreatAnalysis:
    """Tests for ThreatAnalysis dataclass."""

    @pytest.mark.unit
    def test_basic_creation(self):
        """Test creating a ThreatAnalysis."""
        analysis = ThreatAnalysis(
            methodology="STRIDE",
            threats=[],
            control_gaps=[],
            summary={"total_threats": 0, "high_risk": 0}
        )
        assert analysis.methodology == "STRIDE"
        assert len(analysis.threats) == 0
        assert analysis.summary["total_threats"] == 0
