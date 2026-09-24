"""detect_filter applied during context collection (feature 039, #165/#150).

Covers contracts/detect-filter.md obligations DF-7 and DF-8, plus the
reporting requirements FR-007 and FR-008.

The load-bearing assertion in this file is that filtering happens BEFORE the
auto-accept confidence threshold. `security_contact` carries
`auto_detect = true`, and a detected value at or above 0.8 is written to
`.project/` with no prompt (`context_storage.py`). Filtering after that check
would still have stored the rejected value, which is why DF-7 asserts at
confidence 1.0.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from darnit.config import context_storage
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
    """FR-014 and FR-015 (DF-9).

    Before feature 039 the read path performed no validation, so a value
    auto-accepted while the filter was not running persists indefinitely. The
    repositories most likely to hold one are exactly those audited while the
    guard was off, so without re-evaluation this fix would protect only
    repositories that have never been audited.
    """

    def _store(self, tmp_path: Path, key: str, value: object) -> bytes:
        context_storage.save_context_value(
            str(tmp_path),
            key,
            value,
            source=ContextSource.AUTO_DETECTED,
            detection_method="regex",
            confidence=0.8,
        )
        return (tmp_path / ".project" / "project.yaml").read_bytes()

    @pytest.mark.unit
    def test_stored_value_failing_its_filter_reads_as_unset(self, tmp_path: Path) -> None:
        """DF-9, first half."""
        self._store(tmp_path, "security_contact", PLACEHOLDER)
        assert context_storage.get_context_value(str(tmp_path), "security_contact") is None

    @pytest.mark.unit
    def test_project_file_is_not_modified(self, tmp_path: Path) -> None:
        """DF-9, second half. FR-015.

        A stored value may carry a human confirmation, and Principle IV makes
        confirmation the transition that grants usability. The framework
        reports; it does not silently revoke.
        """
        before = self._store(tmp_path, "security_contact", PLACEHOLDER)
        context_storage.get_context_value(str(tmp_path), "security_contact")
        after = (tmp_path / ".project" / "project.yaml").read_bytes()
        assert before == after

    @pytest.mark.unit
    def test_stored_value_passing_its_filter_reads_normally(self, tmp_path: Path) -> None:
        self._store(tmp_path, "security_contact", "security@real.org")
        value = context_storage.get_context_value(str(tmp_path), "security_contact")
        assert value is not None
        assert value.value == "security@real.org"

    @pytest.mark.unit
    def test_rejection_on_read_is_reported(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        self._store(tmp_path, "security_contact", PLACEHOLDER)
        with caplog.at_level(logging.WARNING):
            context_storage.get_context_value(str(tmp_path), "security_contact")
        assert "security_contact" in caplog.text
        assert "NOT modified" in caplog.text

    @pytest.mark.unit
    def test_key_without_a_filter_is_unaffected_on_read(self, tmp_path: Path) -> None:
        """FR-009 / SC-007: `has_releases` declares no filter and must behave
        exactly as it did before this feature."""
        self._store(tmp_path, "has_releases", True)
        value = context_storage.get_context_value(str(tmp_path), "has_releases")
        assert value is not None
        assert value.value is True
