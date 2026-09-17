"""Classification of requirements.txt pinning strength (feature 037, issue #429).

Covers contracts/requirements-classification.md obligations T-1 through T-6.
The classifier is a pure function over text, so these tests need no fixtures
on disk and no sieve scaffolding.
"""

from __future__ import annotations

import pytest
from darnit_reproducibility.requirements_pins import (
    FileClassification,
    PinClassification,
    classify,
    parse,
)

SHA1 = "d" * 40
SHA256 = "e" * 64
HASH = "a" * 64


def _pin(line: str) -> PinClassification:
    lines, problem = parse(line + "\n")
    assert problem is None, problem
    assert len(lines) == 1, f"expected one requirement line, got {len(lines)}"
    return lines[0].pin


class TestLineClassification:
    """Contract T-1: every row of the line-classification table."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            (f"numpy==1.26.4 --hash=sha256:{HASH}", PinClassification.HASH_PINNED),
            ("numpy==1.26.4", PinClassification.EXACTLY_PINNED),
            # `===` is arbitrary equality and is still exact.
            ("numpy===1.26.4", PinClassification.EXACTLY_PINNED),
            (
                'pkg[extra]==1.0; python_version < "3.11"',
                PinClassification.EXACTLY_PINNED,
            ),
            (f"pkg @ git+https://x/y@{SHA1}", PinClassification.EXACTLY_PINNED),
            (f"pkg @ git+https://x/y@{SHA256}", PinClassification.EXACTLY_PINNED),
            # A wildcard parses with operator `==`, which is exactly why the
            # test must be on the version and not the operator (FR-008).
            ("numpy==1.*", PinClassification.NOT_PINNED),
            ("numpy>=1.0,<2.0", PinClassification.NOT_PINNED),
            ("numpy>=1.0", PinClassification.NOT_PINNED),
            ("numpy~=1.0", PinClassification.NOT_PINNED),
            ("numpy!=1.0", PinClassification.NOT_PINNED),
            ("numpy", PinClassification.NOT_PINNED),
            ("pkg @ git+https://x/y@main", PinClassification.NOT_PINNED),
            # Abbreviated ids resolve against repository state, so they do not pin.
            ("pkg @ git+https://x/y@abc1234", PinClassification.NOT_PINNED),
        ],
    )
    def test_line(self, line: str, expected: PinClassification) -> None:
        assert _pin(line) == expected

    @pytest.mark.unit
    def test_ssh_url_with_user_still_reads_the_final_fragment(self) -> None:
        """`git@host` must not be mistaken for the object id."""
        assert _pin(f"pkg @ git+ssh://git@host/repo@{SHA1}") == (PinClassification.EXACTLY_PINNED)

    @pytest.mark.unit
    def test_url_fragment_does_not_hide_the_object_id(self) -> None:
        assert _pin(f"pkg @ git+https://x/y@{SHA1}#egg=pkg") == (PinClassification.EXACTLY_PINNED)


class TestFileClassification:
    """Contract T-2, T-3, T-4, T-6: file-level rules."""

    @pytest.mark.unit
    def test_all_hashed_is_hash_pinned(self) -> None:
        text = f"numpy==1.0 --hash=sha256:{HASH}\nclick==2.0 --hash=sha256:{HASH}\n"
        assert classify(text).classification is FileClassification.HASH_PINNED

    @pytest.mark.unit
    def test_mixed_hashed_and_bare_is_version_pinned(self) -> None:
        """Contract T-3. The weakest line governs.

        A partially hashed file has no stronger guarantee than its weakest
        line, and pip's require-hashes mode refuses to install it at all.
        """
        text = f"numpy==1.0 --hash=sha256:{HASH}\nclick==2.0\n"
        assert classify(text).classification is FileClassification.VERSION_PINNED

    @pytest.mark.unit
    def test_one_floating_dependency_governs(self) -> None:
        text = "numpy==1.0\nclick>=2.0\n"
        report = classify(text)
        assert report.classification is FileClassification.UNPINNED
        assert report.unpinned == ["click>=2.0"]

    @pytest.mark.unit
    def test_vcs_sha_caps_the_file_at_version_pinned(self) -> None:
        """FR-010: a SHA pins, but it is never hash evidence.

        pip cannot enforce hashes on a VCS reference, so a file containing one
        is not a require-hashes file and must not borrow that tier's PASS.
        """
        text = f"numpy==1.0 --hash=sha256:{HASH}\npkg @ git+https://x/y@{SHA1}\n"
        assert classify(text).classification is FileClassification.VERSION_PINNED

    @pytest.mark.unit
    def test_unresolved_include_is_not_inspectable(self) -> None:
        report = classify("-r base.txt\nnumpy==1.0\n")
        assert report.classification is FileClassification.NOT_INSPECTABLE
        assert "include" in report.reason

    @pytest.mark.unit
    def test_unparseable_surviving_line_is_not_inspectable(self) -> None:
        """A line that survived preprocessing but cannot be read.

        The tool must not claim to have understood a file containing a line it
        could not parse (FR-007).
        """
        report = classify("numpy==1.0\n=== not a requirement ===\n")
        assert report.classification is FileClassification.NOT_INSPECTABLE

    @pytest.mark.unit
    @pytest.mark.parametrize("text", ["", "\n\n", "# only a comment\n", "   \n#x\n"])
    def test_no_requirement_lines(self, text: str) -> None:
        """Contract T-6. FR-011: neither good nor bad practice."""
        assert classify(text).classification is FileClassification.NO_REQUIREMENTS

    @pytest.mark.unit
    def test_option_lines_and_self_reference_do_not_count(self) -> None:
        """Contract T-4: the file classifies on its requirements alone (FR-018)."""
        text = (
            "--index-url https://example.invalid/simple\n"
            "--extra-index-url https://example.invalid/other\n"
            "--find-links /tmp/wheels\n"
            "-e .\n"
            f"numpy==1.0 --hash=sha256:{HASH}\n"
        )
        report = classify(text)
        assert report.classification is FileClassification.HASH_PINNED
        assert len(report.lines) == 1

    @pytest.mark.unit
    def test_only_option_lines_is_no_requirements(self) -> None:
        assert classify("-e .\n--index-url https://x\n").classification is (FileClassification.NO_REQUIREMENTS)

    @pytest.mark.unit
    def test_editable_vcs_is_a_dependency_not_a_self_reference(self) -> None:
        """`-e .` is the project; `-e git+...` is a dependency."""
        report = classify(f"-e git+https://x/y@{SHA1}\n")
        assert len(report.lines) == 1
        assert report.classification is FileClassification.VERSION_PINNED
