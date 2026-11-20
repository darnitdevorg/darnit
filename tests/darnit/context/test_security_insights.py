"""Security Insights contact as a candidate for ``security_contact`` (#497).

The documents below follow the shapes in the OpenSSF Security Insights spec
(v1.0.0 ``security-insights-schema.yaml`` and examples; v2.2.0
``spec/schema.cue`` and ``examples/example-full.yml``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from darnit.config.context_keys import value_digest
from darnit.config.context_resolve import resolve_context
from darnit.config.context_schema import ContextDefinition, ContextType, OriginKind, Standing
from darnit.config.loader import load_project_config
from darnit.config.operator.schema import OperatorConfig
from darnit.context.security_insights import find_security_insights, security_contact_from_insights
from darnit.context.sieve import ContextSieve

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)

V1 = """\
header:
  schema-version: 1.0.0
  expiration-date: '2027-08-31T10:10:09.000Z'
  project-url: https://github.com/foo/bar
project-lifecycle:
  status: active
  bug-fixes-only: false
security-contacts:
- type: email
  value: secondary@foobar.dev
  primary: false
- type: email
  value: security@foobar.dev
  primary: true
vulnerability-reporting:
  accepts-vulnerability-reports: true
"""

V2 = """\
header:
  schema-version: 2.0.0
  last-updated: '2026-03-01'
  last-reviewed: '2026-04-01'
  url: https://foobar.dev/security-insights.yml
project:
  name: FooBar
  vulnerability-reporting:
    reports-accepted: true
    bug-bounty-available: false
    contact:
      name: FooBar security team
      email: security@foobar.dev
      primary: true
    policy: https://foobar.dev/reporting.html
