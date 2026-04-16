import json
import urllib.request
from pathlib import Path

import pytest

try:
    import jsonschema

    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

from darnit.core.models import AuditResult
from darnit_baseline.formatters.sarif import generate_sarif_audit

SARIF_SCHEMA_URL = (
    "https://docs.oasis-open.org/sarif/sarif/v2.1.0"
    "/errata01/os/schemas/sarif-schema-2.1.0.json"
)
CACHE_DIR = Path(".pytest_cache")
SCHEMA_PATH = CACHE_DIR / "sarif-schema-2.1.0.json"


@pytest.fixture(scope="session")
def sarif_schema():
    """Download and cache the official SARIF schema for validation tests.

    Skips only when ``jsonschema`` is not installed (e.g. minimal test
    environment).  When ``jsonschema`` IS available (CI), a download
    failure is a hard error — this prevents CI from silently skipping
    schema validation when the URL is temporarily unreachable.
    """
    if not HAS_JSONSCHEMA:
        pytest.skip("jsonschema is not installed, skipping strict validation")

    if not SCHEMA_PATH.exists():
        CACHE_DIR.mkdir(exist_ok=True, parents=True)
        # Hard failure when jsonschema IS installed — don't let CI
        # silently skip validation because of a transient network issue.
        with urllib.request.urlopen(SARIF_SCHEMA_URL, timeout=30) as response:
            schema_data = json.loads(response.read().decode())
            with open(SCHEMA_PATH, "w") as f:
                json.dump(schema_data, f)

    with open(SCHEMA_PATH) as f:
        return json.load(f)


def test_sarif_empty_results(sarif_schema):
    """Test generating SARIF with no results."""
    audit = AuditResult(
        owner="test-owner", repo="test-repo", local_path="/tmp/test", level=1, default_branch="main", all_results=[]
    )
    result = generate_sarif_audit(audit)

    assert result["version"] == "2.1.0"
    assert "runs" in result
    assert len(result["runs"]) == 1

    if sarif_schema:
        jsonschema.validate(instance=result, schema=sarif_schema)


def test_sarif_all_pass(sarif_schema):
    """Test generating SARIF with all passing results."""
    audit = AuditResult(
        owner="test-owner",
        repo="test-repo",
        local_path="/tmp/test",
        level=1,
        default_branch="main",
        all_results=[
            {
                "id": "OSPS-AC-01.01",
                "status": "PASS",
                "details": "MFA is required",
                "level": 1,
            },
            {
                "id": "OSPS-RE-01.02",
                "status": "PASS",
                "details": "Signatures exist",
                "level": 1,
            },
        ],
    )
    result = generate_sarif_audit(audit, include_passing=True)

    assert len(result["runs"][0]["results"]) == 2
    # Ensure all rules referenced in results are defined in the tool rules
    rule_ids = {r["id"] for r in result["runs"][0]["tool"]["driver"]["rules"]}
    for res in result["runs"][0]["results"]:
        assert res["ruleId"] in rule_ids

    if sarif_schema:
        jsonschema.validate(instance=result, schema=sarif_schema)


def test_sarif_all_fail(sarif_schema):
    """Test generating SARIF with failing results."""
    audit = AuditResult(
        owner="test-owner",
        repo="test-repo",
        local_path="/tmp/test",
        level=1,
        default_branch="main",
        all_results=[
            {
                "id": "OSPS-AC-01.01",
                "status": "FAIL",
                "details": "MFA is NOT required",
                "level": 1,
            }
        ],
    )
    result = generate_sarif_audit(audit)

    assert len(result["runs"][0]["results"]) == 1
    res = result["runs"][0]["results"][0]
    assert res["level"] == "error"
    assert "MFA is NOT required" in res["message"]["text"]

    if sarif_schema:
        jsonschema.validate(instance=result, schema=sarif_schema)


def test_sarif_mixed_levels(sarif_schema):
    """Test generating SARIF with mixed result states."""
    audit = AuditResult(
        owner="test-owner",
        repo="test-repo",
        local_path="/tmp/test",
        level=1,
        default_branch="main",
        all_results=[
            {
                "id": "OSPS-AC-01.01",
                "status": "FAIL",
                "details": "Failed AC",
                "level": 1,
            },
            {
                "id": "OSPS-RE-01.02",
                "status": "WARN",
                "details": "Warning on setup",
                "level": 2,
            },
            {
                "id": "OSPS-GD-01.01",
                "status": "PASS",
                "details": "Passing",
                "level": 1,
            },
        ],
    )
    # Don't include passing
    result = generate_sarif_audit(audit, include_passing=False)

    results = result["runs"][0]["results"]
    assert len(results) == 2  # WARN and FAIL only

    levels = {r["level"] for r in results}
    assert "error" in levels
    assert "warning" in levels

    if sarif_schema:
        jsonschema.validate(instance=result, schema=sarif_schema)


def test_sarif_structure_and_location():
    """Test specific expected fields without schema check to ensure manual coverage."""
    audit = AuditResult(
        owner="test-owner",
        repo="test-repo",
        local_path="/tmp/test",
        level=1,
        default_branch="main",
        all_results=[
            {
                "id": "OSPS-AC-01.01",
                "status": "FAIL",
                "details": "Test Fail",
                "level": 1,
            }
        ],
    )
    result = generate_sarif_audit(audit)

    run = result["runs"][0]

    # Check Tool
    tool = run["tool"]["driver"]
    assert tool["name"] in ("openssf-baseline-audit", "OpenSSF Baseline Threat Model", "OpenSSF Baseline")
    assert len(tool["rules"]) > 0
    rule = tool["rules"][0]
    assert "id" in rule
    assert "shortDescription" in rule
    assert "helpUri" in rule

    # Check Result
    res = run["results"][0]
    assert res["ruleId"] == "OSPS-AC-01.01"

    # Check locations
    assert len(res["locations"]) > 0
    phys_loc = res["locations"][0]["physicalLocation"]
    assert "artifactLocation" in phys_loc
    assert "uri" in phys_loc["artifactLocation"]

    # Check expected message format
    assert "Test Fail" in res["message"]["text"]
