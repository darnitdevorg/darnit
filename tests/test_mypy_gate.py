"""The type-check gate (scripts/mypy_gate.py) fails on new and hard-tier errors."""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("mypy_gate", REPO_ROOT / "scripts" / "mypy_gate.py")
assert _spec and _spec.loader
gate = importlib.util.module_from_spec(_spec)
sys.modules["mypy_gate"] = gate
_spec.loader.exec_module(gate)

SOFT = (
    'packages/darnit/src/darnit/x.py: error: Argument 1 to "f" has incompatible type "str"; expected "int"  [arg-type]'
)
HARD = 'packages/darnit/src/darnit/x.py: error: Module has no attribute "nonexistent"  [attr-defined]'


def test_normalize_strips_line_and_column_numbers() -> None:
    assert gate.normalize("pkg/a.py:12: error: Bad thing  [misc]") == "pkg/a.py: error: Bad thing  [misc]"
    assert gate.normalize("pkg/a.py:12:5: error: Bad thing  [misc]") == "pkg/a.py: error: Bad thing  [misc]"
    assert (
        gate.normalize('pkg/a.py:40: error: Name "x" already defined on line 31  [no-redef]')
        == 'pkg/a.py: error: Name "x" already defined on line N  [no-redef]'
    )
    assert gate.normalize("pkg/a.py:12: note: See docs") is None


def test_unrecognized_mypy_output_is_an_error_not_a_pass() -> None:
    with pytest.raises(gate.GateError):
        gate.parse_mypy_output("mypy: can't read file 'nope.py': No such file or directory")


def test_baselined_errors_pass() -> None:
    result = gate.compare([SOFT], Counter([SOFT]), Counter())
    assert result.ok


def test_new_error_fails() -> None:
    new = SOFT.replace('"f"', '"g"')
    result = gate.compare([SOFT, new], Counter([SOFT]), Counter())

    assert not result.ok
    assert result.new == [new]


def test_extra_occurrence_of_a_baselined_error_fails() -> None:
    result = gate.compare([SOFT, SOFT], Counter([SOFT]), Counter())

    assert not result.ok
    assert result.new == [SOFT]


def test_hard_tier_error_fails() -> None:
    result = gate.compare([HARD], Counter(), Counter())

    assert not result.ok
    assert result.hard == [HARD]


def test_hard_tier_error_fails_even_when_baselined() -> None:
    result = gate.compare([HARD], Counter([HARD]), Counter())

    assert not result.ok
    assert result.hard == [HARD]
    assert result.hard_in_baseline == [HARD]


@pytest.mark.parametrize("code", ["attr-defined", "call-arg", "name-defined"])
def test_every_hard_tier_code_fails(code: str) -> None:
    error = f"pkg/a.py: error: something  [{code}]"
    assert not gate.compare([error], Counter([error]), Counter()).ok


def test_allow_listed_hard_tier_error_passes_and_is_reported() -> None:
    result = gate.compare([HARD], Counter(), Counter([HARD]))

    assert result.ok
    assert result.allowed_hard == [HARD]
    assert HARD in gate.render(result, 0)


def test_stale_entries_fail() -> None:
    result = gate.compare([], Counter([SOFT]), Counter([HARD]))

    assert not result.ok
    assert result.stale_baseline == [SOFT]
    assert result.stale_allowlist == [HARD]


def test_allowlist_entry_needs_a_reason() -> None:
    with pytest.raises(gate.GateError, match="reason"):
        gate.load_allowlist(f"{HARD}\n")
    assert gate.load_allowlist(f"# removed by #1\n{HARD}\n") == Counter([HARD])


def test_allowlist_holds_only_hard_tier_errors() -> None:
    with pytest.raises(gate.GateError, match="not a hard-tier"):
        gate.load_allowlist(f"# reason\n{SOFT}\n")


def test_update_refuses_hard_tier_errors(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.txt"

    assert gate.update([SOFT, HARD], Counter(), baseline) == 1
    assert not baseline.exists()


def test_update_writes_soft_errors_only(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.txt"

    assert gate.update([SOFT, HARD], Counter([HARD]), baseline) == 0
    assert gate.load_baseline(baseline.read_text()) == Counter([SOFT])


def test_committed_baseline_and_allowlist_are_well_formed() -> None:
    baseline = gate.load_baseline(gate.BASELINE_PATH.read_text())
    gate.load_allowlist(gate.ALLOWLIST_PATH.read_text())

    assert baseline
    assert not [e for e in baseline if gate.is_hard_tier(e)]


def _project(tmp_path: Path, body: str) -> list[str]:
    (tmp_path / "mypy.ini").write_text("[mypy]\nshow_error_codes = True\n")
    module = tmp_path / "mod.py"
    module.write_text(body)
    return ["--", "--config-file", str(tmp_path / "mypy.ini"), "--cache-dir", str(tmp_path / ".cache"), str(module)]


def test_gate_fails_on_a_real_missing_attribute(tmp_path: Path, capsys) -> None:
    """End to end: real mypy, a call to an attribute that does not exist."""
    args = _project(tmp_path, "import os\n\nos.nonexistent()\n")
    empty = tmp_path / "empty.txt"
    empty.write_text("")

    status = gate.main(["--baseline", str(empty), "--allowlist", str(empty), *args])

    out = capsys.readouterr().out
    assert status == 1
    assert 'Module has no attribute "nonexistent"  [attr-defined]' in out
    assert "mypy gate: FAIL" in out


def test_gate_fails_on_a_real_new_error(tmp_path: Path, capsys) -> None:
    args = _project(tmp_path, "x: int = 'a'\n")
    empty = tmp_path / "empty.txt"
    empty.write_text("")

    status = gate.main(["--baseline", str(empty), "--allowlist", str(empty), *args])

    out = capsys.readouterr().out
    assert status == 1
    assert "[assignment]" in out
    assert "new 1" in out


def test_gate_passes_a_clean_module(tmp_path: Path, capsys) -> None:
    args = _project(tmp_path, "x: int = 1\n")
    empty = tmp_path / "empty.txt"
    empty.write_text("")

    assert gate.main(["--baseline", str(empty), "--allowlist", str(empty), *args]) == 0
    assert "mypy gate: PASS" in capsys.readouterr().out
