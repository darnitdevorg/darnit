"""Shared handlers are removed; declaring them fails loading (framework-design Appendix C).

A step referencing a ``[shared_handlers]`` entry cached its verdict after its
own control's ``expr`` ran, so a second control referencing the same entry got
that verdict without evaluating its own ``expr`` (a false PASS), and the
effective configuration never resolved the references. Each declaration now
fails loading on every path, naming the removal.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from darnit.cli import main as cli_main
from darnit.config.control_loader import load_controls_from_effective, load_controls_from_framework
from darnit.config.merger import load_effective_config, load_framework_config
from darnit.tools.audit import run_sieve_audit

REMOVED = "shared handlers were removed"

METADATA = """
[metadata]
name = "shared-removed"
display_name = "Shared removed"
version = "0.0.1"
spec_version = "t"
"""

SHARED_TABLE = (
    METADATA
    + """
[shared_handlers.probe]
handler = "exec"
command = ["sh", "-c", "echo '{\\"a\\": 1}'"]
output_format = "json"

[controls."SR-01"]
name = "Plain"
description = "A control that does not reference the shared handler"
level = 1
[[controls."SR-01".passes]]
handler = "exec"
command = ["sh", "-c", "echo '{\\"a\\": 1}'"]
output_format = "json"
expr = "output.json.a == 1"
"""
)

SHARED_STEP = (
    METADATA
    + """
[controls."SR-01"]
name = "First"
description = "Its expr holds"
level = 1
[[controls."SR-01".passes]]
handler = "exec"
shared = "probe"
command = ["sh", "-c", "echo '{\\"a\\": 1}'"]
output_format = "json"
expr = "output.json.a == 1"

[controls."SR-02"]
name = "Second"
description = "Its expr does not hold; the shared cache gave it the first control's PASS"
level = 1
[[controls."SR-02".passes]]
handler = "exec"
shared = "probe"
command = ["sh", "-c", "echo '{\\"a\\": 1}'"]
output_format = "json"
expr = "output.json.a == 2"
"""
)

SHARED_REMEDIATION_STEP = (
    METADATA
    + """
[controls."SR-01"]
name = "Remediated"
description = "A remediation step referencing a shared handler"
level = 1
[[controls."SR-01".passes]]
handler = "manual"
steps = ["Check it"]
[[controls."SR-01".remediation.handlers]]
handler = "manual"
shared = "probe"
steps = ["Fix it"]
"""
)

DECLARATIONS = {
    "shared_handlers_table": SHARED_TABLE,
    "shared_step_key": SHARED_STEP,
    "shared_remediation_step_key": SHARED_REMEDIATION_STEP,
}


@pytest.fixture(params=sorted(DECLARATIONS))
def framework_path(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    path = tmp_path / f"{request.param}.toml"
    path.write_text(DECLARATIONS[request.param], encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    (path / "README.md").write_text("# repo\n", encoding="utf-8")
    return path


def test_framework_path_refuses(framework_path: Path) -> None:
    with pytest.raises(ValueError, match=REMOVED):
        load_controls_from_framework(load_framework_config(framework_path))


def test_effective_path_refuses(framework_path: Path) -> None:
    with pytest.raises(ValueError, match=REMOVED):
        load_controls_from_effective(load_effective_config(framework_path))


def test_audit_refuses(framework_path: Path, repo: Path) -> None:
    with pytest.raises(ValueError, match=REMOVED):
        run_sieve_audit("o", "r", str(repo), "main", framework_name=str(framework_path), write_cache=False)


def test_cli_audit_refuses(
    framework_path: Path, repo: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("darnit.cli.configure_logging", lambda level: None)
    with caplog.at_level(logging.ERROR, logger="darnit"):
        exit_code = cli_main(["audit", "-f", str(framework_path), "-o", "json", "--no-fail", str(repo)])
    assert exit_code == 1
    assert any("Failed to load framework" in r.message and REMOVED in r.message for r in caplog.records)
