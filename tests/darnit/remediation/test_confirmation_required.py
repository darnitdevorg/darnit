"""Remediation reads only usable context values (feature 042, US2, FR-006, FR-007; research R11)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from darnit.config.context_keys import value_digest
from darnit.config.framework_schema import HandlerInvocation, RemediationConfig, TemplateConfig
from darnit.remediation.executor import RemediationExecutor


def _executor(
    repo: Path, content: str, values: dict[str, Any] | None = None, unconfirmed: set[str] = frozenset()
) -> RemediationExecutor:
    return RemediationExecutor(
        local_path=str(repo),
        owner="example-org",
        repo="example",
        templates={"t": TemplateConfig(content=content), "plain": TemplateConfig(content="plain\n")},
        context_values=values or {},
        unconfirmed_keys=unconfirmed,
    )


def _file(path: str, template: str = "t", **fields: Any) -> HandlerInvocation:
    return HandlerInvocation(handler="file_create", path=path, template=template, **fields)


@pytest.mark.unit
class TestTemplateReads:
    @pytest.mark.parametrize(
        "content",
        [
            "Maintainers: << context.maintainers >>\n",
            "Maintainers: << context.maintainers | default('@org/maintainers') >>\n",
            "Maintainers: << context['maintainers'] | default('@org/maintainers', true) >>\n",
            "<% if 'maintainers' in context %>listed<% else %>@org/maintainers<% endif %>\n",
            "<< context.get('maintainers', '@org/maintainers') >>\n",
        ],
    )
    @pytest.mark.parametrize("dry_run", [True, False])
    def test_unusable_key_requires_confirmation(self, tmp_path: Path, content: str, dry_run: bool) -> None:
        executor = _executor(tmp_path, content, unconfirmed={"maintainers"})

        result = executor.execute("C-1", RemediationConfig(handlers=[_file("OUT.md")]), dry_run=dry_run)

        assert not result.success
        assert result.message == "confirmation required: maintainers"
        assert result.confirmation_required == "maintainers"
        assert not (tmp_path / "OUT.md").exists()

    def test_usable_value_renders(self, tmp_path: Path) -> None:
        executor = _executor(
            tmp_path, "Maintainers: << context.maintainers >>\n", {"maintainers": ["@b", "@a"]}, {"security_contact"}
        )

        result = executor.execute("C-1", RemediationConfig(handlers=[_file("OUT.md")]), dry_run=False)

        assert result.success
        assert result.confirmation_required is None
        assert (tmp_path / "OUT.md").read_text() == "Maintainers: @a @b\n"

    def test_nothing_is_written_when_a_later_handler_needs_confirmation(self, tmp_path: Path) -> None:
        executor = _executor(tmp_path, "<< context.security_contact >>\n", unconfirmed={"security_contact"})
        config = RemediationConfig(handlers=[_file("FIRST.md", template="plain"), _file("SECOND.md")])

        result = executor.execute("C-1", config, dry_run=False)

        assert result.confirmation_required == "security_contact"
        assert not (tmp_path / "FIRST.md").exists()
        assert not (tmp_path / "SECOND.md").exists()

    def test_undefined_key_that_is_not_a_context_key_renders_empty(self, tmp_path: Path) -> None:
        executor = _executor(tmp_path, "[<< context.not_a_key >>]\n", unconfirmed={"maintainers"})

        result = executor.execute("C-1", RemediationConfig(handlers=[_file("OUT.md")]), dry_run=False)

        assert result.success
        assert (tmp_path / "OUT.md").read_text() == "[]\n"


@pytest.mark.unit
class TestWhen:
    def _config(self) -> RemediationConfig:
        return RemediationConfig(
            strategy="first_match",
            handlers=[
                _file("UMBRELLA.md", template="plain", when={"csl_governance_mode": "umbrella"}),
                _file("FULL.md", template="plain"),
            ],
        )

    def test_unusable_key_in_when_requires_confirmation(self, tmp_path: Path) -> None:
        executor = _executor(tmp_path, "unused\n", unconfirmed={"csl_governance_mode"})

        result = executor.execute("C-1", self._config(), dry_run=False)

        assert result.confirmation_required == "csl_governance_mode"
        assert list(tmp_path.iterdir()) == []

    def test_when_evaluates_against_usable_values(self, tmp_path: Path) -> None:
        executor = _executor(tmp_path, "unused\n", {"csl_governance_mode": "csl"}, {"csl_governance_reference"})

        result = executor.execute("C-1", self._config(), dry_run=False)

        assert result.success
        assert (tmp_path / "FULL.md").exists()
        assert not (tmp_path / "UMBRELLA.md").exists()


def _confirm(repo: Path, key: str, value: Any) -> None:
    path = repo / ".project" / "darnit.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data.setdefault("context", {})[key] = value
    data.setdefault("confirmations", {})[key] = {
        "value_digest": value_digest(key, value),
        "confirmed_by": "alice",
        "confirmed_at": "2026-09-01T00:00:00Z",
        "last_validated": "2026-09-01T00:00:00Z",
    }
    path.parent.mkdir(exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


@pytest.mark.integration
class TestBaselineRemediation:
    """OSPS-VM-02.01 renders ``context.security_contact`` without declaring it in ``requires_context``."""

    def test_unconfirmed_security_contact_requires_confirmation(self, tmp_path: Path) -> None:
        from darnit_baseline.remediation.orchestrator import _apply_control_remediation

        repo = tmp_path
        (repo / ".project").mkdir()
        (repo / ".project" / "darnit.yaml").write_text(
            yaml.safe_dump({"context": {"security_contact": "security@stored-only.example.net"}}), encoding="utf-8"
        )

        result = _apply_control_remediation("OSPS-VM-02.01", str(repo), "example-org", "example", dry_run=True)

        assert result["status"] == "needs_confirmation"
        assert result["missing_context"] == ["security_contact"]
        assert "confirmation required: security_contact" in result["result"]
        assert "security@stored-only.example.net" not in str(result)

    def test_confirmed_security_contact_is_rendered(self, tmp_path: Path) -> None:
        from darnit_baseline.remediation.orchestrator import _apply_control_remediation

        repo = tmp_path
        _confirm(repo, "security_contact", "security@confirmed.example.net")

        result = _apply_control_remediation("OSPS-VM-02.01", str(repo), "example-org", "example", dry_run=False)

        assert result["status"] == "applied"
        assert "security@confirmed.example.net" in (repo / "SECURITY.md").read_text(encoding="utf-8")

    def test_detected_maintainers_candidate_is_not_ready(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from darnit.config import context_resolve
        from darnit.config.context_schema import ContextValue, OriginKind
        from darnit.remediation.context_validator import check_context_requirements
        from darnit_baseline.remediation.orchestrator import _get_framework_config

        def fake_detect(key: str, *args: Any):
            if key == "maintainers":
                value = ContextValue.auto_detected(value=["@alice"], method="MAINTAINERS.md", confidence=0.95)
                return value, OriginKind.SIEVE_HINT
            return None, None

        monkeypatch.setattr(context_resolve, "_detect", fake_detect)
        repo = tmp_path
        (repo / "MAINTAINERS.md").write_text("# Maintainers\n\n- @alice\n", encoding="utf-8")
        framework = _get_framework_config()
        requirements = framework.controls["OSPS-GV-04.01"].remediation.requires_context

        check = check_context_requirements(requirements, str(repo), framework, "example-org", "r-maint")

        assert not check.ready
        assert check.missing_context == ["maintainers"]
        assert check.auto_detected == {"maintainers": ["@alice"]}


@pytest.mark.unit
class TestRequirementStanding:
    """``check_context_requirements`` decides by standing, not by stored ``source``."""

    def _check(self, repo: Path, key: str, **requirement: Any):
        from darnit.config.framework_schema import ContextRequirement
        from darnit.remediation.context_validator import check_context_requirements
        from darnit_baseline.remediation.orchestrator import _get_framework_config

        return check_context_requirements(
            [ContextRequirement(key=key, **requirement)], str(repo), _get_framework_config()
        )

    def test_stored_unconfirmed_value_is_not_ready(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from darnit.config import context_resolve

        monkeypatch.setattr(context_resolve, "_detect", lambda *a: (None, None))
        (tmp_path / ".project").mkdir()
        (tmp_path / ".project" / "darnit.yaml").write_text(
            yaml.safe_dump({"context": {"maintainers": ["@bare"]}}), encoding="utf-8"
        )

        check = self._check(tmp_path, "maintainers")

        assert not check.ready
        assert check.missing_context == ["maintainers"]

    def test_confirmed_value_is_ready(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from darnit.config import context_resolve

        monkeypatch.setattr(context_resolve, "_detect", lambda *a: (None, None))
        _confirm(tmp_path, "maintainers", ["@alice"])

        check = self._check(tmp_path, "maintainers", confidence_threshold=0.9, prompt_if_auto_detected=True)

        assert check.ready
        assert check.missing_context == []
