"""Feature 030 SC-002 mechanical verification.

Loads the `full_field_coverage.yaml` fixture through the reconciled reader
and mapper, and asserts the flat CEL context dict equals a hand-authored
golden `EXPECTED` dict inlined below. Any silent semantic drift in a
future reconciliation trips this test.

Also asserts the NEW-IGNORED handling of `slack_channels` -- when the
fixture (or a caller) includes the new upstream field, the raw parsed
value lands in `ProjectConfig._extra` verbatim and is NOT projected onto
any `ProjectConfig` attribute.
"""

from __future__ import annotations

import shutil
import warnings
from pathlib import Path

from darnit.context.dot_project import DotProjectReader
from darnit.context.dot_project_mapper import DotProjectMapper

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "full_field_coverage.yaml"


EXPECTED_CONTEXT = {
    "project.adopters_path": "ADOPTERS.md",
    "project.cncf_slack_channel": "#full-field-coverage",
    "project.description": "Reconciliation coverage fixture for feature 030.",
    "project.documentation.quickstart": {"path": "docs/quickstart.md"},
    "project.governance.code_of_conduct_path": "CODE_OF_CONDUCT.md",
    "project.governance.contributing_path": "CONTRIBUTING.md",
    "project.landscape.category": "runtime",
    "project.landscape.subcategory": "cloud-native",
    "project.legal.license_path": "LICENSE",
    "project.mailing_lists": ["full-field-coverage-dev@example.org"],
    "project.name": "full-field-coverage",
    # Both list-form entries in the fixture collapse to their first element
    # per feature 030 Q1 (parse-only) + T005.
    "project.package_managers": {
        "npm": "@full-field/package",
        "docker": "cncf/full-field-coverage:latest",
    },
    # Fixture supplies `project_lead` as a list; the reader's coercer
    # collapses to the first non-empty element per T003+T004.
    "project.project_lead": "@alice",
    "project.repositories": ["cncf/full-field-coverage"],
    "project.schema_version": "1.2.0",
    "project.security.advisory_url": "https://example.org/advisories",
    "project.security.contact": "security@example.org",
    "project.security.contact_email": "security@example.org",
    "project.security.policy_path": "SECURITY.md",
    "project.security.threat_model_path": "docs/threat-model.md",
    "project.slug": "full-field-coverage",
    "project.social.mastodon": "@full_field@example.social",
    "project.social.twitter": "@full_field",
    "project.type": "sandbox",
    "project.website": "https://example.org",
}


def _stage_fixture(tmp_path: Path, extra_top_level: dict | None = None) -> Path:
    """Copy the fixture into a `.project/project.yaml` under `tmp_path` and
    optionally append additional top-level keys (as YAML text) so tests can
    exercise NEW-IGNORED behavior without editing the shared fixture file.
    """
    dest_dir = tmp_path / ".project"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "project.yaml"
    shutil.copy(FIXTURE_PATH, dest)
    if extra_top_level:
        import yaml

        existing = yaml.safe_load(dest.read_text())
        existing.update(extra_top_level)
        dest.write_text(yaml.safe_dump(existing, sort_keys=False))
    return tmp_path


def test_reader_output_matches_golden(tmp_path: Path) -> None:
    """SC-002: every field darnit exposes today produces the same value
    it did pre-reconciliation for this fixture. The golden dict is the
    baseline; any drift is a maintainer signal."""
    repo = _stage_fixture(tmp_path)

    mapper = DotProjectMapper(str(repo))
    # Suppress `cncf_slack_channel` deprecation-warning noise; the warning
    # itself is asserted in `test_dot_project_deprecations` (T016).
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        context = mapper.get_context()

    assert context == EXPECTED_CONTEXT


def test_extra_captures_slack_channels(tmp_path: Path) -> None:
    """T007 verification: when the new upstream `slack_channels` field is
    present in a `.project/project.yaml`, the raw parsed value lands in
    `ProjectConfig._extra['slack_channels']` verbatim and is NOT projected
    onto any `ProjectConfig` attribute (parse-only per feature 030 Q1).
    """
    slack_channels_value = [
        {
            "workspace": "cncf",
            "link": "https://cncf.slack.com/channels/full-field",
            "name": "#full-field-coverage",
            "primary": True,
        },
        {
            "workspace": "cncf",
            "link": "https://cncf.slack.com/channels/full-field-dev",
            "name": "#full-field-coverage-dev",
            "primary": False,
        },
    ]
    repo = _stage_fixture(tmp_path, extra_top_level={"slack_channels": slack_channels_value})

    reader = DotProjectReader(str(repo))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        config = reader.read()

    assert config is not None
    assert "slack_channels" in config._extra
    assert config._extra["slack_channels"] == slack_channels_value
    # And there is no attribute for it (parse-only).
    assert not hasattr(config, "slack_channels")
