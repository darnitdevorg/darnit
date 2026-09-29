"""A control's on_pass project_update is reported, never written, during an audit (feature 042, FR-001)."""

from __future__ import annotations

from pathlib import Path

from darnit.config.framework_schema import HandlerInvocation
from darnit.sieve.models import CheckContext, ControlSpec
from darnit.sieve.orchestrator import SieveOrchestrator


def _tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_on_pass_update_is_proposed_not_written(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# widget\n", encoding="utf-8")
    before = _tree(tmp_path)
    spec = ControlSpec(
        control_id="TEST-ONPASS-01",
        level=1,
        domain="TEST",
        name="ReadmeExists",
        description="A README exists",
        metadata={
            "handler_invocations": [HandlerInvocation(handler="file_exists", files=["README.md"], existence=True)],
            "on_pass": {"project_update": {"documentation.readme": "$EVIDENCE.relative_path"}},
        },
    )
    context = CheckContext(
        owner="example-org",
        repo="widget",
        local_path=str(tmp_path),
        default_branch="main",
        control_id="TEST-ONPASS-01",
        project_context={},
    )

    result = SieveOrchestrator().verify(spec, context)

    assert result.status == "PASS"
    assert _tree(tmp_path) == before
    assert not (tmp_path / ".project").exists()
    assert result.evidence["proposed_project_update"] == {"documentation.readme": "README.md"}
