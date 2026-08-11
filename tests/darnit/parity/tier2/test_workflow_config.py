"""Governance-critical workflow-config tests (feature 028 T024).

Parses `.github/workflows/parity-tier2.yml` and asserts the properties
required by contract tier2-workflow.md (T2-1..T2-6, T2-10, T2-11). Also
enforces SC-005a by scanning all workflow files for stray
ANTHROPIC_API_KEY references.

LC2 fix: pure-Python file iteration, no `subprocess grep`; portable
across Linux/macOS/Windows CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

WORKFLOWS_DIR = Path(".github/workflows")
TIER2_WORKFLOW = WORKFLOWS_DIR / "parity-tier2.yml"


def _load_workflow() -> dict:
    """Parse the Tier 2 workflow YAML."""
    try:
        import yaml
    except ImportError:  # pragma: no cover
        pytest.skip("PyYAML not installed")
    if not TIER2_WORKFLOW.exists():
        pytest.fail(f"Tier 2 workflow missing: {TIER2_WORKFLOW}")
    with TIER2_WORKFLOW.open() as f:
        return yaml.safe_load(f)


class TestGovernanceInvariants:
    def test_t2_1_only_workflow_dispatch_trigger(self) -> None:
        """T2-1: workflow_dispatch is the ONLY trigger."""
        workflow = _load_workflow()
        # PyYAML parses `on:` as True (Python bool) in some versions;
        # accept either key.
        triggers = workflow.get("on") or workflow.get(True)
        assert triggers is not None, "workflow must have an `on:` block"
        assert isinstance(triggers, dict)
        keys = set(triggers.keys())
        assert keys == {"workflow_dispatch"}, f"only `workflow_dispatch` allowed, found: {keys}"

    def test_t2_2_environment_declared(self) -> None:
        """T2-2: job MUST declare `environment: parity-tier2`."""
        workflow = _load_workflow()
        jobs = workflow.get("jobs", {})
        assert "tier2" in jobs, "job named `tier2` required"
        assert jobs["tier2"].get("environment") == "parity-tier2"

    def test_t2_5_permissions_contents_read_only(self) -> None:
        """T2-5: `permissions: contents: read` and NO write scope."""
        workflow = _load_workflow()
        jobs = workflow.get("jobs", {})
        tier2 = jobs["tier2"]
        perms = tier2.get("permissions")
        assert perms is not None, "job must declare `permissions:`"
        assert perms.get("contents") == "read", f"contents scope must be read, got {perms.get('contents')!r}"
        # No other keys with 'write' value.
        for k, v in perms.items():
            assert v != "write", f"forbidden write scope: {k}"

    def test_t2_10_no_api_key_input(self) -> None:
        """T2-10: workflow MUST NOT accept an api_key input (governance
        regression guard)."""
        workflow = _load_workflow()
        triggers = workflow.get("on") or workflow.get(True)
        dispatch = triggers.get("workflow_dispatch", {})
        inputs = dispatch.get("inputs", {}) if isinstance(dispatch, dict) else {}
        for name in inputs or {}:
            assert "api_key" not in name.lower(), f"forbidden input {name!r} (T2-10)"

    def test_t2_11_artifact_upload_on_any_exit_code(self) -> None:
        """T2-11: upload-artifact runs with `if: always()`."""
        workflow = _load_workflow()
        steps = workflow["jobs"]["tier2"]["steps"]
        upload_steps = [s for s in steps if isinstance(s, dict) and "uses" in s and "upload-artifact" in s["uses"]]
        assert len(upload_steps) >= 1
        for step in upload_steps:
            # PyYAML parses `if:` as True key too on some versions; check both.
            condition = step.get("if") or step.get(True)
            assert condition == "always()" or condition is True, (
                f"upload step must be `if: always()`, got {condition!r}"
            )


class TestApiKeyExclusivity:
    def test_sc_005a_no_stray_anthropic_key_references(self) -> None:
        """SC-005a + T2-4: `ANTHROPIC_API_KEY` MUST NOT appear in any
        workflow file other than `parity-tier2.yml`. Pure-Python file
        iteration; no `grep` subprocess (LC2)."""
        if not WORKFLOWS_DIR.exists():
            pytest.skip("no .github/workflows directory")

        offenders: list[str] = []
        for wf in list(WORKFLOWS_DIR.glob("*.yml")) + list(WORKFLOWS_DIR.glob("*.yaml")):
            if wf.name == TIER2_WORKFLOW.name:
                continue
            if "ANTHROPIC_API_KEY" in wf.read_text():
                offenders.append(str(wf))
        assert not offenders, f"ANTHROPIC_API_KEY MUST only appear in parity-tier2.yml. Offenders: {offenders}"


# ---------------------------------------------------------------------------
# Feature 029: OpenAI Tier 2 workflow config tests (T018)
# ---------------------------------------------------------------------------

import re  # noqa: E402

TIER2_OPENAI_WORKFLOW = WORKFLOWS_DIR / "parity-tier2-openai.yml"


def _load_openai_workflow() -> dict:
    """Parse the Tier 2 OpenAI workflow YAML."""
    try:
        import yaml
    except ImportError:  # pragma: no cover
        pytest.skip("PyYAML not installed")
    if not TIER2_OPENAI_WORKFLOW.exists():
        pytest.fail(f"Tier 2 OpenAI workflow missing: {TIER2_OPENAI_WORKFLOW}")
    with TIER2_OPENAI_WORKFLOW.open() as f:
        return yaml.safe_load(f)


class TestOpenAIWorkflowGovernance:
    def test_ow_1_only_workflow_dispatch(self) -> None:
        """OW-1: workflow_dispatch is the ONLY trigger."""
        workflow = _load_openai_workflow()
        triggers = workflow.get("on") or workflow.get(True)
        assert isinstance(triggers, dict)
        assert set(triggers) == {"workflow_dispatch"}

    def test_ow_4_environment_declared(self) -> None:
        """OW-4: environment: parity-tier2-openai."""
        workflow = _load_openai_workflow()
        assert workflow["jobs"]["tier2"].get("environment") == "parity-tier2-openai"

    def test_ow_6_permissions_read_only(self) -> None:
        """OW-6: contents: read; no write scopes."""
        workflow = _load_openai_workflow()
        perms = workflow["jobs"]["tier2"].get("permissions")
        assert perms is not None
        assert perms.get("contents") == "read"
        for k, v in perms.items():
            assert v != "write", f"forbidden write scope: {k}"

    def test_ow_13_no_api_key_input(self) -> None:
        """OW-13 (T2-10 equivalent): no api_key workflow input."""
        workflow = _load_openai_workflow()
        triggers = workflow.get("on") or workflow.get(True)
        dispatch = triggers["workflow_dispatch"]
        inputs = dispatch.get("inputs", {}) if isinstance(dispatch, dict) else {}
        for name in inputs or {}:
            assert "api_key" not in name.lower(), f"forbidden input {name!r} (OW-13)"

    def test_ow_14_artifact_upload_always(self) -> None:
        """OW-14: upload-artifact runs with if: always()."""
        workflow = _load_openai_workflow()
        steps = workflow["jobs"]["tier2"]["steps"]
        upload_steps = [s for s in steps if isinstance(s, dict) and "uses" in s and "upload-artifact" in s["uses"]]
        assert upload_steps, "no upload-artifact step found"
        for step in upload_steps:
            condition = step.get("if") or step.get(True)
            assert condition in ("always()", True), f"upload step must be `if: always()`, got {condition!r}"

    def test_sc_010_openai_workflow_pins_versioned_model(self) -> None:
        """SC-010: the default OpenAI model MUST be a version-suffixed
        string (e.g. gpt-4o-2024-08-06); a moving alias like gpt-4o
        fails this test."""
        workflow = _load_openai_workflow()
        triggers = workflow.get("on") or workflow.get(True)
        inputs = triggers["workflow_dispatch"]["inputs"]
        assert "model" in inputs, "workflow must expose a `model` input"
        default_model = inputs["model"].get("default")
        assert default_model is not None, "model input must have a default"

        # Two accepted version-pin shapes:
        #   date-suffixed: gpt-4o-2024-08-06
        #   dotted-version: gpt-4o.1
        date_shape = re.fullmatch(r"[a-z0-9\-]+-\d{4}-\d{2}-\d{2}", default_model)
        dot_shape = re.fullmatch(r"[a-z0-9\-]+\.\d+", default_model)
        assert date_shape or dot_shape, (
            f"OpenAI model default {default_model!r} must be a versioned pin "
            "(e.g. gpt-4o-2024-08-06 or gpt-4o.1), not a moving alias"
        )


class TestOpenAIApiKeyExclusivity:
    """SC-002 + OW-7: OPENAI_API_KEY MUST appear only in parity-tier2-openai.yml."""

    def test_sc_002_no_stray_openai_key_references(self) -> None:
        offenders: list[str] = []
        for wf in list(WORKFLOWS_DIR.glob("*.yml")) + list(WORKFLOWS_DIR.glob("*.yaml")):
            if wf.name == TIER2_OPENAI_WORKFLOW.name:
                continue
            if "OPENAI_API_KEY" in wf.read_text():
                offenders.append(str(wf))
        assert not offenders, f"OPENAI_API_KEY MUST only appear in parity-tier2-openai.yml. Offenders: {offenders}"

    def test_ow_9_no_anthropic_key_in_openai_workflow(self) -> None:
        """OW-9: the OpenAI workflow does NOT expose ANTHROPIC_API_KEY."""
        content = TIER2_OPENAI_WORKFLOW.read_text()
        assert "ANTHROPIC_API_KEY" not in content, "parity-tier2-openai.yml must not reference ANTHROPIC_API_KEY (OW-9)"

    def test_ow_8_no_openai_key_in_claude_workflow(self) -> None:
        """OW-8: the Claude workflow does NOT expose OPENAI_API_KEY."""
        content = TIER2_WORKFLOW.read_text()
        assert "OPENAI_API_KEY" not in content, "parity-tier2.yml must not reference OPENAI_API_KEY (OW-8)"
