from __future__ import annotations

from pathlib import Path

import yaml

from darnit.core.insights import (
    export_security_insights,
    import_insights_to_context,
    load_security_insights,
)


def test_load_security_insights(tmp_path: Path) -> None:
    fixture = tmp_path / "security-insights.yml"
    fixture.write_text("schema-version: '1.0.0'\nsecurity-contact: 'test@example.com'", encoding="utf-8")
    data = load_security_insights(tmp_path)
    assert data["security-contact"] == "test@example.com"

def test_import_does_not_overwrite_confirmed(tmp_path: Path) -> None:
    fixture = tmp_path / "security-insights.yml"
    fixture.write_text("security-contact: 'insight-email@example.com'", encoding="utf-8")
    existing_data = {
        "security_contact": {
            "value": "confirmed-email@example.com",
            "status": "confirmed"
        }
    }
    imported = import_insights_to_context(tmp_path, existing_data)
    assert "security_contact" not in imported

def test_export_only_writes_confirmed(tmp_path: Path) -> None:
    confirmed_data = {
        "security_contact": {
            "value": "secure@example.com",
            "status": "confirmed"
        },
        "unconfirmed_field": {
            "value": "candidate@example.com",
            "status": "candidate"
        }
    }
    output_path = export_security_insights(tmp_path, confirmed_data)
    assert output_path is not None
    assert output_path.exists()
    content = yaml.safe_load(output_path.read_text(encoding="utf-8"))
    assert content["security-contact"] == "secure@example.com"
    assert "candidate@example.com" not in str(content)
