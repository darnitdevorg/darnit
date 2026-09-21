"""SC-007: the reproducibility corpus, as an explicit expectation (feature 038).

The table below is written by hand rather than captured. This feature's claim is
"these specific verdicts changed", which a reviewer should be able to read and
disagree with; a captured baseline would only assert that the code agrees with
itself.

Feature 037 needed a captured baseline because its claim was the opposite --
"nothing changed" across 213 controls. It also learned that a stored golden of
control statuses is not portable: statuses depend on whether `gh` is
authenticated. That is avoided here by disabling witness verification, which
removes the only network call in this plugin and makes every verdict a pure
filesystem function.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from darnit_reproducibility.handlers import (
    repro_bit_for_bit_handler,
    repro_build_env_declared_handler,
    repro_deps_pinned_handler,
    repro_hermetic_build_handler,
)

from .conftest import OFFLINE_CONFIG, repro_ctx

DIGEST = "sha256:" + "a" * 64

# (fixture name, files) -> expected verdict per control.
CORPUS: dict[str, dict[str, str]] = {
    "pinned_container": {"Dockerfile": f"FROM alpine@{DIGEST}\n"},
    "floating_container": {"Dockerfile": "FROM alpine:latest\n"},
    "flake_only": {"flake.nix": "{ outputs = {}; }\n"},
    "signals_only": {".github/workflows/ci.yml": "env:\n  SOURCE_DATE_EPOCH: 0\n"},
    "go_installer": {".github/workflows/ci.yml": "steps:\n  - run: go install example.com/t@latest\n"},
    "native_flags": {"Makefile": "build:\n\tgcc -march=native -o app main.c\n"},
    "empty": {},
}

EXPECTED: dict[str, dict[str, str]] = {
    "pinned_container": {"RE-01.02": "pass"},
    "floating_container": {"RE-01.02": "warn"},
    "flake_only": {"RE-01.02": "pass"},
    "signals_only": {"RE-03.01": "warn"},
    "go_installer": {"RE-02.01": "fail"},
    "native_flags": {"RE-02.01": "fail"},
    "empty": {"RE-01.02": "inconclusive", "RE-03.01": "inconclusive"},
}

HANDLERS = {
    "RE-01.01": repro_deps_pinned_handler,
    "RE-01.02": repro_build_env_declared_handler,
    "RE-02.01": repro_hermetic_build_handler,
    "RE-03.01": repro_bit_for_bit_handler,
}

#: The only controls this feature is permitted to move (FR-013).
CHANGED_BY_THIS_FEATURE = {"RE-01.02", "RE-02.01", "RE-03.01"}


def _build(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return tmp_path


@pytest.mark.unit
@pytest.mark.parametrize("fixture_name", sorted(CORPUS))
def test_corpus_matches_expected_verdicts(tmp_path: Path, fixture_name: str) -> None:
    repo = _build(tmp_path, CORPUS[fixture_name])
    ctx = repro_ctx(repo)
    for control_id, expected in EXPECTED[fixture_name].items():
        result = HANDLERS[control_id](dict(OFFLINE_CONFIG), ctx)
        assert result.status.value == expected, (
            f"{fixture_name}: {control_id} expected {expected}, got {result.status.value} -- {result.message}"
        )


@pytest.mark.unit
def test_expectations_only_cover_controls_this_feature_may_change() -> None:
    """FR-013. A verdict asserted here for RE-01.01 would mean this feature
    moved a control it promised not to touch."""
    asserted = {c for verdicts in EXPECTED.values() for c in verdicts}
    assert asserted <= CHANGED_BY_THIS_FEATURE | {"RE-01.01"}
    changed = asserted - {"RE-01.01"}
    assert changed <= CHANGED_BY_THIS_FEATURE


@pytest.mark.unit
def test_deps_pinned_is_untouched_by_this_feature(tmp_path: Path) -> None:
    """FR-013 positively: RE-01.01 keeps feature 037's behaviour exactly."""
    repo = _build(tmp_path, {"requirements.txt": "numpy==1.26.4\n"})
    result = repro_deps_pinned_handler(dict(OFFLINE_CONFIG), repro_ctx(repo))
    assert result.status.value == "warn"
    assert "transitive" in result.message
