"""Base-image pin classification (feature 038, issue #431).

Covers contracts/build-env-pinning.md obligations BE-1 through BE-7. The
classifier is a pure function over text, so these need no fixtures on disk and
no sieve scaffolding.
"""

from __future__ import annotations

import pytest
from darnit_reproducibility.container_pinning import (
    ContainerClassification,
    PinKind,
    classify,
    parse,
)

DIGEST = "sha256:" + "a" * 64


def _kinds(text: str) -> list[PinKind]:
    return [ref.pin for ref in parse(text)]


class TestReferenceClassification:
    """BE-1 through BE-6, one row each."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            (f"FROM alpine@{DIGEST}", PinKind.DIGEST),
            ("FROM alpine:latest", PinKind.TAG),
            # A specific-looking tag is still a tag: `3.12-slim-bookworm` is
            # rebuilt regularly and resolves to different bytes over time.
            ("FROM python:3.12-slim-bookworm", PinKind.TAG),
            ("FROM alpine", PinKind.TAG),
            ("FROM scratch", PinKind.SCRATCH),
            ("FROM $BASE_IMAGE", PinKind.INDETERMINATE),
            ("FROM ${BASE_IMAGE}", PinKind.INDETERMINATE),
        ],
    )
    def test_single_reference(self, line: str, expected: PinKind) -> None:
        assert _kinds(line) == [expected]

    @pytest.mark.unit
    def test_platform_flag_is_not_the_image(self) -> None:
        assert _kinds(f"FROM --platform=linux/amd64 alpine@{DIGEST}") == [PinKind.DIGEST]

    @pytest.mark.unit
    def test_lowercase_from_is_accepted(self) -> None:
        assert _kinds("from alpine:latest") == [PinKind.TAG]


class TestStageReferences:
    """BE-4. The case a naive scan gets wrong on every multi-stage build."""

    @pytest.mark.unit
    def test_stage_reference_is_not_an_image(self) -> None:
        kinds = _kinds("FROM python:3.12 AS builder\nRUN true\nFROM builder\n")
        assert kinds == [PinKind.TAG, PinKind.STAGE_REF]

    @pytest.mark.unit
    def test_stage_reference_is_case_insensitive(self) -> None:
        assert _kinds(f"FROM alpine@{DIGEST} AS Builder\nFROM builder\n")[1] is (PinKind.STAGE_REF)

    @pytest.mark.unit
    def test_repo_own_dockerfile_shape_reports_only_real_images(self) -> None:
        """The shape of packaging/container/Dockerfile in this repository."""
        text = (
            "FROM python:3.12-slim-bookworm AS builder\n"
            "RUN pip install .\n"
            "FROM python:3.12-slim-bookworm\n"
            "COPY --from=builder /app /app\n"
        )
        report = classify(text)
        assert report.classification is ContainerClassification.UNPINNED
        assert report.unpinned == [
            "python:3.12-slim-bookworm",
            "python:3.12-slim-bookworm",
        ]
        assert "builder" not in report.unpinned


class TestFileClassification:
    """BE-7 and the file-level rules."""

    @pytest.mark.unit
    def test_all_digest_pinned(self) -> None:
        text = f"FROM alpine@{DIGEST} AS a\nFROM alpine@{DIGEST}\n"
        assert classify(text).classification is ContainerClassification.PINNED

    @pytest.mark.unit
    def test_weakest_reference_governs(self) -> None:
        """BE-7: one floating stage is enough."""
        report = classify(f"FROM alpine@{DIGEST}\nFROM debian:bookworm\n")
        assert report.classification is ContainerClassification.UNPINNED
        assert report.unpinned == ["debian:bookworm"]

    @pytest.mark.unit
    def test_scratch_only_is_pinned(self) -> None:
        assert classify("FROM scratch\nCOPY app /app\n").classification is (ContainerClassification.PINNED)

    @pytest.mark.unit
    def test_no_from_lines(self) -> None:
        assert classify("RUN echo hi\n").classification is (ContainerClassification.NO_IMAGES)

    @pytest.mark.unit
    def test_commented_from_is_ignored(self) -> None:
        report = classify("# FROM alpine:latest\nFROM scratch\n")
        assert report.classification is ContainerClassification.PINNED
        assert report.unpinned == []
