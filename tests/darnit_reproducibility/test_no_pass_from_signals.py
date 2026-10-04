"""Reproducibility controls do not PASS on text or file-presence signals (feature 044, US3).

FR-010: the five reproducibility step types decide from signals, so they
register the ceiling ``{fail}``; a PASS needs a corpus-backed promotion. FR-011:
the signals they find reach the control's later steps (model judgment, human
review) as evidence. SC-004: a text mention alone concludes 0 controls PASS.

These run controls through the orchestrator rather than calling handlers
directly: the handler may still report what it saw, and the property under test
is what the control concludes from it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from darnit_reproducibility.implementation import ReproducibilityImplementation

from darnit.config import load_controls_from_framework, load_framework_config
from darnit.config.framework_schema import HandlerInvocation
from darnit.sieve.handler_registry import get_sieve_handler_registry
from darnit.sieve.models import CheckContext, ControlSpec, SieveResult
from darnit.sieve.orchestrator import SieveOrchestrator

STEP_TYPES = (
    "repro_hermetic_build",
    "repro_provenance_exists",
    "repro_bit_for_bit",
    "repro_deps_pinned",
    "repro_build_env_declared",
)

# A release workflow that mentions signing only in a comment and produces no
# provenance: the #453 reproduction.
COMMENT_ONLY_WORKFLOW = """\
name: release
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # TODO: cosign sign the artifacts once we have a key
      - run: make dist
"""

# Per step type: files that make its handler report a positive signal, and the
# evidence key the signal is recorded under.
SIGNAL_REPOS: dict[str, tuple[dict[str, str], str]] = {
    "repro_provenance_exists": ({".github/workflows/release.yml": COMMENT_ONLY_WORKFLOW}, "provenance_signals"),
    "repro_deps_pinned": ({"package.json": "{}\n", "package-lock.json": "{}\n"}, "lock_files_found"),
    "repro_build_env_declared": ({"flake.nix": "{ outputs = {}; }\n"}, "env_files_found"),
    "repro_hermetic_build": (
        {
            "MODULE.bazel": "",
            ".bazelrc": "build --sandbox_default_allow_network=false\n",
            ".github/workflows/build.yml": "steps:\n  - run: bazel build //...\n",
        },
        "strong_signal",
    ),
    "repro_bit_for_bit": (
        {".github/workflows/ci.yml": "env:\n  SOURCE_DATE_EPOCH: 0\n"},
        "reproducibility_signals",
    ),
}

# The only network call in the plugin; off so every verdict is a filesystem function.
OFFLINE = {"repro_hermetic_build": {"verify_witness_attestations": False}}


@pytest.fixture(autouse=True)
def _registered() -> None:
    ReproducibilityImplementation().register_sieve_handlers()


def _build(root: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def _shipped_control(control_id: str) -> ControlSpec:
    path = ReproducibilityImplementation().get_framework_config_path()
    controls = {c.control_id: c for c in load_controls_from_framework(load_framework_config(path))}
    spec = controls[control_id]
    for step in spec.metadata["handler_invocations"]:
        for key, value in OFFLINE.get(step.handler, {}).items():
            setattr(step, key, value)
    return spec


def _verify(spec: ControlSpec, repo: Path) -> SieveResult:
    context = CheckContext(
        owner="org",
        repo="repo",
        local_path=str(repo),
        default_branch="main",
        control_id=spec.control_id,
    )
    return SieveOrchestrator(stop_on_llm=True).verify(spec, context)


@pytest.mark.unit
@pytest.mark.parametrize("step_type", STEP_TYPES)
def test_step_type_registers_fail_ceiling(step_type: str) -> None:
    """FR-010: registered `{fail}`, so PASS needs a promotion on the step."""
    info = get_sieve_handler_registry().get(step_type)
    assert info is not None
    assert info.ceiling == frozenset({"fail"})


@pytest.mark.unit
def test_comment_mention_of_cosign_does_not_pass_provenance(tmp_path: Path) -> None:
    """SC-004, quickstart V4: RE-02.02 is not PASS and the mention is evidence."""
    repo = _build(tmp_path, {".github/workflows/release.yml": COMMENT_ONLY_WORKFLOW})
    result = _verify(_shipped_control("RE-02.02"), repo)

    assert result.status != "PASS"
    assert "release.yml: cosign sign" in result.evidence["provenance_signals"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "control_id",
    ["RE-01.01", "RE-01.02", "RE-02.01", "RE-02.02", "RE-03.01"],
)
def test_no_shipped_control_passes_on_signals(tmp_path: Path, control_id: str) -> None:
    """SC-004: a repository carrying every signal still has no PASS."""
    files: dict[str, str] = {}
    for repo_files, _ in SIGNAL_REPOS.values():
        files.update(repo_files)
    repo = _build(tmp_path, files)

    result = _verify(_shipped_control(control_id), repo)

    assert result.status != "PASS", result.message


@pytest.mark.unit
def test_manifest_without_lockfile_still_fails(tmp_path: Path) -> None:
    """US3 scenario 2: proof the requirement is unmet still concludes FAIL."""
    repo = _build(tmp_path, {"package.json": '{"dependencies": {"left-pad": "^1.0.0"}}\n'})
    result = _verify(_shipped_control("RE-01.01"), repo)

    assert result.status == "FAIL"
    assert result.concluded_by == "repro_deps_pinned"
    assert result.evidence["loose_manifests_found"] == ["package.json (npm package)"]


@pytest.mark.unit
@pytest.mark.parametrize("step_type", sorted(SIGNAL_REPOS))
def test_signals_reach_llm_eval(tmp_path: Path, step_type: str) -> None:
    """FR-011: a model-judgment step after the signal step is given the signals."""
    files, evidence_key = SIGNAL_REPOS[step_type]
    repo = _build(tmp_path, files)
    spec = ControlSpec(
        control_id="RE-TEST",
        level=1,
        domain="RE",
        name="SignalsReachJudgment",
        description="Signals reach the judgment step",
        metadata={
            "handler_invocations": [
                HandlerInvocation(handler=step_type, **OFFLINE.get(step_type, {})),
                HandlerInvocation(handler="llm_eval", prompt="Is the property established?"),
            ]
        },
    )

    result = _verify(spec, repo)

    assert result.status == "PENDING", result.message
    gathered = result.evidence["llm_consultation"]["gathered_evidence"]
    assert gathered.get(evidence_key), f"{evidence_key} missing from {sorted(gathered)}"
