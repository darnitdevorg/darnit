"""Audits and queries never write project data (feature 042, US1, FR-001, FR-002, SC-001)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from darnit.config.context_resolve import resolve_context
from darnit.config.context_schema import OriginKind, Standing
from darnit.core.llm_step import LLMJudgment, MockLLMStep
from darnit.harness.driver import HarnessRun
from darnit.server.tools.builtin_audit import builtin_audit
from darnit_baseline.remediation.orchestrator import remediate_audit_findings as remediate_dry_run
from darnit_baseline.tools import audit_openssf_baseline, get_pending_data, remediate_audit_findings

from .conftest import assert_unchanged, snapshot

REPOSITORIES = ["R-maint", "R-ci", "R-legacy", "empty"]


def _harness(local_path: str) -> HarnessRun:
    return HarnessRun(
        local_path=local_path,
        framework_name="openssf-baseline",
        level=1,
        answer_resolver=HarnessRun.build_default_resolver(local_path),
        llm_step=MockLLMStep(
            LLMJudgment(outcome="yes", confidence=0.95, reasoning="mock", raw_response={"provider": "mock"})
        ),
        per_call_timeout_s=10,
        total_run_timeout_s=120,
    )


def _pending_keys(payload: str) -> set[str]:
    data = json.loads(payload[payload.index("{") :])
    if "answer_mapping" in data:
        return {m["context_key"] for m in data["answer_mapping"]}
    return {q["key"] for q in data.get("questions", [])}


@pytest.mark.integration
@pytest.mark.parametrize("name", REPOSITORIES)
def test_no_read_path_writes(name: str, scratch_repo: Callable[[str], Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    repo = scratch_repo(name)
    local_path = str(repo)
    before = snapshot(repo)

    audit_openssf_baseline(local_path=local_path, level=1)
    assert_unchanged(repo, before)

    asyncio.run(builtin_audit(local_path=local_path, level=1, _framework_name="openssf-baseline"))
    assert_unchanged(repo, before)

    get_pending_data(local_path=local_path, limit=0)
    assert_unchanged(repo, before)

    remediate_audit_findings(local_path=local_path, dry_run=True)
    assert_unchanged(repo, before)

    # The tool's context guard stops early while keys are pending; run the
    # dry-run remediation itself as well.
    remediate_dry_run(local_path=local_path, categories=["all"], dry_run=True)
    assert_unchanged(repo, before)

    asyncio.run(_harness(local_path).run())
    assert_unchanged(repo, before)

    confirmed = [
        v.key for v in resolve_context(local_path, detect=False).values.values() if v.standing is Standing.CONFIRMED
    ]
    assert confirmed == []


@pytest.mark.integration
def test_stored_values_without_records_are_pending(scratch_repo: Callable[[str], Path]) -> None:
    repo = scratch_repo("R-legacy")

    pending = _pending_keys(get_pending_data(local_path=str(repo), limit=0))

    assert {"maintainers", "ci_provider"} <= pending


@pytest.mark.integration
def test_pending_carries_the_candidate_and_its_origin(scratch_repo: Callable[[str], Path]) -> None:
    from darnit.config.context_storage import get_pending_context

    repo = scratch_repo("R-legacy")

    pending = {req.key: req for req in get_pending_context(str(repo))}

    candidate = pending["maintainers"].candidate
    assert candidate.standing is Standing.CANDIDATE
    assert candidate.value == ["@alice", "@realcorp"]
    assert candidate.origin.kind is OriginKind.STORED_UNCONFIRMED
    assert candidate.location == ".project/darnit.yaml:context.maintainers"
