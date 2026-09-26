"""Files darnit writes to ``.project/`` stay within the upstream schema (feature 040, US2, T038).

``asserted_by`` is darnit data, so it must land only in darnit's extension
file (``.project/darnit.yaml``), never in the upstream ``project.yaml``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from darnit.config.loader import CNCF_STANDARD_FIELDS, load_project_config, save_project_config
from darnit.config.schema import ProjectConfig
from darnit.trust.assertions import collect_assertions


def _config() -> ProjectConfig:
    return ProjectConfig.model_validate(
        {
            "name": "own",
            "x-openssf-baseline": {
                "controls": {
                    "OSPS-BR-02.01": {
                        "status": "n/a",
                        "reason": "No releases yet",
                        "asserted_by": "@maintainer",
                    }
                }
            },
        }
    )


@pytest.mark.unit
def test_asserted_by_is_written_only_to_the_extension_file(tmp_path: Path) -> None:
    save_project_config(_config(), str(tmp_path))

    project = yaml.safe_load((tmp_path / ".project" / "project.yaml").read_text(encoding="utf-8"))
    extension = yaml.safe_load((tmp_path / ".project" / "darnit.yaml").read_text(encoding="utf-8"))

    assert set(project) <= CNCF_STANDARD_FIELDS
    assert "asserted_by" not in (tmp_path / ".project" / "project.yaml").read_text(encoding="utf-8")
    assert extension["controls"]["OSPS-BR-02.01"]["asserted_by"] == "@maintainer"


@pytest.mark.unit
def test_written_claim_round_trips(tmp_path: Path) -> None:
    save_project_config(_config(), str(tmp_path))

    loaded = load_project_config(str(tmp_path))
    assert loaded is not None
    assert loaded.x_openssf_baseline.controls["OSPS-BR-02.01"].asserted_by == "@maintainer"

    (claim,) = collect_assertions(tmp_path, {"OSPS-BR-02.01"})
    assert claim.asserted_by == "@maintainer"


@pytest.mark.unit
def test_asserted_by_is_optional(tmp_path: Path) -> None:
    config = ProjectConfig.model_validate(
        {"name": "own", "x-openssf-baseline": {"controls": {"OSPS-BR-02.01": {"status": "n/a"}}}}
    )
    save_project_config(config, str(tmp_path))

    extension = yaml.safe_load((tmp_path / ".project" / "darnit.yaml").read_text(encoding="utf-8"))
    assert "asserted_by" not in extension["controls"]["OSPS-BR-02.01"]
