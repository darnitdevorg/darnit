"""Unit and integration tests for scripts/verify_harness_report.py (#781)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.verify_harness_report import (
    main,
    verify_harness_report,
)


def _build_sample_report(
    *,
    llm_status: str = "PENDING",
    llm_model: str = "openai:qwen2.5-coder:1.5b",
    llm_provider: str = "openai:qwen2.5-coder:1.5b",
    llm_calls_total: int = 1,
    fail_count: int = 0,
    include_deterministic: bool = True,
    deterministic_status: str = "PASS",
) -> dict[str, Any]:
    controls: list[dict[str, Any]] = [
        {
            "id": "OSPS-BR-07.02",
            "status": llm_status,
            "authority": "suggestive",
            "evidence": {
                "llm_model": llm_model,
                "llm_reasoning": "Model candidate proposal",
            },
        }
    ]
    if include_deterministic:
        controls.append(
            {
                "id": "OSPS-AC-04.02",
                "status": deterministic_status,
                "authority": "dispositive",
                "evidence": {},
            }
        )

    return {
        "harness_version": "1.0",
        "target": {
            "local_path": "/tmp/wtf-frontend",
            "owner": "whiskeytastingfoundation",
            "repo": "wtf-frontend",
        },
        "summary": {
            "total": len(controls),
            "pass": 1 if deterministic_status == "PASS" else 0,
            "fail": fail_count,
            "warn": 0,
            "n_a": 0,
            "error": 0,
        },
        "controls": controls,
        "pending_feedback": [],
        "answer_sources_used": [],
        "llm_calls": {
            "total": llm_calls_total,
            "provider": llm_provider,
        },
    }


def test_valid_report():
    report = _build_sample_report()
    expected_controls = {"OSPS-AC-04.02": {"before": "PASS"}}

    violations = verify_harness_report(
        report,
        expected_model="qwen2.5-coder:1.5b",
        expected_provider="openai",
        expected_controls=expected_controls,
        harness_exit_code=0,
    )
    assert not violations


def test_safety_violation_unilateral_pass():
    # LLM cannot unilaterally yield PASS
    report = _build_sample_report(llm_status="PASS")

    violations = verify_harness_report(
        report,
        expected_model="qwen2.5-coder:1.5b",
        expected_provider="openai",
    )
    assert any("[Safety]" in v and "OSPS-BR-07.02" in v for v in violations)


def test_safety_violation_unexpected_status():
    report = _build_sample_report(llm_status="UNKNOWN_STATUS")

    violations = verify_harness_report(
        report,
        expected_model="qwen2.5-coder:1.5b",
        expected_provider="openai",
    )
    assert any("[Safety]" in v and "unexpected status" in v for v in violations)


def test_attribution_violation_wrong_model():
    report = _build_sample_report(llm_model="openai:wrong-model")

    violations = verify_harness_report(
        report,
        expected_model="qwen2.5-coder:1.5b",
        expected_provider="openai",
    )
    assert any("[Attribution]" in v and "evidence['llm_model']" in v for v in violations)


def test_attribution_missing_llm_model():
    report = _build_sample_report()
    # Remove llm_model from evidence
    del report["controls"][0]["evidence"]["llm_model"]

    violations = verify_harness_report(
        report,
        expected_model="qwen2.5-coder:1.5b",
        expected_provider="openai",
    )
    assert any("[Attribution]" in v and "missing 'llm_model'" in v for v in violations)


def test_attribution_violation_wrong_provider():
    report = _build_sample_report(llm_provider="openai:other-model")

    violations = verify_harness_report(
        report,
        expected_model="qwen2.5-coder:1.5b",
        expected_provider="openai",
    )
    assert any("[Attribution]" in v and "llm_calls['provider']" in v for v in violations)


def test_accounting_violation_mismatch():
    report = _build_sample_report(llm_calls_total=5)

    violations = verify_harness_report(
        report,
        expected_model="qwen2.5-coder:1.5b",
        expected_provider="openai",
    )
    assert any("[Accounting]" in v and "does not match" in v for v in violations)


def test_accounting_violation_zero_calls():
    report = _build_sample_report(llm_calls_total=0)

    violations = verify_harness_report(
        report,
        expected_model="qwen2.5-coder:1.5b",
        expected_provider="openai",
    )
    assert any("[Accounting]" in v and "expected > 0" in v for v in violations)


def test_parity_violation_deterministic_mismatch():
    report = _build_sample_report(deterministic_status="FAIL")
    expected_controls = {"OSPS-AC-04.02": {"before": "PASS"}}

    violations = verify_harness_report(
        report,
        expected_model="qwen2.5-coder:1.5b",
        expected_provider="openai",
        expected_controls=expected_controls,
    )
    assert any("[Parity]" in v and "OSPS-AC-04.02" in v for v in violations)


def test_exit_code_contract():
    # 0 fails, exit code 0 -> valid
    report_zero_fail = _build_sample_report(fail_count=0)
    assert not verify_harness_report(report_zero_fail, harness_exit_code=0)

    # 0 fails, exit code 1 -> violation
    v1 = verify_harness_report(report_zero_fail, harness_exit_code=1)
    assert any("[ExitCode]" in v for v in v1)

    # 1 fail, exit code 1 -> valid
    report_one_fail = _build_sample_report(fail_count=1)
    assert not verify_harness_report(report_one_fail, harness_exit_code=1)

    # 1 fail, exit code 0 -> violation
    v2 = verify_harness_report(report_one_fail, harness_exit_code=0)
    assert any("[ExitCode]" in v for v in v2)

    # Exit code 2 or 3 -> setup or internal error
    v3 = verify_harness_report(report_zero_fail, harness_exit_code=2)
    assert any("[ExitCode]" in v and "error code 2" in v for v in v3)


def test_min_answered_satisfied():
    # 1 LLM control with status PENDING (non-ERROR) -> satisfied
    report = _build_sample_report(llm_status="PENDING")
    violations = verify_harness_report(report, min_answered=1)
    assert not violations


def test_min_answered_violation():
    # 1 LLM control with status ERROR -> 0 answered, fails min_answered=1
    report = _build_sample_report(llm_status="ERROR")
    violations = verify_harness_report(report, min_answered=1)
    assert any("[Inference]" in v and "Only 0/1 LLM judgments were answered" in v for v in violations)


def test_min_answered_default_threshold():
    # By default, fails if fewer than half are answered
    report_all_error = _build_sample_report(llm_status="ERROR")
    violations = verify_harness_report(report_all_error)
    assert any("[Inference]" in v and "Only 0/1 LLM judgments were answered" in v for v in violations)

    # If status is non-ERROR, passes by default
    report_pending = _build_sample_report(llm_status="PENDING")
    assert not verify_harness_report(report_pending)


def test_main_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    report_file = tmp_path / "report.json"
    report_data = _build_sample_report()
    report_file.write_text(json.dumps(report_data), encoding="utf-8")

    # Run main CLI with matching model and skipped parity
    rc = main(
        [
            "--report",
            str(report_file),
            "--model",
            "qwen2.5-coder:1.5b",
            "--no-parity-check",
            "--harness-exit-code",
            "0",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "Harness report verification PASSED" in captured.out

    # Run main CLI with failing report
    bad_report_file = tmp_path / "bad_report.json"
    bad_report_data = _build_sample_report(llm_status="PASS")
    bad_report_file.write_text(json.dumps(bad_report_data), encoding="utf-8")

    rc_fail = main(
        [
            "--report",
            str(bad_report_file),
            "--model",
            "qwen2.5-coder:1.5b",
            "--no-parity-check",
        ]
    )
    assert rc_fail == 1
    captured_fail = capsys.readouterr()
    assert "Harness report verification FAILED" in captured_fail.out
    assert "[Safety]" in captured_fail.out

    # Run main CLI with min-answered check
    rc_min_pass = main(
        [
            "--report",
            str(report_file),
            "--model",
            "qwen2.5-coder:1.5b",
            "--no-parity-check",
            "--min-answered",
            "1",
        ]
    )
    assert rc_min_pass == 0

    rc_min_fail = main(
        [
            "--report",
            str(report_file),
            "--model",
            "qwen2.5-coder:1.5b",
            "--no-parity-check",
            "--min-answered",
            "5",
        ]
    )
    assert rc_min_fail == 1
    captured_min_fail = capsys.readouterr()
    assert "[Inference]" in captured_min_fail.out
