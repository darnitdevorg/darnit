"""Regression tests for audit_openssf_baseline output/attestation wiring.

These guard two previously-silent failures:
- output_format="sarif" was advertised but fell through to markdown
- the generate_attestation tool imported a function that does not exist
"""

import json

import pytest

FAKE_RESULTS = [
    {"id": "OSPS-LE-02.01", "status": "FAIL", "level": 1, "details": "no license"},
    {"id": "OSPS-AC-01.01", "status": "PASS", "level": 1, "details": "MFA enforced"},
]
FAKE_SUMMARY = {"PASS": 1, "FAIL": 1, "WARN": 0, "N/A": 0, "ERROR": 0, "total": 2}


@pytest.fixture
def fake_audit(monkeypatch):
    import darnit.tools.audit as audit_mod

    def _fake_run_sieve_audit(*args, **kwargs):
        return FAKE_RESULTS, FAKE_SUMMARY

    monkeypatch.setattr(audit_mod, "run_sieve_audit", _fake_run_sieve_audit)


class TestSarifOutputFormat:
    def test_sarif_format_returns_sarif_document(self, fake_audit, tmp_path):
        from darnit_baseline.tools import audit_openssf_baseline

        output = audit_openssf_baseline(
            owner="acme",
            repo="widget",
            local_path=str(tmp_path),
            level=1,
            output_format="sarif",
        )

        doc = json.loads(output)
        assert doc["version"] == "2.1.0"
        assert "sarif" in doc["$schema"]
        run = doc["runs"][0]
        rule_ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
        assert "OSPS-LE-02.01" in rule_ids
        assert run["properties"]["owner"] == "acme"
        # PASS results are excluded by default; the FAIL must be present
        result_rules = {r["ruleId"] for r in run["results"]}
        assert result_rules == {"OSPS-LE-02.01"}

    def test_sarif_format_is_not_markdown(self, fake_audit, tmp_path):
        from darnit_baseline.tools import audit_openssf_baseline

        output = audit_openssf_baseline(
            owner="acme",
            repo="widget",
            local_path=str(tmp_path),
            level=1,
            output_format="sarif",
        )
        assert not output.startswith("#")


class TestAttestWiring:
    def test_attest_appends_section_to_markdown(self, fake_audit, tmp_path, monkeypatch):
        import darnit_baseline.attestation as attestation_pkg
        from darnit_baseline.tools import audit_openssf_baseline

        captured = {}

        def _fake_generate(audit_result, sign=True, staging=False, **kwargs):
            captured["audit_result"] = audit_result
            captured["sign"] = sign
            return "✅ Attestation saved to: /tmp/fake.intoto.json\n\n{}"

        monkeypatch.setattr(attestation_pkg, "generate_attestation_from_results", _fake_generate)

        output = audit_openssf_baseline(
            owner="acme",
            repo="widget",
            local_path=str(tmp_path),
            level=1,
            attest=True,
            sign_attestation=False,
        )

        assert "## Attestation" in output
        assert "✅ Attestation saved to:" in output
        assert captured["sign"] is False
        assert captured["audit_result"].owner == "acme"
        assert captured["audit_result"].all_results == FAKE_RESULTS

    def test_attest_skipped_without_owner_repo(self, fake_audit, tmp_path):
        from darnit_baseline.tools import audit_openssf_baseline

        output = audit_openssf_baseline(
            local_path=str(tmp_path),
            level=1,
            attest=True,
        )
        assert "Attestation skipped" in output

    def test_no_attest_section_by_default(self, fake_audit, tmp_path):
        from darnit_baseline.tools import audit_openssf_baseline

        output = audit_openssf_baseline(
            owner="acme",
            repo="widget",
            local_path=str(tmp_path),
            level=1,
        )
        assert "## Attestation" not in output


class TestGenerateAttestationToolImports:
    def test_generate_attestation_from_results_importable(self):
        # The tool previously imported `generate_attestation`, which does
        # not exist in the attestation package and raised ImportError at
        # call time.
        from darnit_baseline.attestation import (
            generate_attestation_from_results,  # noqa: F401
        )

    def test_tool_uses_existing_attestation_api(self, fake_audit, tmp_path, monkeypatch):
        import darnit_baseline.attestation as attestation_pkg
        from darnit_baseline.tools import generate_attestation

        def _fake_generate(audit_result, **kwargs):
            return "✅ Attestation saved to: /tmp/fake.intoto.json"

        monkeypatch.setattr(attestation_pkg, "generate_attestation_from_results", _fake_generate)

        output = generate_attestation(
            owner="acme",
            repo="widget",
            local_path=str(tmp_path),
            level=1,
            sign=False,
        )
        assert output.startswith("✅")
