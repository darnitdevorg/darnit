from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

INSIGHTS_FILENAME = "security-insights.yml"

INSIGHT_TO_DARNIT_MAPPING = {
    "security-contact": "security_contact",
    "vulnerability-reporting": "vulnerability_reporting_policy",
    "maintainers": "maintainers",
}

def load_security_insights(project_root: Path) -> dict[str, Any]:
    insight_path = project_root / INSIGHTS_FILENAME
    if not insight_path.exists():
        return {}
    try:
        with open(insight_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        raise ValueError(f"Failed to parse {INSIGHTS_FILENAME}: {e}") from e

def import_insights_to_context(project_root: Path, existing_project_data: dict[str, Any]) -> dict[str, Any]:
    insights = load_security_insights(project_root)
    imported_context = {}

    for insight_key, darnit_key in INSIGHT_TO_DARNIT_MAPPING.items():
        if insight_key in insights:
            if darnit_key not in existing_project_data or not existing_project_data[darnit_key]:
                imported_context[darnit_key] = {
                    "value": insights[insight_key],
                    "origin": "security-insights.yml",
                    "status": "asserted"
                }
    return imported_context

def export_security_insights(project_root: Path, confirmed_project_data: dict[str, Any]) -> Path | None:
    insights_data = {}
    darnit_to_insight_mapping = {v: k for k, v in INSIGHT_TO_DARNIT_MAPPING.items()}

    for darnit_key, value_info in confirmed_project_data.items():
        if isinstance(value_info, dict) and value_info.get("status") == "confirmed":
            if darnit_key in darnit_to_insight_mapping:
                insight_key = darnit_to_insight_mapping[darnit_key]
                insights_data[insight_key] = value_info.get("value")

    if not insights_data:
        return None

    output_path = project_root / INSIGHTS_FILENAME
    existing_data = {}
    if output_path.exists():
        try:
            with open(output_path, encoding="utf-8") as f:
                existing_data = yaml.safe_load(f) or {}
        except Exception:
            pass

    existing_data.update(insights_data)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(existing_data, f, sort_keys=False, indent=2)

    return output_path
