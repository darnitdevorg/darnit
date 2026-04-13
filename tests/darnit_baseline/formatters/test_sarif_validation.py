import json
from pathlib import Path

import jsonschema
import pytest

from darnit.core.models import AuditResult, CheckResult, CheckStatus
from darnit_baseline.formatters.sarif import generate_sarif_audit

SCHEMA_PATH = Path(__file__).parent / "fixtures" / "sarif-schema-2.1.0.json"

@pytest.fixture(scope="session")
def sarif_schema():
    if not SCHEMA_PATH.exists():
        pytest.skip(f"SARIF schema not found at {SCHEMA_PATH}")
    with open(SCHEMA_PATH) as f:
        return json.load(f)

def test_sarif_validation_all_pass(sarif_schema):
    """Test that a fully passing audit result produces valid SARIF."""
    result = AuditResult(
        owner="testorg",
        repo="testrepo",
        local_path="/path/to/repo",
        level=1,
        default_branch="main",
        all_results=[
            CheckResult(
                control_id="OSPS-VM-01.01",
                status=CheckStatus.PASS,
                message="Control passed successfully",
                source="builtin"
            ).to_dict(),
            CheckResult(
                control_id="OSPS-BL-01.01",
                status=CheckStatus.PASS,
                message="Another control passed",
                source="builtin"
            ).to_dict()
        ]
    )

    sarif_output = generate_sarif_audit(result, include_passing=True, include_na=False)
    jsonschema.validate(instance=sarif_output, schema=sarif_schema)

    assert sarif_output["version"] == "2.1.0"
    assert len(sarif_output["runs"]) == 1
    run = sarif_output["runs"][0]
    assert len(run["results"]) == 2
    assert "ruleId" in run["results"][0]

def test_sarif_validation_all_fail(sarif_schema):
    """Test that failing controls produce valid SARIF results."""
    result = AuditResult(
        owner="testorg",
        repo="testrepo",
        local_path="/path/to/repo",
        level=1,
        default_branch="main",
        all_results=[
            CheckResult(
                control_id="OSPS-VM-01.01",
                status=CheckStatus.FAIL,
                message="Vulnerability scan failed",
                source="builtin"
            ).to_dict()
        ]
    )

    sarif_output = generate_sarif_audit(result, include_passing=False, include_na=False)
    jsonschema.validate(instance=sarif_output, schema=sarif_schema)

    run = sarif_output["runs"][0]
    assert len(run["results"]) == 1
    res = run["results"][0]
    assert res["level"] == "error"
    assert res.get("message", {}).get("text") == "Vulnerability scan failed"

def test_sarif_validation_empty_results(sarif_schema):
    """Test that an empty audit returns valid SARIF."""
    result = AuditResult(
        owner="testorg",
        repo="testrepo",
        local_path="/path/to/repo",
        level=1,
        default_branch="main",
        all_results=[]
    )

    sarif_output = generate_sarif_audit(result, include_passing=True, include_na=True)
    jsonschema.validate(instance=sarif_output, schema=sarif_schema)

    assert len(sarif_output["runs"]) == 1
    assert len(sarif_output["runs"][0]["results"]) == 0

def test_sarif_validation_mixed_results(sarif_schema):
    """Test that a structurally mixed audit returns valid SARIF."""
    result = AuditResult(
        owner="testorg",
        repo="testrepo",
        local_path="/path/to/repo",
        level=1,
        default_branch="main",
        all_results=[
            CheckResult(
                control_id="OSPS-VM-01.01",
                status=CheckStatus.PASS,
                message="Passed",
                source="builtin"
            ).to_dict(),
            CheckResult(
                control_id="OSPS-BL-01.01",
                status=CheckStatus.FAIL,
                message="Failed issue",
                source="builtin"
            ).to_dict(),
            CheckResult(
                control_id="OSPS-SD-02.04",
                status=CheckStatus.ERROR,
                message="Exception during test",
                source="builtin"
            ).to_dict(),
            CheckResult(
                control_id="OSPS-SD-02.05",
                status=CheckStatus.NA,
                message="Not applicable",
                source="builtin"
            ).to_dict()
        ]
    )

    sarif_output = generate_sarif_audit(result, include_passing=True, include_na=False)
    jsonschema.validate(instance=sarif_output, schema=sarif_schema)

    run = sarif_output["runs"][0]
    assert len(run["results"]) == 3
    assert all("ruleIndex" in r and r["ruleIndex"] > -1 for r in run["results"])
    assert all("locations" in r for r in run["results"])
