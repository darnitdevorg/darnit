"""The OpenSSF Baseline controls follow the result authority contract (feature 041 US5).

Every Baseline control loads under step-declaration validation on both
control-loading paths, and the adversarial corpus reports zero false PASS
for ``openssf-baseline`` with an empty allowlist (SC-001).
"""

from __future__ import annotations

import pytest

from darnit.config import load_controls_from_framework, load_framework_config
from darnit.config.control_loader import load_controls_from_effective
from darnit.config.merger import load_effective_config_by_name
from darnit.core.discovery import get_implementation, register_implementation_handlers
from darnit.sieve.handler_registry import effective_outcomes, get_sieve_handler_registry
from tests.darnit_baseline.corpus.runner import (
    CorpusReport,
    gate,
    load_framework,
    load_known_false_pass,
    run_corpus,
)

FRAMEWORK = "openssf-baseline"
EXISTENCE_CONTROLS = {"OSPS-LE-03.01", "OSPS-QA-02.01", "OSPS-QA-05.01", "OSPS-QA-05.02"}
PRESENCE_OR_PATTERN = {"file_exists", "regex", "pattern"}


@pytest.fixture(scope="module")
def controls() -> list:
    impl = get_implementation(FRAMEWORK)
    assert impl is not None
    register_implementation_handlers(FRAMEWORK)
    return load_controls_from_framework(load_framework_config(impl.get_framework_config_path()))


def _baseline(controls: list) -> list:
    return [c for c in controls if c.control_id.startswith("OSPS-")]


def _steps(control) -> list:
    return control.metadata.get("handler_invocations") or []


def test_every_control_loads_on_the_effective_path(controls: list) -> None:
    effective = load_controls_from_effective(load_effective_config_by_name(FRAMEWORK, repo_path=None))
    assert {c.control_id for c in effective} == {c.control_id for c in controls}


def test_every_step_handler_is_registered(controls: list) -> None:
    registry = get_sieve_handler_registry()
    unregistered = [
        f"{c.control_id} pass[{i}] {inv.handler}"
        for c in _baseline(controls)
        for i, inv in enumerate(_steps(c))
        if registry.get(inv.handler) is None
    ]
    assert not unregistered, f"steps that validation could not check: {unregistered}"


def test_presence_and_pattern_steps_conclude_pass_only_for_existence_controls(controls: list) -> None:
    registry = get_sieve_handler_registry()
    offenders = []
    for c in _baseline(controls):
        for i, inv in enumerate(_steps(c)):
            if inv.handler not in PRESENCE_OR_PATTERN:
                continue
            may_pass = "pass" in effective_outcomes(registry.get(inv.handler), inv)
            if may_pass and c.control_id not in EXISTENCE_CONTROLS:
                offenders.append(f"{c.control_id} pass[{i}] {inv.handler}")
    assert not offenders, f"presence/pattern steps that may conclude PASS: {offenders}"
    for cid in EXISTENCE_CONTROLS:
        control = next(c for c in controls if c.control_id == cid)
        assert any(getattr(inv, "existence", False) for inv in _steps(control)), cid


def test_no_step_carries_a_promotion(controls: list) -> None:
    promoted = [
        f"{c.control_id} pass[{i}]"
        for c in _baseline(controls)
        for i, inv in enumerate(_steps(c))
        if getattr(inv, "promotion", None) is not None
    ]
    assert not promoted


def test_no_exec_step_calls_the_platform_api(controls: list) -> None:
    offenders = [
        f"{c.control_id} pass[{i}]"
        for c in _baseline(controls)
        for i, inv in enumerate(_steps(c))
        if inv.handler == "exec" and (inv.model_extra or {}).get("command", [])[:2] == ["gh", "api"]
    ]
    assert not offenders, f"platform checks still on exec (use gh_api): {offenders}"


@pytest.fixture(scope="module")
def report() -> CorpusReport:
    return run_corpus(load_framework(FRAMEWORK))


def test_corpus_has_zero_false_pass(report: CorpusReport) -> None:
    assert not report.violations, "false PASS on the corpus:\n" + "\n".join(v.describe() for v in report.violations)


def test_known_false_pass_list_is_empty_for_baseline(report: CorpusReport) -> None:
    known = [k for k in load_known_false_pass() if k.framework == FRAMEWORK]
    assert not known
    unexpected, stale = gate(report, known)
    assert not unexpected and not stale
