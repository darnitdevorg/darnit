"""Every template a shipped framework defines renders, and its YAML/JSON output parses (#152).

Each template is rendered twice: with nothing detected (every ``scan.*``
key absent), and with every scan key the template names set. Every context
key the framework declares has a sample value, so this checks the template
itself, not confirmation. A template that names a variable that does not
exist, has a syntax error, or renders a ``.yml``/``.yaml``/``.json`` file
that does not parse fails here instead of in a user's remediation.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from darnit.config.merger import load_framework_config
from darnit.remediation.executor import RemediationExecutor, _check_structured

REPO_ROOT = Path(__file__).resolve().parents[3]
FRAMEWORKS = sorted(REPO_ROOT.glob("packages/*/src/*/*.toml"))
SCAN_NAME = re.compile(r"scan\.([A-Za-z_][A-Za-z0-9_]*)")


def _cases() -> list[tuple[Path, str, str | None]]:
    cases: list[tuple[Path, str, str | None]] = []
    for framework_path in FRAMEWORKS:
        framework = load_framework_config(framework_path)
        paths: dict[str, set[str]] = {}
        for control in framework.controls.values():
            for handler in control.remediation.handlers if control.remediation else []:
                extra = handler.model_extra or {}
                if isinstance(extra.get("template"), str) and isinstance(extra.get("path"), str):
                    paths.setdefault(extra["template"], set()).add(extra["path"])
        for name in sorted(framework.templates):
            for path in sorted(paths.get(name, {None})):
                cases.append((framework_path, name, path))
    return cases


CASES = _cases()


def test_shipped_frameworks_define_templates() -> None:
    assert FRAMEWORKS, "no framework TOMLs found"
    assert len(CASES) > 20


@pytest.mark.parametrize("detected", [False, True], ids=["nothing-detected", "all-detected"])
@pytest.mark.parametrize(
    ("framework_path", "template", "path"),
    CASES,
    ids=[f"{fw.stem}:{name}" + (f"->{path}" if path else "") for fw, name, path in CASES],
)
def test_template_renders(
    tmp_path: Path, framework_path: Path, template: str, path: str | None, detected: bool
) -> None:
    framework = load_framework_config(framework_path)
    executor = RemediationExecutor(
        local_path=str(tmp_path),
        owner="example-org",
        repo="example",
        templates=framework.templates,
        framework_path=str(framework_path),
        context_values=dict.fromkeys(framework.context.definitions, "sample"),
    )
    content = executor._get_template_content(template)
    assert content is not None, f"template {template!r} has no content"
    if detected:
        executor._scan_values = {f"scan.{key}": "sample" for key in SCAN_NAME.findall(content)}

    rendered = executor._substitute(content, "C-1", template)

    if path is not None:
        _check_structured(template, path, rendered)
