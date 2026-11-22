"""Report invariant verification for model providers and scheduled smoke tests (#781, #780, #783).

Validates that an end-to-end darnit harness audit report adheres to:
1. Safety Contract (Principle IV): Model judgments never unilaterally yield PASS.
   Statuses must strictly be in {PENDING, FAIL, WARN, ERROR}.
2. Attribution Contract (Framework Design 14.1 / #780 / #764):
   Every model judgment records llm_model matching f"{provider}:{model}".
   The report's top-level llm_calls["provider"] matches f"{provider}:{model}".
3. Accounting Contract:
   llm_calls["total"] > 0 and matches the number of controls that consulted the LLM.
4. Deterministic Parity Contract:
   Controls not evaluated by the LLM strictly match the recorded baseline from
   scripts/comply_replay_expected.json for the audited reference repository (wtf-frontend).
5. Exit Code Contract:
   Follows HarnessExitCode specification (0 for clean runs, 1 for audit failures,
   never 2 setup error or 3 internal error).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EXPECTED_PATH = REPO_ROOT / "scripts" / "comply_replay_expected.json"

VALID_LLM_STATUSES = frozenset({"PENDING", "FAIL", "WARN", "ERROR"})


def is_llm_evaluated(control: dict[str, Any]) -> bool:
    """Return True if the control was evaluated by an LLM."""
    evidence = control.get("evidence") or {}
    return bool(
        "llm_model" in evidence
        or "llm_consultation" in evidence
        or "llm_reasoning" in evidence
        or control.get("concluded_by") in ("llm_judgment", "llm_eval")
    )


def verify_control_llm_judgment(
    control: dict[str, Any],
    *,
    expected_provider: str = "openai",
    expected_model: str | None = None,
) -> list[str]:
    """Verify invariants for a single control evaluated by an LLM."""
    violations: list[str] = []
    cid = control.get("id", "unknown")
    status = control.get("status")

    # Safety: Never PASS
    if status == "PASS":
        violations.append(
            f"[Safety] Control {cid} was evaluated by LLM but has status 'PASS'. "
            "Principle IV requires human confirmation; LLMs may only propose candidates "
            "(status PENDING) or conclude FAIL/WARN/ERROR."
        )
    elif status not in VALID_LLM_STATUSES:
        violations.append(
            f"[Safety] Control {cid} was evaluated by LLM but has unexpected status {status!r}. "
            f"Expected one of: {sorted(VALID_LLM_STATUSES)}."
        )

    # Attribution
    evidence = control.get("evidence") or {}
    ctrl_model = evidence.get("llm_model")
    if not ctrl_model:
        violations.append(f"[Attribution] Control {cid} was evaluated by LLM but is missing 'llm_model' in evidence.")
    elif expected_model:
        expected_tagged = f"{expected_provider}:{expected_model}"
        if ctrl_model != expected_tagged:
            violations.append(
                f"[Attribution] Control {cid} evidence['llm_model'] is {ctrl_model!r}, expected {expected_tagged!r}."
            )

    return violations


def verify_deterministic_parity(
    controls: list[dict[str, Any]],
    expected_controls: dict[str, Any],
    llm_control_ids: set[str],
) -> list[str]:
    """Verify non-LLM controls against baseline recorded outcomes."""
    violations: list[str] = []
    actual_by_id = {c.get("id"): c for c in controls if c.get("id")}

    for cid, exp in expected_controls.items():
        if cid in llm_control_ids:
            # Model-evaluated controls may legitimately vary based on model inference
            continue

        expected_status = exp.get("before")
        if not expected_status:
            continue

        if cid not in actual_by_id:
            violations.append(f"[Parity] Deterministic control {cid} is missing from the audit report.")
            continue

        actual_status = actual_by_id[cid].get("status")
        if actual_status != expected_status:
            violations.append(
                f"[Parity] Deterministic control {cid} status is {actual_status!r}, "
                f"expected baseline {expected_status!r}."
            )

    return violations


def verify_harness_report(
    report: dict[str, Any],
    *,
    expected_model: str | None = None,
    expected_provider: str = "openai",
    reference_repo: str = "wtf-frontend",
    expected_controls: dict[str, Any] | None = None,
    expected_baseline_path: Path | None = None,
    harness_exit_code: int | None = None,
    min_answered: int | None = None,
) -> list[str]:
    """Verify all 5 harness report invariants (and optional min-answered threshold)."""
    violations: list[str] = []

    controls = report.get("controls") or []
    summary = report.get("summary") or {}
    llm_calls = report.get("llm_calls") or {}

    llm_controls = [c for c in controls if is_llm_evaluated(c)]
    llm_control_ids = {c.get("id") for c in llm_controls if c.get("id")}
    expected_tagged = f"{expected_provider}:{expected_model}" if expected_model else None

    # Invariant 1 & 2: Safety and Attribution per control
    for ctrl in llm_controls:
        violations.extend(
            verify_control_llm_judgment(
                ctrl,
                expected_provider=expected_provider,
                expected_model=expected_model,
            )
        )

    # Invariant: Minimum answered (usable) model judgments
    if llm_controls:
        answered_controls = [c for c in llm_controls if c.get("status") != "ERROR"]
        error_controls = [c for c in llm_controls if c.get("status") == "ERROR"]
        required_answered = min_answered if min_answered is not None else ((len(llm_controls) + 1) // 2)
        if len(answered_controls) < required_answered:
            violations.append(
                f"[Inference] Only {len(answered_controls)}/{len(llm_controls)} LLM judgments were answered "
                f"(status not 'ERROR'); expected at least {required_answered}. "
                f"{len(error_controls)} judgment(s) ended in ERROR."
            )

    # Invariant 2b: Attribution at report level
    if expected_tagged:
        provider_in_report = llm_calls.get("provider")
        if provider_in_report != expected_tagged:
            violations.append(
                f"[Attribution] Report llm_calls['provider'] is {provider_in_report!r}, expected {expected_tagged!r}."
            )

    # Invariant 3: Accounting
    total_calls = llm_calls.get("total", 0)
    if total_calls <= 0:
        violations.append(f"[Accounting] llm_calls['total'] is {total_calls}, expected > 0.")
    if len(llm_controls) != total_calls:
        violations.append(
            f"[Accounting] Count of LLM-evaluated controls ({len(llm_controls)}) "
            f"does not match llm_calls['total'] ({total_calls})."
        )

    # Invariant 4: Deterministic Parity against reference baseline
    baseline_controls = expected_controls
    if baseline_controls is None and expected_baseline_path:
        if not expected_baseline_path.is_file():
            violations.append(f"[Parity] Expected baseline file {expected_baseline_path} not found.")
        else:
            try:
                baseline_data = json.loads(expected_baseline_path.read_text(encoding="utf-8"))
                baseline_controls = baseline_data.get(reference_repo, {}).get("controls")
                if not baseline_controls:
                    violations.append(
                        f"[Parity] Reference repository {reference_repo!r} controls not found in {expected_baseline_path}."
                    )
            except Exception as exc:
                violations.append(f"[Parity] Failed to load baseline {expected_baseline_path}: {exc}")

    if baseline_controls is not None:
        violations.extend(verify_deterministic_parity(controls, baseline_controls, llm_control_ids))

    # Invariant 5: Harness Exit Code Contract
    if harness_exit_code is not None:
        fail_count = summary.get("fail", 0)
        expected_code = 1 if fail_count > 0 else 0
        if harness_exit_code not in (0, 1):
            violations.append(
                f"[ExitCode] Harness exited with error code {harness_exit_code} "
                "(expected 0 for clean run or 1 for audit failures)."
            )
        elif harness_exit_code != expected_code:
            violations.append(
                f"[ExitCode] Harness exited with {harness_exit_code}, but summary.fail is "
                f"{fail_count} (expected exit code {expected_code})."
            )

    return violations


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify invariants of a darnit harness report (#781, #780).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Path to the JSON report produced by `darnit harness`.",
    )
    parser.add_argument(
        "--expected",
        type=Path,
        default=DEFAULT_EXPECTED_PATH,
        help="Path to comply_replay_expected.json for deterministic parity (default: scripts/comply_replay_expected.json).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Expected model name (e.g. qwen2.5-coder:1.5b).",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="openai",
        help="Expected LLM provider (default: openai).",
    )
    parser.add_argument(
        "--reference-repo",
        type=str,
        default="wtf-frontend",
        help="Reference repository key in expected file (default: wtf-frontend).",
    )
    parser.add_argument(
        "--harness-exit-code",
        type=int,
        default=None,
        help="Exit code returned by `darnit harness`.",
    )
    parser.add_argument(
        "--no-parity-check",
        action="store_true",
        help="Skip deterministic control parity check against expected baseline.",
    )
    parser.add_argument(
        "--min-answered",
        type=int,
        default=None,
        help="Minimum number of LLM judgments that must end in non-ERROR status (e.g. FAIL, WARN, PENDING).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.report.is_file():
        sys.stderr.write(f"Error: report file {args.report} does not exist.\n")
        return 2

    try:
        report_data = json.loads(args.report.read_text(encoding="utf-8"))
    except Exception as exc:
        sys.stderr.write(f"Error reading report {args.report}: {exc}\n")
        return 2

    baseline_path = None if args.no_parity_check else args.expected

    violations = verify_harness_report(
        report_data,
        expected_model=args.model,
        expected_provider=args.provider,
        reference_repo=args.reference_repo,
        expected_baseline_path=baseline_path,
        harness_exit_code=args.harness_exit_code,
        min_answered=args.min_answered,
    )

    controls = report_data.get("controls") or []
    controls_count = len(controls)
    llm_controls = [c for c in controls if is_llm_evaluated(c)]
    llm_count = len(llm_controls)
    llm_control_ids = {c.get("id") for c in llm_controls if c.get("id")}
    answered_count = sum(1 for c in llm_controls if c.get("status") != "ERROR")
    error_count = sum(1 for c in llm_controls if c.get("status") == "ERROR")

    llm_detail = (
        f"{llm_count} LLM-evaluated ({answered_count} answered, {error_count} error(s))"
        if llm_count
        else "0 LLM-evaluated"
    )

    deterministic_info = ""
    if baseline_path and baseline_path.is_file():
        try:
            baseline_data = json.loads(baseline_path.read_text(encoding="utf-8"))
            baseline_controls = baseline_data.get(args.reference_repo, {}).get("controls", {})
            checked_count = sum(
                1 for cid, exp in baseline_controls.items() if cid not in llm_control_ids and exp.get("before")
            )
            deterministic_info = f", {checked_count} deterministic controls verified against {baseline_path.name}"
        except Exception:
            pass

    if violations:
        print(f"Harness report verification FAILED ({len(violations)} violation(s)):")
        for v in violations:
            print(f"  - {v}")
        return 1

    print(
        f"Harness report verification PASSED ({controls_count} total controls: "
        f"{llm_detail}{deterministic_info}, all invariants satisfied)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
