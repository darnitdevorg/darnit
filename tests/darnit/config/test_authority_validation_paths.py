"""Authority validation runs on every control-loading path (feature 041 T006).

Before feature 041 the check ran only in ``control_from_effective``; the MCP
audit path (``tools/audit.py`` -> ``load_controls_from_framework``) skipped
it, so a framework TOML that widened a step's authority loaded silently.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit.config.control_loader import (
    control_from_effective,
    control_from_framework,
    load_controls_from_effective,
    load_controls_from_framework,
)
from darnit.config.framework_schema import (
    ControlConfig,
    FrameworkConfig,
    FrameworkMetadata,
    HandlerInvocation,
)
from darnit.config.merger import EffectiveControl, load_effective_config
from darnit.core.errors import AuthorityViolation

WIDENING = {"handler": "pattern", "files": ["README.md"], "pattern": "x", "concludes": ["pass"]}

FRAMEWORK_TOML = """
[metadata]
name = "widening-fw"
display_name = "Widening"
version = "0.0.1"
spec_version = "t"

[controls."WID-01"]
name = "Widening"
description = "Widens a pattern step without a promotion"
level = 1
domain = "WD"

[[controls."WID-01".passes]]
handler = "pattern"
files = ["README.md"]
pattern = "x"
concludes = ["pass"]
"""


def _framework() -> FrameworkConfig:
    return FrameworkConfig(
        metadata=FrameworkMetadata(
            name="widening-fw",
            display_name="Widening",
            version="0.0.1",
            spec_version="t",
        ),
        controls={
            "WID-01": ControlConfig(
                name="Widening",
                description="Widens a pattern step",
                level=1,
                domain="WD",
                passes=[HandlerInvocation(**WIDENING)],
            )
        },
    )


def _assert_names_step(excinfo: pytest.ExceptionInfo[AuthorityViolation]) -> None:
    text = str(excinfo.value)
    for fragment in ("WID-01", "pass[0]", "pass"):
        assert fragment in text, (fragment, text)


def test_load_controls_from_framework_validates() -> None:
    with pytest.raises(AuthorityViolation) as excinfo:
        load_controls_from_framework(_framework())
    _assert_names_step(excinfo)
    assert "widening-fw" in str(excinfo.value)


def test_control_from_framework_validates() -> None:
    config = _framework()
    with pytest.raises(AuthorityViolation) as excinfo:
        control_from_framework("WID-01", config.controls["WID-01"])
    _assert_names_step(excinfo)


def test_control_from_effective_validates() -> None:
    effective = EffectiveControl(
        control_id="WID-01",
        name="Widening",
        description="Widens a pattern step",
        level=1,
        domain="WD",
        passes_config=[dict(WIDENING)],
    )
    with pytest.raises(AuthorityViolation) as excinfo:
        control_from_effective("WID-01", effective)
    _assert_names_step(excinfo)


def test_load_controls_from_effective_validates(tmp_path: Path) -> None:
    framework_path = tmp_path / "widening.toml"
    framework_path.write_text(FRAMEWORK_TOML, encoding="utf-8")
    config = load_effective_config(framework_path)
    with pytest.raises(AuthorityViolation) as excinfo:
        load_controls_from_effective(config)
    _assert_names_step(excinfo)
    assert "widening-fw" in str(excinfo.value)


def test_shared_handler_declarations_survive_resolution() -> None:
    config = FrameworkConfig(
        metadata=FrameworkMetadata(name="shared-fw", display_name="S", version="0", spec_version="t"),
        shared_handlers={"readme_check": {"handler": "file_exists", "files": ["README.md"]}},
        controls={
            "SH-01": ControlConfig(
                name="Shared",
                description="Existence via a shared handler",
                level=1,
                domain="SH",
                passes=[HandlerInvocation(handler="readme_check", shared="readme_check", existence=True)],
            )
        },
    )
    [spec] = load_controls_from_framework(config)
    [step] = spec.metadata["handler_invocations"]
    assert step.handler == "file_exists"
    assert step.existence is True