"""


def _doc(text: str) -> Any:
    return yaml.safe_load(text)


@pytest.mark.unit
class TestParse:
    def test_v1_prefers_the_primary_contact(self) -> None:
        assert security_contact_from_insights(_doc(V1)) == "security@foobar.dev"

    def test_v1_first_contact_when_none_is_primary(self) -> None:
        doc = _doc(V1)
        for contact in doc["security-contacts"]:
            contact.pop("primary")
        assert security_contact_from_insights(doc) == "secondary@foobar.dev"

    def test_v1_url_contact(self) -> None:
        doc = _doc(V1)
        doc["security-contacts"] = [{"type": "url", "value": "https://foobar.dev/report"}]
        assert security_contact_from_insights(doc) == "https://foobar.dev/report"

    def test_v1_phone_is_not_a_reporting_contact(self) -> None:
        doc = _doc(V1)
        doc["security-contacts"] = [{"type": "phone", "value": "+1 555 0100", "primary": True}]
        assert security_contact_from_insights(doc) is None

    def test_v1_falls_back_to_email_contact(self) -> None:
        doc = _doc(V1)
        del doc["security-contacts"]
        doc["vulnerability-reporting"]["email-contact"] = "vuln@foobar.dev"
        assert security_contact_from_insights(doc) == "vuln@foobar.dev"

    def test_v2_contact_email(self) -> None:
        assert security_contact_from_insights(_doc(V2)) == "security@foobar.dev"

    def test_v2_contact_without_email_gives_nothing(self) -> None:
        doc = _doc(V2)
        del doc["project"]["vulnerability-reporting"]["contact"]["email"]
        assert security_contact_from_insights(doc) is None

    def test_v2_without_contact_gives_nothing(self) -> None:
        doc = _doc(V2)
        del doc["project"]["vulnerability-reporting"]["contact"]
        assert security_contact_from_insights(doc) is None

    def test_v2_policy_url_is_not_read(self) -> None:
        doc = _doc(V2)
        del doc["project"]["vulnerability-reporting"]["contact"]
        assert security_contact_from_insights(doc) != "https://foobar.dev/reporting.html"

    @pytest.mark.parametrize(
        "doc",
        [
            None,
            [],
            "text",
            {"security-contacts": [{"type": "email", "value": "a@foobar.dev"}]},
            {"header": {"schema-version": "3.0.0"}, "project": {}},
            {"header": "1.0.0"},
        ],
    )
    def test_unknown_shapes_give_nothing(self, doc: Any) -> None:
        assert security_contact_from_insights(doc) is None


@pytest.mark.unit
class TestFind:
    @pytest.mark.parametrize(
        "relative",
        [
            "security-insights.yml",
            "SECURITY-INSIGHTS.yml",
            ".github/security-insights.yml",
            ".gitlab/security-insights.yml",
        ],
    )
    def test_spec_locations(self, tmp_path: Path, relative: str) -> None:
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(V2, encoding="utf-8")
        assert find_security_insights(tmp_path) == relative

    def test_root_before_forge_directory(self, tmp_path: Path) -> None:
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "security-insights.yml").write_text(V1, encoding="utf-8")
        (tmp_path / "security-insights.yml").write_text(V2, encoding="utf-8")
        assert find_security_insights(tmp_path) == "security-insights.yml"

    def test_absent(self, tmp_path: Path) -> None:
        (tmp_path / ".project").mkdir()
        (tmp_path / ".project" / "security-insights.yml").write_text(V2, encoding="utf-8")
        assert find_security_insights(tmp_path) is None


@pytest.mark.unit
class TestSieveSignal:
    def test_signal_names_the_relative_file(self, tmp_path: Path) -> None:
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "security-insights.yml").write_text(V1, encoding="utf-8")

        result = ContextSieve().detect("security_contact", str(tmp_path))

        assert result.value == "security@foobar.dev"
        [signal] = result.signals
        assert signal.method == "Parsed .github/security-insights.yml"
        assert signal.evidence == {"file": ".github/security-insights.yml"}

    def test_malformed_file_gives_no_signal(self, tmp_path: Path) -> None:
        (tmp_path / "security-insights.yml").write_text("header: [unclosed\n", encoding="utf-8")

        result = ContextSieve().detect("security_contact", str(tmp_path))

        assert result.value is None
        assert result.signals == []

    def test_file_outside_the_repository_is_not_read(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.yml"
        outside.write_text(V2, encoding="utf-8")
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "security-insights.yml").symlink_to(outside)

        result = ContextSieve().detect("security_contact", str(repo))

        assert result.signals == []


def _definitions() -> dict[str, ContextDefinition]:
    # As openssf-baseline.toml defines security_contact: a user-judgment key
    # whose detected values may be proposed.
    return {
        "security_contact": ContextDefinition(
            prompt="security_contact?",
            type=ContextType.STRING,
            affects=["C-1"],
            auto_detect=False,
            allow_sieve_hints=True,
            detect_filter="!value.contains('example.com') && !value.contains('example.org')",
        )
    }


def _resolve(repo: Path):
    return resolve_context(
        str(repo),
        _definitions(),
        operator=OperatorConfig.model_validate({"schema_version": 1}),
        now=NOW,
        env={},
        auto_accept_confidence=0.8,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    (path / "security-insights.yml").write_text(V2, encoding="utf-8")
    return path


@pytest.mark.unit
class TestCandidate:
    def test_contact_is_a_candidate_with_its_origin(self, repo: Path) -> None:
        resolved = _resolve(repo)
        value = resolved.values["security_contact"]

        assert value.standing is Standing.CANDIDATE
        assert value.value == "security@foobar.dev"
        assert value.origin.kind is OriginKind.SIEVE_HINT
        assert value.origin.method.endswith("from security-insights.yml")
        assert str(repo) not in value.origin.method
        assert "security_contact" not in resolved.usable()

    def test_unconfirmed_stored_value_is_not_replaced(self, repo: Path) -> None:
        (repo / ".project").mkdir()
        (repo / ".project" / "project.yaml").write_text(
            "name: p\nsecurity:\n  contact: team@foobar.dev\n", encoding="utf-8"
        )

        value = _resolve(repo).values["security_contact"]

        assert value.standing is Standing.CANDIDATE
        assert value.value == "team@foobar.dev"
        assert value.origin.kind is OriginKind.STORED_UNCONFIRMED

    def test_confirmed_value_is_not_replaced(self, repo: Path) -> None:
        (repo / ".project").mkdir()
        (repo / ".project" / "darnit.yaml").write_text(
            yaml.safe_dump(
                {
                    "context": {"security_contact": "team@foobar.dev"},
                    "confirmations": {
                        "security_contact": {
                            "value_digest": value_digest("security_contact", "team@foobar.dev"),
                            "confirmed_by": "alice",
                            "confirmed_at": "2026-11-01T00:00:00Z",
                            "last_validated": "2026-11-01T00:00:00Z",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        resolved = _resolve(repo)

        assert resolved.values["security_contact"].standing is Standing.CONFIRMED
        assert resolved.usable() == {"security_contact": "team@foobar.dev"}

    def test_project_config_is_not_changed(self, repo: Path) -> None:
        (repo / ".project").mkdir()
        (repo / ".project" / "project.yaml").write_text("name: p\n", encoding="utf-8")

        config = load_project_config(str(repo))

        assert config is not None
        assert config.security is None or config.security.contact is None
