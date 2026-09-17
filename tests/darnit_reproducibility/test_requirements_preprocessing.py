"""Preprocessing of requirements.txt before PEP 440 parsing (feature 037).

Order matters and is fixed by research.md R5: continuations are joined BEFORE
hashes are collected, because `pip-compile --generate-hashes` puts hashes on
continuation lines.
"""

from __future__ import annotations

import pytest
from darnit_reproducibility.requirements_pins import (
    FileClassification,
    classify,
    parse,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


class TestContinuationJoining:
    @pytest.mark.unit
    def test_hashes_on_continuation_lines_are_collected(self) -> None:
        """The shape pip-compile actually emits.

        Collecting hashes before joining continuations would see a bare
        `click==8.1.7` and classify the file one tier too low.
        """
        text = f"click==8.1.7 \\\n    --hash=sha256:{HASH_A} \\\n    --hash=sha256:{HASH_B}\n"
        lines, problem = parse(text)
        assert problem is None
        assert len(lines) == 1
        assert lines[0].hashes == [f"sha256:{HASH_A}", f"sha256:{HASH_B}"]
        assert classify(text).classification is FileClassification.HASH_PINNED

    @pytest.mark.unit
    def test_trailing_continuation_at_eof_is_not_dropped(self) -> None:
        lines, _ = parse(f"click==8.1.7 \\\n    --hash=sha256:{HASH_A}")
        assert len(lines) == 1


class TestComments:
    @pytest.mark.unit
    def test_full_comment_and_blank_lines_are_dropped(self) -> None:
        lines, _ = parse("# a comment\n\n   \nnumpy==1.0\n")
        assert [ln.name for ln in lines] == ["numpy"]

    @pytest.mark.unit
    def test_trailing_comment_is_stripped(self) -> None:
        lines, _ = parse("numpy==1.0  # via requirements.in\n")
        assert lines[0].name == "numpy"

    @pytest.mark.unit
    def test_url_fragment_is_not_treated_as_a_comment(self) -> None:
        """pip treats `#` as a comment only at line start or after whitespace."""
        lines, problem = parse("pkg @ git+https://x/y@%s#egg=pkg\n" % ("d" * 40))
        assert problem is None
        assert len(lines) == 1


class TestSkippedLines:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        "line",
        [
            "--index-url https://example.invalid/simple",
            "--extra-index-url https://example.invalid/other",
            "--find-links /tmp/wheels",
            "--no-binary :all:",
            "--require-hashes",
            "--trusted-host example.invalid",
            "-i https://example.invalid/simple",
            "-f /tmp/wheels",
        ],
    )
    def test_option_lines_are_skipped(self, line: str) -> None:
        lines, problem = parse(line + "\nnumpy==1.0\n")
        assert problem is None
        assert [ln.name for ln in lines] == ["numpy"]

    @pytest.mark.unit
    @pytest.mark.parametrize("line", ["-e .", "--editable .", ".", "./", "../sibling"])
    def test_self_references_are_skipped(self, line: str) -> None:
        lines, problem = parse(line + "\nnumpy==1.0\n")
        assert problem is None
        assert [ln.name for ln in lines] == ["numpy"]


class TestIncludes:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        "line",
        ["-r base.txt", "--requirement base.txt", "-c constraints.txt", "--constraint c.txt"],
    )
    def test_includes_make_the_file_not_inspectable(self, line: str) -> None:
        """Following includes is out of scope for v0; an unresolved include
        means the file has not been fully inspected (FR-007)."""
        _lines, problem = parse(line + "\n")
        assert problem is not None
        assert "include" in problem
