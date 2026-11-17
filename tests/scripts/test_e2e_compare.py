"""scripts/e2e_compare.py: the comparison and transcript parsing, without builds, network or a model."""

from __future__ import annotations

import json

from scripts.e2e_compare import (
    clean_env,
    compare_comply,
    diff_controls,
    diff_files,
    diff_surface,
    differs,
    parse_transcript,
    render,
)


def _c(status: str, level: int = 1, by: str | None = None) -> dict:
    return {"level": level, "status": status, "concluded_by": by}


def test_diff_controls_names_each_change() -> None:
    base = {"A": _c("PASS"), "B": _c("FAIL"), "C": _c("WARN")}
    head = {"A": _c("PASS"), "B": _c("PENDING", by="llm_eval"), "D": _c("PASS")}
    assert diff_controls(base, head) == [
        "B: status FAIL > PENDING, concluded_by None > llm_eval",
        "C: removed",
        "D: added (PASS)",
    ]
    assert diff_controls(base, base) == []


def test_diff_surface_names_tools_and_fields() -> None:
    tool = {"name": "audit", "description": "Audit.", "inputSchema": {"type": "object"}}
    base = {"fw": {"audit": tool, "old": {"name": "old"}}, "gone": {}}
    head = {"fw": {"audit": {**tool, "description": "Audit it."}, "new": {"name": "new"}}, "gone": None}
    assert diff_surface(base, head) == [
        "fw: added new",
        "fw: removed old",
        "fw: changed audit (description)",
        "gone: not registered in head",
    ]


def test_diff_surface_framework_only_in_head() -> None:
    # Frameworks are listed per side, so a renamed one is absent from the other side.
    base = {"old-name": {"audit": {"name": "audit"}}}
    head = {"new-name": {"audit": {"name": "audit"}}}
    assert diff_surface(base, head) == [
        "new-name: registered in head",
        "new-name: added audit",
        "old-name: not registered in head",
        "old-name: removed audit",
    ]


def test_diff_files() -> None:
    assert diff_files(["A.md", "B.md"], ["B.md", "C.md"]) == ["no longer written: A.md", "now written: C.md"]


def _event(kind: str, **kw) -> str:
    return json.dumps({"type": kind, **kw})


def test_parse_transcript(tmp_path) -> None:
    spill = tmp_path / "mcp-darnit-remediate_audit_findings-1.txt"
    spill.write_text(json.dumps({"result": "# Remediation Applied\n\n### OSPS-DO-04.01: unchanged\n"}))
    applied = "# Remediation Applied\n\n### OSPS-GV-03.01: changed_not_passing\n- x\n### OSPS-BR-01.01: fixed\n"
    lines = [
        _event("system", subtype="init", model="m", mcp_servers=[{"name": "darnit", "status": "connected"}]),
        _event(
            "assistant",
            message={
                "content": [
                    {"type": "tool_use", "id": "1", "name": "mcp__darnit__remediate_audit_findings"},
                    {"type": "tool_use", "id": "2", "name": "Read"},
                ]
            },
        ),
        _event(
            "user",
            message={
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "1",
                        "content": [{"type": "text", "text": json.dumps({"result": applied})}],
                    },
                    {"type": "tool_result", "tool_use_id": "2", "is_error": True, "content": "File does not exist."},
                ]
            },
        ),
        "not json",
        _event(
            "assistant",
            message={
                "content": [
                    {"type": "tool_use", "id": "3", "name": "mcp__darnit__remediate_audit_findings"},
                ]
            },
        ),
        _event(
            "user",
            message={
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "3",
                        "content": (
                            f"Error: result (174,244 characters) exceeds maximum allowed tokens. "
                            f"Output has been saved to {spill}.\\nFormat: JSON with schema: {{result: string}}"
                        ),
                    },
                ]
            },
        ),
        _event(
            "result",
            num_turns=3,
            total_cost_usd=0.5,
            is_error=False,
            subtype="success",
            permission_denials=[{"tool_name": "mcp__darnit__confirm_pass_candidate"}],
            result="done",
        ),
    ]
    run = parse_transcript(lines)
    assert run["model"] == "m"
    assert run["mcp_servers"] == ["darnit:connected"]
    assert run["tool_calls"] == {"mcp__darnit__remediate_audit_findings": 2, "Read": 1}
    assert run["tool_errors"] == [{"tool": "Read", "error": "File does not exist."}]
    assert run["outcomes"] == {
        "OSPS-GV-03.01": "changed_not_passing",
        "OSPS-BR-01.01": "fixed",
        "OSPS-DO-04.01": "unchanged",
    }
    assert run["spilled"] == [{"tool": "mcp__darnit__remediate_audit_findings", "characters": 174244}]
    assert run["denials"] == ["mcp__darnit__confirm_pass_candidate"]
    assert run["turns"] == 3 and run["report"] == "done"


def _side(status: str, outcome: str, files: list[str], errors: list | None = None) -> dict:
    return {
        "final": {"A": _c(status)},
        "outcomes": {"A": outcome},
        "files": files,
        "tool_errors": errors or [],
        "denials": [],
        "tool_calls": {"x": 1},
        "model": "m",
        "turns": 1,
        "seconds": 1,
        "cost_usd": 1.0,
    }


def test_compare_comply_and_render() -> None:
    same = compare_comply(
        _side("PENDING", "changed_not_passing", ["A.md"]), _side("PENDING", "changed_not_passing", ["A.md"])
    )
    assert not differs({"4": same})
    base = _side("PENDING", "changed_not_passing", ["A.md"])
    head = _side("FAIL", "unchanged", [], errors=[{"tool": "t", "error": "boom"}])
    diff = compare_comply(base, head)
    assert diff["final_audit"] == ["A: status PENDING > FAIL"]
    assert diff["outcomes"] == ["A: changed_not_passing > unchanged"]
    assert diff["files"] == ["no longer written: A.md"]
    assert differs({"1": [], "4": diff})
    meta = {
        "base": "b" * 40,
        "head": "h" * 40,
        "head_build": "m" * 40,
        "reference": "r",
        "commit": "c",
        "url": "u",
        "phases": ["4"],
        "platform": "no",
    }
    report = render(meta, {"base": {"4": base}, "head": {"4": head}}, {"4": diff}, [])
    assert "- final audit: A: status PENDING > FAIL" in report
    assert "- head tool error: t: boom" in report
    assert report.isascii()


def test_clean_env_removes_tokens_and_ci(monkeypatch) -> None:
    for name, value in {
        "GH_TOKEN": "",
        "GITHUB_TOKEN": "t",
        "CI": "true",
        "GITHUB_ACTIONS": "true",
        "DARNIT_X": "1",
        "XDG_DATA_HOME": "/x",
        "KEEP_ME": "1",
    }.items():
        monkeypatch.setenv(name, value)
    env = clean_env()
    assert env["KEEP_ME"] == "1"
    assert not {"GH_TOKEN", "GITHUB_TOKEN", "CI", "GITHUB_ACTIONS", "DARNIT_X", "XDG_DATA_HOME"} & set(env)
