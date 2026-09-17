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

from .baseline_capture import capture


@pytest.mark.integration
def test_warn_outcome_changes_no_existing_control() -> None:
    """SC-008 / FR-017.

    No existing handler returns WARN, so neutralizing the outcome must be
    invisible. A difference here means either a handler started returning WARN
    or the disposition refactor changed how PASS/FAIL/INCONCLUSIVE are routed.
    """
    with_warn = capture()
    without_warn = capture(neutralize=True)

    assert set(with_warn) == set(without_warn), "corpus pairs differ between runs"

    drift: dict[str, dict[str, tuple[str | None, str | None]]] = {}
    for pair in sorted(with_warn):
        changed = {
            control_id: (without_warn[pair].get(control_id), with_warn[pair].get(control_id))
            for control_id in set(with_warn[pair]) | set(without_warn[pair])
            if with_warn[pair].get(control_id) != without_warn[pair].get(control_id)
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
