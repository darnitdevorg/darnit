"""Failed detection is not a value (feature 042, US5, FR-016, FR-017, SC-004)."""

from __future__ import annotations

import json
import os
import shutil
import tomllib
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest

from darnit.config import context_storage
from darnit.config.context_resolve import resolve_context
from darnit.config.context_schema import Standing
from darnit.config.context_storage import _run_detect_pipeline, get_context_definitions, get_pending_context
from darnit.config.framework_schema import ContradictedBy, HandlerInvocation
from darnit.trust.assertions import observe_context_evidence
from darnit_baseline.tools import audit_openssf_baseline

OWNER = "example-org"
REPO = "r-rel"
NO_SUCH_COMMAND = "darnit-042-no-such-command"


def _step(**fields: Any) -> HandlerInvocation:
    return HandlerInvocation(**fields)


def _answered_no() -> HandlerInvocation:
    """A step that ran to completion and answered "no": exit 0, empty output, ``expr`` false."""
    return _step(
        handler="exec",
        command=["true"],
        pass_exit_codes=[0],
        expr='output.stdout != ""',
        value_if_pass=True,
        value_if_fail=False,
    )


def _baseline_framework() -> dict[str, Any]:
    return tomllib.loads((files("darnit_baseline") / "openssf-baseline.toml").read_text(encoding="utf-8"))


def _release_gated_controls() -> set[str]:
    return {
        control_id
        for control_id, control in _baseline_framework()["controls"].items()
        if "has_releases" in (control.get("when") or {})
        or (control.get("contradicted_by") or {}).get("context") == "has_releases"
    }


def _has_releases_pipeline() -> list:
    return get_context_definitions(".")["has_releases"].detect


@pytest.fixture(scope="session")
def _no_releases_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    bin_dir = tmp_path_factory.mktemp("no-releases-bin")
    (bin_dir / "gh").symlink_to(shutil.which("true"))
    return bin_dir


@pytest.fixture
def gh_answers_no_releases(_no_releases_bin: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``gh`` that succeeds with empty output: the recorded answer of a repository without releases."""
    monkeypatch.setenv("PATH", f"{_no_releases_bin}{os.pathsep}{os.environ.get('PATH', '')}")


@pytest.fixture
def r_rel(scratch_repo: Callable[[str], Path]) -> Path:
    return scratch_repo("R-rel")


@pytest.mark.unit
class TestFallbackOnlyOnConcludedNegative:
    def test_value_if_fail_applies_when_the_step_answered_no(self, tmp_path: Path) -> None:
        detected = _run_detect_pipeline("has_releases", [_answered_no()], str(tmp_path), OWNER, REPO)

        assert detected is not None
        assert detected.value is False
        assert detected.detection_method.endswith(":fail_fallback")

    def test_error_yields_no_value(self, tmp_path: Path) -> None:
        missing_tool = _step(
            handler="exec", command=[NO_SUCH_COMMAND], pass_exit_codes=[0], value_if_pass=True, value_if_fail=False
        )

        assert _run_detect_pipeline("has_releases", [missing_tool], str(tmp_path), OWNER, REPO) is None

    def test_inconclusive_yields_no_value(self, tmp_path: Path) -> None:
        undeclared_exit = _step(
            handler="exec",
            command=["false"],
            pass_exit_codes=[0],
            expr='output.stdout != ""',
            value_if_pass=True,
            value_if_fail=False,
        )

        assert _run_detect_pipeline("has_releases", [undeclared_exit], str(tmp_path), OWNER, REPO) is None

    def test_an_earlier_step_that_did_not_run_blocks_the_fallback(self, tmp_path: Path) -> None:
        pipeline = [_step(handler="exec", command=[NO_SUCH_COMMAND], value_if_pass=True), _answered_no()]

        assert _run_detect_pipeline("has_releases", pipeline, str(tmp_path), OWNER, REPO) is None

    def test_an_unknown_handler_blocks_the_fallback(self, tmp_path: Path) -> None:
        pipeline = [_step(handler="darnit_042_no_such_handler"), _answered_no()]

        assert _run_detect_pipeline("has_releases", pipeline, str(tmp_path), OWNER, REPO) is None

    def test_a_later_step_still_concludes_a_positive(self, tmp_path: Path) -> None:
        (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
        pipeline = [
            _step(handler="exec", command=["false"], value_if_pass=True, value_if_fail=False),
            _step(handler="file_exists", files=["CHANGELOG.md"], value_if_pass=True),
        ]

        detected = _run_detect_pipeline("has_releases", pipeline, str(tmp_path), OWNER, REPO)

        assert detected is not None
        assert detected.value is True


@pytest.mark.integration
class TestReleaseStatus:
    def test_failing_gh_leaves_release_status_unknown(self, r_rel: Path) -> None:
        resolved = resolve_context(str(r_rel), owner=OWNER, repo=REPO)

        assert resolved.get("has_releases").standing is Standing.UNKNOWN
        assert "has_releases" not in resolved.usable()
        assert "has_releases" in {request.key for request in get_pending_context(str(r_rel), owner=OWNER, repo=REPO)}

    def test_a_successful_answer_of_no_releases_concludes_false(
        self, r_rel: Path, gh_answers_no_releases: None
    ) -> None:
        resolved = resolve_context(str(r_rel), owner=OWNER, repo=REPO)

        assert resolved.get("has_releases").standing is Standing.CONCLUDED
        assert resolved.usable()["has_releases"] is False

    def test_failing_gh_is_no_contradicting_evidence(self, r_rel: Path) -> None:
        evidence = observe_context_evidence(
            ContradictedBy(context="has_releases", when_value=True), _has_releases_pipeline(), str(r_rel), OWNER, REPO
        )

        assert not evidence.obtained

    def test_release_gated_controls_match_the_unknown_case(self, r_rel: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """SC-004: a failing lookup changes 0 release-gated results compared with no lookup at all."""
        gated = _release_gated_controls()
        assert gated

        def statuses() -> dict[str, str]:
            payload = audit_openssf_baseline(local_path=str(r_rel), level=3, output_format="json")
            results = json.loads(payload[payload.index("{") :])["results"]
            return {r["id"]: r["status"] for r in results if r["id"] in gated}

        with_failing_lookup = statuses()

        run_pipeline = context_storage._run_detect_pipeline

        def never_for_releases(key: str, *args: Any, **kwargs: Any):
            return None if key == "has_releases" else run_pipeline(key, *args, **kwargs)

        monkeypatch.setattr(context_storage, "_run_detect_pipeline", never_for_releases)
        with_unknown_status = statuses()

        assert with_failing_lookup == with_unknown_status
        assert set(with_failing_lookup) == gated
        assert "N/A" not in with_failing_lookup.values()
