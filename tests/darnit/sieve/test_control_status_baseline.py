"""SC-008: adding the conclusive WARN outcome changed no existing control.

This is the claim that makes the framework change acceptable, and it is the
kind of claim that is easy to assert and hard to notice breaking.

It is deliberately NOT a committed golden of control statuses. That was tried
first and it fails for a reason worth recording: control statuses depend on the
environment as much as on the code. Seven OSPS controls resolve FAIL on a
developer machine and WARN on a CI runner, so a golden captured in one
environment can never pass in the other -- it pins the runner, not the change.

Instead the corpus is captured twice in the SAME environment: once normally,
and once with the WARN outcome routed the way it was routed before feature 037
(a handler could not express WARN, so the faithful simulation is INCONCLUSIVE).
Whatever the environment does, it does identically to both runs and cancels.

Any control whose status differs between the two is a control this feature
changed.
"""

from __future__ import annotations

import pytest

from .baseline_capture import PARITY_FIXTURES, capture, capture_details

# #584: `github_workflows_present`, the first step of these controls, returns
# WARN by design on a repository with nothing for them to audit. Neutralized,
# the controls run on to zizmor and grep instead: ERROR where the tool is not
# installed; PASS for the zizmor controls where the suite's zizmor stand-in
# (tests/conftest.py), which answers "no findings" whatever it is given, is on
# PATH; else the same WARN, which is no drift. BR-01.02's grep step concludes
# nothing, so it never PASSes. Those statuses before the WARN are the only
# drift tolerated.
WARN_BY_DESIGN = {
    "OSPS-BR-01.01": {"ERROR", "PASS"},
    "OSPS-BR-01.02": {"ERROR"},
    "OSPS-AC-04.02": {"ERROR", "PASS"},
}


def _nothing_to_audit(repo: str) -> bool:
    """No workflow file, and no action definition (which BR-01.01's zizmor audit reads)."""
    root = PARITY_FIXTURES / repo
    workflows = root / ".github" / "workflows"
    if any(p.suffix.lower() in (".yml", ".yaml") for p in workflows.glob("*")):
        return False
    return not any(p.name.lower() in ("action.yml", "action.yaml") for p in root.rglob("*"))


def _warn_by_design(pair: str, control_id: str, before: str | None, after: dict[str, str] | None) -> bool:
    framework, _, repo = pair.partition("::")
    return (
        framework == "openssf-baseline"
        and before in WARN_BY_DESIGN.get(control_id, set())
        and after is not None
        and after["status"] == "WARN"
        and after["details"].startswith("No GitHub Actions workflow files")
        and "nothing to audit" in after["details"]
        and _nothing_to_audit(repo)
    )


NO_WORKFLOWS_WARN = {
    "status": "WARN",
    "details": "No GitHub Actions workflow files (.github/workflows/*.yml or *.yaml) were found, "
    "so there is nothing to audit.",
}


@pytest.mark.parametrize(
    ("control_id", "before"),
    [("OSPS-BR-01.01", "ERROR"), ("OSPS-BR-01.01", "PASS"), ("OSPS-AC-04.02", "PASS"), ("OSPS-BR-01.02", "ERROR")],
)
def test_tolerated_drift(control_id: str, before: str) -> None:
    assert _warn_by_design("openssf-baseline::empty_repo", control_id, before, NO_WORKFLOWS_WARN)


@pytest.mark.parametrize(
    ("pair", "control_id", "before", "after"),
    [
        ("openssf-baseline::empty_repo", "OSPS-BR-01.02", "PASS", NO_WORKFLOWS_WARN),
        ("openssf-baseline::empty_repo", "OSPS-BR-01.01", "FAIL", NO_WORKFLOWS_WARN),
        ("openssf-baseline::empty_repo", "OSPS-BR-01.01", "WARN", NO_WORKFLOWS_WARN),
        ("openssf-baseline::empty_repo", "OSPS-BR-01.01", None, NO_WORKFLOWS_WARN),
        ("openssf-baseline::empty_repo", "OSPS-AC-04.01", "PASS", NO_WORKFLOWS_WARN),
        ("reproducibility::empty_repo", "OSPS-BR-01.01", "PASS", NO_WORKFLOWS_WARN),
        ("openssf-baseline::empty_repo", "OSPS-BR-01.01", "PASS", {**NO_WORKFLOWS_WARN, "status": "FAIL"}),
        ("openssf-baseline::empty_repo", "OSPS-BR-01.01", "PASS", {"status": "WARN", "details": "Could not verify"}),
        ("openssf-baseline::empty_repo", "OSPS-BR-01.01", "PASS", None),
    ],
)
def test_other_drift_is_not_tolerated(pair: str, control_id: str, before: str | None, after) -> None:
    assert not _warn_by_design(pair, control_id, before, after)


@pytest.mark.parametrize(
    "path", [".github/workflows/ci.yml", ".github/workflows/ci.YAML", "action.yml", "a/action.yaml"]
)
def test_no_drift_is_tolerated_on_a_fixture_with_inputs(path: str, tmp_path, monkeypatch) -> None:
    import sys

    monkeypatch.setattr(sys.modules[__name__], "PARITY_FIXTURES", tmp_path)
    (tmp_path / "repo" / path).parent.mkdir(parents=True)
    (tmp_path / "repo" / path).write_text("on: push\n", encoding="utf-8")

    assert not _warn_by_design("openssf-baseline::repo", "OSPS-BR-01.01", "PASS", NO_WORKFLOWS_WARN)


@pytest.mark.integration
def test_warn_outcome_changes_no_existing_control() -> None:
    """SC-008 / FR-017.

    Only `github_workflows_present` returns WARN (#584), so neutralizing the
    outcome must be invisible everywhere else. A difference here means either
    another handler started returning WARN or the disposition refactor changed
    how PASS/FAIL/INCONCLUSIVE are routed.
    """
    with_details = capture_details()
    with_warn = {
        pair: {control_id: result["status"] for control_id, result in controls.items()}
        for pair, controls in with_details.items()
    }
    without_warn = capture(neutralize=True)

    assert set(with_warn) == set(without_warn), "corpus pairs differ between runs"

    drift: dict[str, dict[str, tuple[str | None, str | None]]] = {}
    for pair in sorted(with_warn):
        changed = {
            control_id: (without_warn[pair].get(control_id), with_warn[pair].get(control_id))
            for control_id in set(with_warn[pair]) | set(without_warn[pair])
            if with_warn[pair].get(control_id) != without_warn[pair].get(control_id)
            and not _warn_by_design(
                pair, control_id, without_warn[pair].get(control_id), with_details[pair].get(control_id)
            )
        }
        if changed:
            drift[pair] = changed

    assert not drift, (
        "adding the WARN outcome changed existing control statuses "
        f"(before -> after): {drift}"
    )


@pytest.mark.integration
def test_corpus_is_non_empty() -> None:
    """Guards the assertion above against passing vacuously.

    A corpus that silently collapsed to zero controls -- a framework failing to
    load, a fixture path moving -- would make the drift check trivially true.
    """
    captured = capture()
    assert captured, "corpus produced no pairs"
    total = sum(len(controls) for controls in captured.values())
    assert total > 100, f"corpus collapsed to {total} controls"
