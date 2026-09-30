"""detect_filter applied during context collection (feature 039, #165/#150).

Covers contracts/detect-filter.md obligations DF-7 and DF-8, plus the
reporting requirements FR-007 and FR-008.

The load-bearing assertion in this file is that filtering happens BEFORE any
confidence threshold is applied. Feature 042 made `security_contact` a
user-judgment key (`auto_detect = false`, FR-005): a detection only proposes
a candidate, and a filtered value must not be proposed either. For keys with
`auto_detect = true`, a value at or above the threshold is concluded for the
run (never written). Filtering after that check would still have concluded or
proposed the rejected value, which is why DF-7 asserts at confidence 1.0.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from darnit.config import context_storage
from darnit.config.context_schema import Standing
from darnit.config.context_storage import (
    ContextSource,
    ContextValue,
    _apply_detect_filter,
    get_pending_context,
)
from darnit.config.framework_schema import ContextDefinitionConfig

SHIPPED = "!value.contains('example.com') && !value.contains('example.org')"
PLACEHOLDER = "security@example.com"


def _definition(expression: str | None) -> ContextDefinitionConfig:
    return ContextDefinitionConfig(type="string", prompt="Security contact?", detect_filter=expression)


def _detected(value: object, confidence: float = 0.8) -> ContextValue:
    return ContextValue(
        value=value,
        confidence=confidence,
        detection_method="regex",
        source=ContextSource.AUTO_DETECTED,
    )


class TestFilterApplication:
    @pytest.mark.unit
    def test_rejected_value_becomes_none(self) -> None:
        assert _apply_detect_filter("security_contact", _definition(SHIPPED), _detected(PLACEHOLDER)) is None

    @pytest.mark.unit
    def test_accepted_value_passes_through(self) -> None:
        result = _apply_detect_filter("security_contact", _definition(SHIPPED), _detected("security@real.org"))
        assert result is not None
        assert result.value == "security@real.org"

    @pytest.mark.unit
    def test_rejected_at_full_confidence_still_rejected(self) -> None:
        """DF-7. Confidence must not rescue a filtered value.

        If filtering ever moves after the auto-accept threshold check, this is
        the test that catches it: 1.0 clears any threshold.
        """
        assert (
            _apply_detect_filter(
                "security_contact",
                _definition(SHIPPED),
                _detected(PLACEHOLDER, confidence=1.0),
            )
            is None
        )

    @pytest.mark.unit
    def test_key_without_filter_is_untouched(self) -> None:
        """FR-009: no filter declared means no evaluation and no change."""
        result = _apply_detect_filter("security_contact", _definition(None), _detected(PLACEHOLDER))
        assert result is not None
        assert result.value == PLACEHOLDER

    @pytest.mark.unit
    def test_list_keeps_survivors(self) -> None:
        result = _apply_detect_filter(
            "maintainers",
            _definition(SHIPPED),
            _detected(["a@example.com", "b@real.org"]),
        )
        assert result is not None
        assert result.value == ["b@real.org"]


class TestBothDetectionRoutes:
    """DF-7 and DF-8: neither route may bypass the filter.

    The filter is applied at the single point where both routes converge. These
    tests patch each route in turn to return a value the shipped filter
    rejects, and assert nothing is offered for that key.
    """

    def _repo(self, tmp_path: Path) -> str:
        (tmp_path / "SECURITY.md").write_text(f"Report vulnerabilities to {PLACEHOLDER}\n", encoding="utf-8")
        return str(tmp_path)

    @pytest.mark.unit
    def test_detect_pipeline_route_is_filtered(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """DF-7."""
        monkeypatch.setattr(
            context_storage,
            "_run_detect_pipeline",
            lambda *a, **k: _detected(PLACEHOLDER, confidence=1.0),
        )
        monkeypatch.setattr(context_storage, "_try_sieve_detection", lambda *a, **k: None)

        pending = get_pending_context(self._repo(tmp_path))
        offered = [p for p in pending if p.key == "security_contact" and getattr(p, "detected_value", None)]
        assert offered == [], "a filtered value was offered as a candidate"

    @pytest.mark.unit
    def test_sieve_fallback_route_is_filtered(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """DF-8. The older route, and the one most likely to be forgotten."""
        monkeypatch.setattr(context_storage, "_run_detect_pipeline", lambda *a, **k: None)
        monkeypatch.setattr(
            context_storage,
            "_try_sieve_detection",
            lambda *a, **k: _detected(PLACEHOLDER, confidence=1.0),
        )

        pending = get_pending_context(self._repo(tmp_path))
        offered = [p for p in pending if p.key == "security_contact" and getattr(p, "detected_value", None)]
        assert offered == [], "a filtered value was offered as a candidate"


class TestReporting:
    """FR-007 and FR-008. A guard that silently does not run is the defect."""

    @pytest.mark.unit
    def test_rejection_is_reported_and_names_the_key(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO):
            _apply_detect_filter("security_contact", _definition(SHIPPED), _detected(PLACEHOLDER))
        assert "security_contact" in caplog.text
        assert "detect_filter" in caplog.text

    @pytest.mark.unit
    def test_unevaluable_filter_is_reported_as_a_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = _apply_detect_filter("security_contact", _definition("!value.contains("), _detected("x"))
        assert result is None
        assert "security_contact" in caplog.text
        assert "!value.contains(" in caplog.text, "FR-007: the warning must name the expression"

    @pytest.mark.unit
    def test_rejected_and_unevaluable_read_differently(self, caplog: pytest.LogCaptureFixture) -> None:
        """FR-008: 'the filter said no' and 'the filter could not run' are
        different claims and must not produce the same message."""
        with caplog.at_level(logging.INFO):
            _apply_detect_filter("security_contact", _definition(SHIPPED), _detected(PLACEHOLDER))
        rejected = caplog.text
        caplog.clear()
        with caplog.at_level(logging.INFO):
            _apply_detect_filter("security_contact", _definition("!value.contains("), _detected("x"))
        assert rejected != caplog.text

    @pytest.mark.unit
    def test_discarded_element_count_is_reported(self, caplog: pytest.LogCaptureFixture) -> None:
        """FR-013."""
        with caplog.at_level(logging.INFO):
            _apply_detect_filter(
                "maintainers",
                _definition(SHIPPED),
                _detected(["a@example.com", "b@real.org"]),
            )
        assert "discarded 1" in caplog.text


class TestStoredValues:
    """FR-014 and FR-015 (DF-9), as feature 042 (FR-006) now provides them.

    Before feature 039 the read path performed no validation, so a value
    auto-accepted while the filter was not running persists indefinitely.
    Feature 039 dropped such a value on read, in every legacy reader. Feature
    042 replaced those readers with the resolver: a stored value without a
    confirmation record is a candidate, so it reaches no consumer whether or
    not it passes its filter, and it stays visible for review.
    """

    def _store(self, tmp_path: Path, key: str, value: object) -> bytes:
        """Write ``.project/`` as an earlier darnit version's auto-accept did.

        Feature 042 removed that write (FR-001, FR-002), so the stored value is
        laid down directly: the security contact in ``project.yaml`` and every
        value under ``darnit.yaml`` ``context``.
        """
        project_dir = tmp_path / ".project"
        project_dir.mkdir(exist_ok=True)
        project = {"name": "stored"}
        if key == "security_contact":
            project["security"] = {"contact": value}
        (project_dir / "project.yaml").write_text(yaml.safe_dump(project), encoding="utf-8")
        (project_dir / "darnit.yaml").write_text(yaml.safe_dump({"context": {key: value}}), encoding="utf-8")
        return (project_dir / "project.yaml").read_bytes()

    def _resolved(self, tmp_path: Path):
        from darnit.config.context_resolve import resolve_context

        return resolve_context(str(tmp_path), detect=False)

    @pytest.mark.unit
    def test_stored_value_failing_its_filter_is_not_usable(self, tmp_path: Path) -> None:
        """DF-9, first half."""
        self._store(tmp_path, "security_contact", PLACEHOLDER)
        assert "security_contact" not in self._resolved(tmp_path).usable()

    @pytest.mark.unit
    def test_project_file_is_not_modified(self, tmp_path: Path) -> None:
        """DF-9, second half. FR-015."""
        before = self._store(tmp_path, "security_contact", PLACEHOLDER)
        self._resolved(tmp_path)
        after = (tmp_path / ".project" / "project.yaml").read_bytes()
        assert before == after

    @pytest.mark.unit
    def test_stored_value_is_a_candidate_for_review(self, tmp_path: Path) -> None:
        """Write-verification and review need what is actually on disk."""
        self._store(tmp_path, "security_contact", PLACEHOLDER)
        value = self._resolved(tmp_path).values["security_contact"]
        assert value.standing is Standing.CANDIDATE
        assert value.value == PLACEHOLDER

    @pytest.mark.unit
    def test_key_without_a_filter_is_a_candidate_too(self, tmp_path: Path) -> None:
        """FR-009 / SC-007: `has_releases` declares no filter; unconfirmed, it is not usable either."""
        self._store(tmp_path, "has_releases", True)
        resolved = self._resolved(tmp_path)
        assert resolved.values["has_releases"].value is True
        assert "has_releases" not in resolved.usable()

    @pytest.mark.unit
    def test_collect_auto_context_does_not_consume_failing_stored_value(self, tmp_path: Path) -> None:
        from darnit.context.auto_detect import collect_auto_context

        self._store(tmp_path, "security_contact", PLACEHOLDER)
        assert collect_auto_context(str(tmp_path)).get("security_contact") != PLACEHOLDER

    @pytest.mark.unit
    def test_failing_stored_value_is_asked_about_again(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A value that reads as unset must not also count as confirmed, or the
        user is never prompted to replace it."""
        monkeypatch.setattr(context_storage, "_run_detect_pipeline", lambda *a, **k: None)
        monkeypatch.setattr(context_storage, "_try_sieve_detection", lambda *a, **k: None)
        self._store(tmp_path, "security_contact", PLACEHOLDER)
        pending = get_pending_context(str(tmp_path))
        assert "security_contact" in [p.key for p in pending]
