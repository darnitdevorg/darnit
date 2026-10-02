"""Outcomes say what remediation actually did (feature 043, US4, SC-004, quickstart V5).

A mixed fixture runs through the real orchestrator, executor and re-check
(framework-design.md 15.4, 15.5):

| Control  | Fixture case                     | Expected outcome                 |
|----------|----------------------------------|----------------------------------|
| T-SEC    | SECURITY.md exists               | ``unchanged`` / already_exists   |
| T-CONTRIB| CONTRIBUTING.md created          | ``fixed``                        |
| T-STILL  | changed but still failing        | ``changed_not_passing``          |
| T-LOOKUP | re-check lookup fails            | ``changed_not_verified``         |
| T-ERR    | handler error                    | ``error``                        |
| T-INC    | handler returns INCONCLUSIVE     | never ``fixed``                  |
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from darnit.config.framework_schema import (
    ControlConfig,
    FrameworkConfig,
    FrameworkMetadata,
    HandlerInvocation,
    RemediationConfig,
)
from darnit.config.merger import merge_configs
from darnit.core import audit_cache
from darnit.remediation.plan import FileChange
from darnit.sieve.handler_registry import HandlerResult, HandlerResultStatus, get_sieve_handler_registry
from darnit.tools import audit
from darnit_baseline.remediation import orchestrator

OWNER, REPO = "example-org", "example"
INCONCLUSIVE_HANDLER = "test_inconclusive_remediation"


def _present(path: str) -> list[HandlerInvocation]:
    return [HandlerInvocation(handler="file_exists", files=[path], existence=True)]


def _create(path: str) -> RemediationConfig:
    return RemediationConfig(handlers=[HandlerInvocation(handler="file_create", path=path, content=f"# {path}\n")])


def _control(passes: list[HandlerInvocation], remediation: RemediationConfig) -> ControlConfig:
    return ControlConfig(name="Test", description="Test control", level=1, passes=passes, remediation=remediation)


FRAMEWORK = FrameworkConfig(
    metadata=FrameworkMetadata(name="openssf-baseline", display_name="Test", version="1.0"),
    controls={
        "T-SEC": _control(_present("SECURITY.md"), _create("SECURITY.md")),
        "T-CONTRIB": _control(_present("CONTRIBUTING.md"), _create("CONTRIBUTING.md")),
        "T-STILL": _control(_present("REQUIRED.md"), _create("NOTES.md")),
        "T-LOOKUP": _control(
            [HandlerInvocation(handler="exec", command=["darnit-test-no-such-binary"])], _create("LOOKUP.md")
        ),
        "T-ERR": _control(_present("ERR.md"), RemediationConfig(handlers=[HandlerInvocation(handler="no_such_handler")])),
        "T-INC": _control(
            _present("INC.md"), RemediationConfig(handlers=[HandlerInvocation(handler=INCONCLUSIVE_HANDLER)])
        ),
    },
)
EXPECTED = {
    "T-SEC": "unchanged",
    "T-CONTRIB": "fixed",
    "T-STILL": "changed_not_passing",
    "T-LOOKUP": "changed_not_verified",
    "T-ERR": "error",
    "T-INC": "unchanged",
}


def _inconclusive(config: dict, context) -> HandlerResult:
    change = FileChange(path="INC.md", action="create", content="# INC\n")
    return HandlerResult(
        status=HandlerResultStatus.INCONCLUSIVE,
        message="could not decide",
        evidence={"file_changes": [change.model_dump(mode="json")]},
    )


@pytest.fixture(autouse=True)
def inconclusive_handler():
    registry = get_sieve_handler_registry()
    registry.register(INCONCLUSIVE_HANDLER, phase="deterministic", handler_fn=_inconclusive, supports_plan=True)
    yield
    registry._handlers.pop(INCONCLUSIVE_HANDLER, None)


@pytest.fixture(autouse=True)
def synthetic_framework(monkeypatch: pytest.MonkeyPatch) -> None:
    results = [{"id": cid, "status": "FAIL"} for cid in FRAMEWORK.controls]
    monkeypatch.setattr(orchestrator, "_get_framework_config", lambda: FRAMEWORK)
    monkeypatch.setattr(audit_cache, "read_audit_cache", lambda *_a, **_k: {"results": results})


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "T"]):
        subprocess.run(["git", *args], cwd=path, check=True)
    (path / "SECURITY.md").write_text("# Existing policy\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return path


def _run_block(output: str) -> dict:
    blocks = re.findall(r"```json\n(.*?)\n```", output, re.DOTALL)
    assert blocks, output
    return json.loads(blocks[-1])


def _apply(repo: Path) -> tuple[str, dict]:
    output = orchestrator.remediate_audit_findings(local_path=str(repo), owner=OWNER, repo=REPO, dry_run=False)
    return output, _run_block(output)


def _specs() -> list:
    from darnit.config.control_loader import load_controls_from_effective

    return load_controls_from_effective(merge_configs(FRAMEWORK))


def _fresh_audit(repo: Path) -> dict[str, str]:
    results, _ = audit.run_sieve_audit(
        OWNER, REPO, str(repo), "main", controls=_specs(), framework_name="openssf-baseline", write_cache=False
    )
    return {r["id"]: r["status"] for r in results}


@pytest.mark.integration
def test_each_case_gets_its_own_outcome(repo: Path) -> None:
    _, run = _apply(repo)

    outcomes = {o["control_id"]: o for o in run["outcomes"]}
    assert {cid: o["kind"] for cid, o in outcomes.items()} == EXPECTED
    assert "already_exists" in outcomes["T-SEC"]["reason"]
    assert outcomes["T-SEC"]["recheck"] is None, "a control whose remediation changed nothing is not re-checked"
    assert outcomes["T-CONTRIB"]["recheck"]["status"] == "PASS"
    assert [c["path"] for c in outcomes["T-CONTRIB"]["file_changes"]] == ["CONTRIBUTING.md"]
    assert outcomes["T-STILL"]["recheck"]["status"] != "PASS"
    assert outcomes["T-LOOKUP"]["recheck"]["status"] == "ERROR"
    assert outcomes["T-LOOKUP"]["error"]["class"] == "missing_tool"
    assert outcomes["T-ERR"]["error"]["cause"]
    assert "inconclusive" in outcomes["T-INC"]["reason"]
    assert not (repo / "INC.md").exists(), "an INCONCLUSIVE step's changes are not written"


@pytest.mark.integration
def test_summary_counts_equal_outcome_counts(repo: Path) -> None:
    output, run = _apply(repo)

    counts = Counter(o["kind"] for o in run["outcomes"])
    assert {k: v for k, v in run["summary"].items() if v} == dict(counts)
    report = output.split("```json")[0]
    for kind, count in counts.items():
        assert f"| {kind} | {count} |" in report


@pytest.mark.integration
def test_every_fixed_control_passes_a_fresh_audit(repo: Path) -> None:
    _, run = _apply(repo)

    fresh = _fresh_audit(repo)
    fixed = [o["control_id"] for o in run["outcomes"] if o["kind"] == "fixed"]
    assert fixed == ["T-CONTRIB"]
    assert all(fresh[cid] == "PASS" for cid in fixed)
    unchanged_targets = [o["control_id"] for o in run["outcomes"] if not o["file_changes"] and not o["change_sets"]]
    assert not set(unchanged_targets) & set(fixed)


@pytest.mark.integration
def test_recheck_leaves_the_full_audit_cache_byte_identical(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audit_cache.write_audit_cache(str(repo), [{"id": "T-SEC", "status": "FAIL"}], {"FAIL": 1}, 3, "openssf-baseline")
    cache_file = audit_cache._get_cache_dir(str(repo)) / audit_cache.CACHE_FILENAME
    before = cache_file.read_bytes()
    invalidated: list[str] = []
    monkeypatch.setattr(audit_cache, "invalidate_audit_cache", lambda path, **_k: invalidated.append(path))

    _, run = _apply(repo)

    assert any(o["recheck"] for o in run["outcomes"]), "the re-check ran"
    assert cache_file.read_bytes() == before
    assert invalidated == [str(repo)], "a run that changed files invalidates the cache once, after the re-check"


@pytest.mark.integration
def test_recheck_that_cannot_run_is_not_verified(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_a, **_k):
        raise RuntimeError("sieve unavailable")

    monkeypatch.setattr(audit, "run_sieve_audit", broken)

    _, run = _apply(repo)

    changed = [o for o in run["outcomes"] if any(c["action"] != "none" for c in o["file_changes"])]
    assert {o["control_id"] for o in changed} == {"T-CONTRIB", "T-STILL", "T-LOOKUP"}
    for outcome in changed:
        assert outcome["kind"] == "changed_not_verified"
        assert "sieve unavailable" in outcome["error"]["cause"]


@pytest.mark.integration
def test_preview_has_no_outcomes_and_writes_nothing(repo: Path) -> None:
    output = orchestrator.remediate_audit_findings(local_path=str(repo), owner=OWNER, repo=REPO)

    run = _run_block(output)
    assert run["mode"] == "preview" and run["outcomes"] == []
    assert not (repo / "CONTRIBUTING.md").exists()


@pytest.mark.integration
def test_run_sieve_audit_without_cache_write(repo: Path) -> None:
    cache_file = audit_cache._get_cache_dir(str(repo)) / audit_cache.CACHE_FILENAME
    cache_file.unlink(missing_ok=True)

    audit.run_sieve_audit(OWNER, REPO, str(repo), "main", controls=_specs(), framework_name="openssf-baseline", write_cache=False)
    assert not cache_file.exists()

    audit.run_sieve_audit(OWNER, REPO, str(repo), "main", controls=_specs(), framework_name="openssf-baseline")
    assert cache_file.exists()
